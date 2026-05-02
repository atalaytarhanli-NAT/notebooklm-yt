from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from notebooklm import NotebookLMClient
from notebooklm.exceptions import NotebookLMError
from notebooklm.rpc.types import (
    AudioFormat,
    AudioLength,
    InfographicDetail,
    InfographicOrientation,
    InfographicStyle,
    QuizDifficulty,
    QuizQuantity,
    ReportFormat,
)
from notebooklm.types import ArtifactStatus

from .config import settings

logger = logging.getLogger(__name__)

_client_lock = asyncio.Lock()
_client: NotebookLMClient | None = None


async def _get_client() -> NotebookLMClient:
    global _client
    async with _client_lock:
        if _client is not None and _client.is_connected:
            return _client
        os.environ.setdefault("NOTEBOOKLM_HOME", settings.notebooklm_home)
        Path(settings.notebooklm_home).mkdir(parents=True, exist_ok=True)
        Path(settings.artifacts_dir).mkdir(parents=True, exist_ok=True)
        if settings.notebooklm_auth_json:
            os.environ["NOTEBOOKLM_AUTH_JSON"] = settings.notebooklm_auth_json
        try:
            client = await NotebookLMClient.from_storage()
            await client.__aenter__()
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="NotebookLM auth missing. Set NOTEBOOKLM_AUTH_JSON env var.",
            ) from exc
        except Exception as exc:
            logger.exception("NotebookLM client init failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"NotebookLM auth failed: {exc}. Re-run `notebooklm login` and refresh NOTEBOOKLM_AUTH_JSON.",
            ) from exc
        _client = client
        return _client


async def reset_client() -> None:
    global _client
    async with _client_lock:
        if _client is not None:
            try:
                await _client.__aexit__(None, None, None)
            except Exception:
                pass
            _client = None


def _serialize_notebook(nb: Any) -> dict[str, Any]:
    return {
        "id": getattr(nb, "id", None),
        "title": getattr(nb, "title", None),
        "created_at": getattr(nb, "created_at", None).isoformat()
        if getattr(nb, "created_at", None)
        else None,
    }


_SOURCE_STATUS_NAME = {1: "processing", 2: "ready", 3: "error", 5: "preparing"}


def _serialize_source(src: Any) -> dict[str, Any]:
    raw_status = getattr(src, "status", None)
    raw_kind = getattr(src, "kind", None) or getattr(src, "type", None)

    type_str: str | None = None
    if raw_kind is not None:
        if hasattr(raw_kind, "value"):
            type_str = str(raw_kind.value).lower()
        else:
            type_str = str(raw_kind).split(".")[-1].lower()

    status_str: str | None = None
    if raw_status is not None:
        if hasattr(raw_status, "name"):
            status_str = raw_status.name.lower()
        elif isinstance(raw_status, int):
            status_str = _SOURCE_STATUS_NAME.get(raw_status, str(raw_status))
        else:
            status_str = str(raw_status).split(".")[-1].lower()

    return {
        "id": getattr(src, "id", None),
        "title": getattr(src, "title", None),
        "url": getattr(src, "url", None),
        "type": type_str,
        "status": status_str,
    }


_STATUS_NAME = {1: "processing", 2: "pending", 3: "completed", 4: "failed"}


def _serialize_artifact(art: Any) -> dict[str, Any]:
    raw_status = getattr(art, "status", None)
    raw_kind = getattr(art, "kind", None) or getattr(art, "type", None)

    type_str: str | None = None
    if raw_kind is not None:
        if hasattr(raw_kind, "value"):
            type_str = str(raw_kind.value).lower()
        else:
            type_str = str(raw_kind).split(".")[-1].lower()

    status_str: str | None = None
    if raw_status is not None:
        if hasattr(raw_status, "name"):
            status_str = raw_status.name.lower()
        elif isinstance(raw_status, int):
            status_str = _STATUS_NAME.get(raw_status, str(raw_status))
        else:
            status_str = str(raw_status).split(".")[-1].lower()

    return {
        "id": getattr(art, "id", None),
        "title": getattr(art, "title", None),
        "type": type_str,
        "status": status_str,
    }


