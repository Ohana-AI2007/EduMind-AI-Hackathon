"""Forwards browser /api/* calls to the FastAPI backend."""
import httpx
from flask import Response, jsonify

import config

_client = httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0))


def _error(status, code, message):
    return jsonify({"error": {"code": code, "message": message}}), status


def forward(req, path):
    if ".." in path.split("/"):
        return _error(400, "bad_request", "Invalid path.")
    url = f"{config.BACKEND_URL.rstrip('/')}/api/{path}"
    headers = {}
    uid = req.headers.get("X-User-Id")
    if uid:
        headers["X-User-Id"] = uid
    kwargs = {"params": list(req.args.items(multi=True))}
    if req.files:
        kwargs["files"] = [(k, (f.filename, f.read(), f.mimetype)) for k, f in req.files.items()]
        if req.form:
            kwargs["data"] = req.form.to_dict()
    elif req.method in ("POST", "PUT", "PATCH"):
        body = req.get_data()
        if body:
            kwargs["content"] = body
            headers["Content-Type"] = req.headers.get("Content-Type", "application/json")
    try:
        r = _client.request(req.method, url, headers=headers, **kwargs)
    except httpx.HTTPError:
        return _error(502, "backend_unreachable", "Can't reach the server. Is the backend running on port 8000?")
    if r.status_code == 204:
        return Response(status=204)
    return Response(r.content, status=r.status_code, content_type=r.headers.get("content-type", "application/json"))