"""Single wrapper around the official OpenAI SDK. Models come from settings only."""
import base64
import json
import logging
import re
from typing import Optional

from backend.config import settings
from backend.errors import AIConfigError, AIServiceError

log = logging.getLogger(__name__)
_client = None
_client_key = None

IMAGE_PROMPT = ("Describe this educational image (diagram, chart, equation or figure) factually in 2-5 sentences. "
                "Transcribe visible labels and text. If something is unclear, say so. Do not invent details.")


def is_configured() -> bool:
    return bool(settings.openai_api_key)


def require_configured() -> None:
    if not is_configured():
        raise AIConfigError("OPENAI_API_KEY is not set. Add it to your .env file to enable AI features.")


def get_client():
    global _client, _client_key
    require_configured()
    if _client is None or _client_key != settings.openai_api_key:
        from openai import OpenAI
        _client = OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout, max_retries=2)
        _client_key = settings.openai_api_key
    return _client


def _call(fn, *args, **kwargs):
    import openai
    try:
        return fn(*args, **kwargs)
    except openai.AuthenticationError:
        raise AIServiceError("OpenAI rejected the API key.")
    except openai.RateLimitError:
        raise AIServiceError("OpenAI rate limit or quota reached.")
    except openai.APIConnectionError:
        raise AIServiceError("Could not reach the OpenAI API.")
    except openai.OpenAIError as exc:
        log.warning("OpenAI error: %s", type(exc).__name__)
        raise AIServiceError("The OpenAI request failed.")


def _chat(messages: list, json_mode: bool = False, model: Optional[str] = None) -> str:
    kwargs = {"model": model or settings.openai_model, "messages": messages}
    if settings.openai_temperature is not None:
        kwargs["temperature"] = settings.openai_temperature
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = _call(get_client().chat.completions.create, **kwargs)
    return (resp.choices[0].message.content or "").strip()


def parse_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise AIServiceError("The AI returned a malformed response.")
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            raise AIServiceError("The AI returned a malformed response.")
    if not isinstance(data, dict):
        raise AIServiceError("The AI returned an unexpected response shape.")
    return data


def chat_json(system: str, user: str, history: Optional[list] = None) -> dict:
    messages = [{"role": "system", "content": system + "\nRespond with a single valid JSON object only."}]
    messages += history or []
    messages.append({"role": "user", "content": user})
    return parse_json(_chat(messages, json_mode=True))


def describe_image(data: bytes, mime: str) -> str:
    url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    content = [{"type": "text", "text": IMAGE_PROMPT}, {"type": "image_url", "image_url": {"url": url}}]
    return _chat([{"role": "user", "content": content}], model=settings.vision_model)


def embed(texts: list) -> list:
    resp = _call(get_client().embeddings.create, model=settings.openai_embedding_model, input=texts)
    return [d.embedding for d in resp.data]


def transcribe(path: str) -> list:
    """Returns [{'start','end','text'}]; marks 'no_timestamps' when the API gave plain text only."""
    client = get_client()
    with open(path, "rb") as fh:
        resp = _call(client.audio.transcriptions.create, model=settings.openai_transcription_model, file=fh,
                     response_format="verbose_json", timestamp_granularities=["segment"])
    out = []
    for s in getattr(resp, "segments", None) or []:
        g = (lambda k, s=s: s.get(k) if isinstance(s, dict) else getattr(s, k, None))
        text = (g("text") or "").strip()
        if text:
            out.append({"start": float(g("start") or 0), "end": float(g("end") or 0), "text": text})
    if not out and getattr(resp, "text", None):
        out.append({"start": 0.0, "end": 0.0, "text": resp.text.strip(), "no_timestamps": True})
    return out