async def list_notebooks() -> list[dict[str, Any]]:
    client = await _get_client()
    try:
        notebooks = await client.notebooks.list()
    except NotebookLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [_serialize_notebook(nb) for nb in notebooks]


async def create_notebook(title: str) -> dict[str, Any]:
    client = await _get_client()
    try:
        nb = await client.notebooks.create(title)
    except NotebookLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _serialize_notebook(nb)


async def add_youtube_source(notebook_id: str, url: str) -> dict[str, Any]:
    client = await _get_client()
    try:
        src = await client.sources.add_url(notebook_id, url)
    except NotebookLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _serialize_source(src)


async def list_sources(notebook_id: str) -> list[dict[str, Any]]:
    client = await _get_client()
    try:
        sources = await client.sources.list(notebook_id)
    except NotebookLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [_serialize_source(s) for s in sources]


_AUDIO_FORMATS = {f.name.lower(): f for f in AudioFormat}
_AUDIO_LENGTHS = {f.name.lower(): f for f in AudioLength}
_REPORT_FORMATS = {str(f.value): f for f in ReportFormat}
_QUIZ_DIFFICULTIES = {f.name.lower(): f for f in QuizDifficulty}
_QUIZ_QUANTITIES = {f.name.lower(): f for f in QuizQuantity}


async def generate_audio(
    notebook_id: str,
    instructions: str | None = None,
    audio_format: str | None = None,
    audio_length: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    client = await _get_client()
    kwargs: dict[str, Any] = {}
    if instructions:
        kwargs["instructions"] = instructions
    if audio_format and audio_format in _AUDIO_FORMATS:
        kwargs["audio_format"] = _AUDIO_FORMATS[audio_format]
    if audio_length and audio_length in _AUDIO_LENGTHS:
        kwargs["audio_length"] = _AUDIO_LENGTHS[audio_length]
    if language:
        kwargs["language"] = language
    try:
        result = await client.artifacts.generate_audio(notebook_id, **kwargs)
    except NotebookLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "task_id": getattr(result, "task_id", None) or getattr(result, "artifact_id", None),
        "status": str(getattr(result, "status", "")).split(".")[-1].lower() or "pending",
        "artifact_type": "audio",
    }


async def generate_report(
    notebook_id: str,
    report_format: str = "briefing_doc",
    extra_instructions: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    client = await _get_client()
    fmt = _REPORT_FORMATS.get(report_format, ReportFormat.BRIEFING_DOC)
    kwargs: dict[str, Any] = {"report_format": fmt, "extra_instructions": extra_instructions}
    if language:
        kwargs["language"] = language
    try:
        result = await client.artifacts.generate_report(notebook_id, **kwargs)
    except NotebookLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "task_id": getattr(result, "task_id", None) or getattr(result, "artifact_id", None),
        "status": str(getattr(result, "status", "")).split(".")[-1].lower() or "pending",
        "artifact_type": "report",
    }


async def generate_quiz(
    notebook_id: str,
    difficulty: str | None = None,
    quantity: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    client = await _get_client()
    kwargs: dict[str, Any] = {}
    if difficulty and difficulty in _QUIZ_DIFFICULTIES:
        kwargs["difficulty"] = _QUIZ_DIFFICULTIES[difficulty]
    if quantity and quantity in _QUIZ_QUANTITIES:
        kwargs["quantity"] = _QUIZ_QUANTITIES[quantity]
    if language:
        kwargs["language"] = language
    try:
        result = await client.artifacts.generate_quiz(notebook_id, **kwargs)
    except NotebookLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "task_id": getattr(result, "task_id", None) or getattr(result, "artifact_id", None),
        "status": str(getattr(result, "status", "")).split(".")[-1].lower() or "pending",
        "artifact_type": "quiz",
    }


async def generate_mind_map(notebook_id: str) -> dict[str, Any]:
    client = await _get_client()
    try:
        result = await client.artifacts.generate_mind_map(notebook_id)
    except NotebookLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"data": result, "status": "completed", "artifact_type": "mind_map"}


