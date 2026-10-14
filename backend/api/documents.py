from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dependencies import get_db, get_user_id
from backend.errors import NotFoundError
from backend.models import Chunk, Document
from backend.schemas import ChunkDetail, CitationOut, DocumentOut, DocumentUploadResponse
from backend.services import document_service
from backend.services.retrieval_service import to_citation, to_retrieved

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _own(db: Session, user_id: str, document_id: str) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.user_id != user_id:
        raise NotFoundError("Document not found.")
    return doc


@router.post("/upload", response_model=DocumentUploadResponse, status_code=202)
def upload(background: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db),
           user_id: str = Depends(get_user_id)):
    doc = document_service.create_document_from_upload(db, user_id, file)
    background.add_task(document_service.process_document, doc.id)
    return DocumentUploadResponse(document=DocumentOut.model_validate(doc),
                                  message="Upload accepted. Poll GET /api/documents/{id}/status until status is 'ready'.")


@router.get("", response_model=list[DocumentOut])
def list_documents(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db),
                   user_id: str = Depends(get_user_id)):
    return db.scalars(select(Document).where(Document.user_id == user_id).order_by(Document.created_at.desc())
                      .limit(limit).offset(offset)).all()


@router.get("/chunks/{chunk_id}", response_model=ChunkDetail)
def get_chunk(chunk_id: str, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    """Citation lookup: original location plus the full passage and its neighbours."""
    row = db.execute(select(Chunk, Document.filename).join(Document, Document.id == Chunk.document_id)
                     .where(Chunk.id == chunk_id, Chunk.user_id == user_id)).first()
    if row is None:
        raise NotFoundError("Source chunk not found (the document may have been deleted).")
    chunk, name = row
    near = {c.chunk_index: c.text for c in db.scalars(select(Chunk).where(
        Chunk.document_id == chunk.document_id, Chunk.chunk_index.in_([chunk.chunk_index - 1, chunk.chunk_index + 1])))}
    return ChunkDetail(chunk_index=chunk.chunk_index, citation=to_citation(to_retrieved(chunk, name, None), include_excerpt=False),
                       text=chunk.text, previous_text=near.get(chunk.chunk_index - 1), next_text=near.get(chunk.chunk_index + 1))


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return _own(db, user_id, document_id)


@router.get("/{document_id}/status", response_model=DocumentOut)
def get_status(document_id: str, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return _own(db, user_id, document_id)


@router.get("/{document_id}/chunks", response_model=list[CitationOut])
def list_chunks(document_id: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    doc = _own(db, user_id, document_id)
    rows = db.scalars(select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.chunk_index).limit(limit).offset(offset)).all()
    return [to_citation(to_retrieved(c, doc.filename, None)) for c in rows]


@router.post("/{document_id}/reprocess", response_model=DocumentOut, status_code=202)
def reprocess(document_id: str, background: BackgroundTasks, db: Session = Depends(get_db),
              user_id: str = Depends(get_user_id)):
    doc = _own(db, user_id, document_id)
    doc.status = "processing"
    db.commit()
    background.add_task(document_service.process_document, doc.id)
    return doc


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    document_service.delete_document(db, _own(db, user_id, document_id))