async def generate_slide_deck(
    notebook_id: str,
    instructions: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    client = await _get_client()
    kwargs: dict[str, Any] = {}
    if instructions:
        kwargs["instructions"] = instructions
    if language:
        kwargs["language"] = language
    try:
        result = await client.artifacts.generate_slide_deck(notebook_id, **kwargs)
    except NotebookLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "task_id": getattr(result, "task_id", None) or getattr(result, "artifact_id", None),
        "status": str(getattr(result, "status", "")).split(".")[-1].lower() or "pending",
        "artifact_type": "slide_deck",
    }


_INFOGRAPHIC_ORIENTATIONS = {f.name.lower(): f for f in InfographicOrientation}
_INFOGRAPHIC_DETAILS = {f.name.lower(): f for f in InfographicDetail}
_INFOGRAPHIC_STYLES = {f.name.lower(): f for f in InfographicStyle}


async def generate_infographic(
    notebook_id: str,
    instructions: str | None = None,
    orientation: str | None = None,
    detail: str | None = None,
    style: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    client = await _get_client()
    kwargs: dict[str, Any] = {}
    if instructions:
        kwargs["instructions"] = instructions
    if orientation and orientation in _INFOGRAPHIC_ORIENTATIONS:
        kwargs["orientation"] = _INFOGRAPHIC_ORIENTATIONS[orientation]
    if detail and detail in _INFOGRAPHIC_DETAILS:
        kwargs["detail"] = _INFOGRAPHIC_DETAILS[detail]
    if style and style in _INFOGRAPHIC_STYLES:
        kwargs["style"] = _INFOGRAPHIC_STYLES[style]
    if language:
        kwargs["language"] = language
    try:
        result = await client.artifacts.generate_infographic(notebook_id, **kwargs)
    except NotebookLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "task_id": getattr(result, "task_id", None) or getattr(result, "artifact_id", None),
        "status": str(getattr(result, "status", "")).split(".")[-1].lower() or "pending",
        "artifact_type": "infographic",
    }


async def list_artifacts(notebook_id: str) -> list[dict[str, Any]]:
    client = await _get_client()
    try:
        artifacts = await client.artifacts.list(notebook_id)
    except NotebookLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [_serialize_artifact(a) for a in artifacts]


async def get_artifact(notebook_id: str, artifact_id: str) -> dict[str, Any] | None:
    client = await _get_client()
    try:
        art = await client.artifacts.get(notebook_id, artifact_id)
    except NotebookLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _serialize_artifact(art) if art else None


_DOWNLOAD_EXT = {
    "audio": "mp3",
    "video": "mp4",
    "report": "md",
    "quiz": "json",
    "flashcards": "json",
    "mind_map": "json",
    "data_table": "csv",
    "slide_deck": "pdf",
    "infographic": "png",
}


async def download_artifact(
    notebook_id: str,
    artifact_id: str,
    artifact_type: str,
) -> str:
    client = await _get_client()
    ext = _DOWNLOAD_EXT.get(artifact_type, "bin")
    out_path = str(Path(settings.artifacts_dir) / f"{artifact_id}.{ext}")
    try:
        if artifact_type == "audio":
            await client.artifacts.download_audio(notebook_id, out_path, artifact_id=artifact_id)
        elif artifact_type == "video":
            await client.artifacts.download_video(notebook_id, out_path, artifact_id=artifact_id)
        elif artifact_type == "report":
            await client.artifacts.download_report(notebook_id, out_path, artifact_id=artifact_id)
        elif artifact_type == "quiz":
            await client.artifacts.download_quiz(notebook_id, out_path, artifact_id=artifact_id)
        elif artifact_type == "flashcards":
            await client.artifacts.download_flashcards(notebook_id, out_path, artifact_id=artifact_id)
        elif artifact_type == "mind_map":
            await client.artifacts.download_mind_map(notebook_id, out_path, artifact_id=artifact_id)
        elif artifact_type == "data_table":
            await client.artifacts.download_data_table(notebook_id, out_path, artifact_id=artifact_id)
        elif artifact_type == "slide_deck":
            await client.artifacts.download_slide_deck(notebook_id, out_path, artifact_id=artifact_id)
        elif artifact_type == "infographic":
            await client.artifacts.download_infographic(notebook_id, out_path, artifact_id=artifact_id)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported artifact type: {artifact_type}")
    except NotebookLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return out_path
