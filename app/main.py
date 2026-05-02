from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import nlm, render_api
from .auth import require_token
from .config import settings
from .youtube import refresh_cookies as _yt_refresh_cookies, search_youtube

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="notebooklm-yt", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/auth/check", dependencies=[Depends(require_token)])
async def auth_check() -> dict[str, object]:
    try:
        notebooks = await nlm.list_notebooks()
        return {"ok": True, "notebook_count": len(notebooks)}
    except HTTPException as exc:
        return {"ok": False, "error": exc.detail, "status_code": exc.status_code}


@app.get("/api/youtube/search", dependencies=[Depends(require_token)])
async def youtube_search(q: str = Query(..., min_length=1), n: int = Query(10, ge=1, le=50)) -> dict[str, object]:
    results = await search_youtube(q, n)
    return {"query": q, "count": len(results), "results": results}


@app.get("/api/notebooks", dependencies=[Depends(require_token)])
async def notebooks_list() -> dict[str, object]:
    return {"notebooks": await nlm.list_notebooks()}


class CreateNotebookBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


@app.post("/api/notebooks", dependencies=[Depends(require_token)])
async def notebooks_create(body: CreateNotebookBody) -> dict[str, object]:
    return {"notebook": await nlm.create_notebook(body.title)}


class AddSourcesBody(BaseModel):
    notebook_id: str
    urls: list[str] = Field(..., min_length=1, max_length=50)


@app.post("/api/sources/add", dependencies=[Depends(require_token)])
async def sources_add(body: AddSourcesBody) -> dict[str, object]:
    added: list[dict] = []
    errors: list[dict] = []
    for url in body.urls:
        try:
            src = await nlm.add_youtube_source(body.notebook_id, url)
            added.append(src)
        except HTTPException as exc:
            errors.append({"url": url, "error": exc.detail})
    return {"added": added, "errors": errors}


@app.get("/api/notebooks/{notebook_id}/sources", dependencies=[Depends(require_token)])
async def sources_list(notebook_id: str) -> dict[str, object]:
    return {"sources": await nlm.list_sources(notebook_id)}


class GenerateAudioBody(BaseModel):
    notebook_id: str
    instructions: str | None = None
    audio_format: str | None = None  # deep_dive | brief | critique | debate
    audio_length: str | None = None  # short | default | long


@app.post("/api/generate/audio", dependencies=[Depends(require_token)])
async def generate_audio(body: GenerateAudioBody) -> dict[str, object]:
    return await nlm.generate_audio(
        body.notebook_id,
        instructions=body.instructions,
        audio_format=body.audio_format,
        audio_length=body.audio_length,
    )


class GenerateReportBody(BaseModel):
    notebook_id: str
    report_format: str = "briefing_doc"  # briefing_doc | study_guide | blog_post | custom
    extra_instructions: str | None = None


@app.post("/api/generate/report", dependencies=[Depends(require_token)])
async def generate_report(body: GenerateReportBody) -> dict[str, object]:
    return await nlm.generate_report(
        body.notebook_id,
        report_format=body.report_format,
        extra_instructions=body.extra_instructions,
    )


class GenerateQuizBody(BaseModel):
    notebook_id: str
    difficulty: str | None = None  # easy | medium | hard
    quantity: str | None = None  # fewer | standard


@app.post("/api/generate/quiz", dependencies=[Depends(require_token)])
async def generate_quiz(body: GenerateQuizBody) -> dict[str, object]:
    return await nlm.generate_quiz(
        body.notebook_id,
        difficulty=body.difficulty,
        quantity=body.quantity,
    )


class GenerateMindMapBody(BaseModel):
    notebook_id: str


@app.post("/api/generate/mind-map", dependencies=[Depends(require_token)])
async def generate_mind_map(body: GenerateMindMapBody) -> dict[str, object]:
    return await nlm.generate_mind_map(body.notebook_id)


class GenerateSlideDeckBody(BaseModel):
    notebook_id: str
    instructions: str | None = None


@app.post("/api/generate/slide-deck", dependencies=[Depends(require_token)])
async def generate_slide_deck(body: GenerateSlideDeckBody) -> dict[str, object]:
    return await nlm.generate_slide_deck(body.notebook_id, instructions=body.instructions)


@app.get("/api/notebooks/{notebook_id}/artifacts", dependencies=[Depends(require_token)])
async def artifacts_list(notebook_id: str) -> dict[str, object]:
    return {"artifacts": await nlm.list_artifacts(notebook_id)}


@app.get(
    "/api/notebooks/{notebook_id}/artifacts/{artifact_id}",
    dependencies=[Depends(require_token)],
)
async def artifact_get(notebook_id: str, artifact_id: str) -> dict[str, object]:
    art = await nlm.get_artifact(notebook_id, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"artifact": art}


_INLINE_MEDIA_TYPES = {
    "audio": "audio/mpeg",
    "video": "video/mp4",
    "report": "text/markdown; charset=utf-8",
    "quiz": "application/json",
    "flashcards": "application/json",
    "mind_map": "application/json",
    "data_table": "text/csv; charset=utf-8",
    "slide_deck": "application/pdf",
    "infographic": "image/png",
}


@app.get(
    "/api/notebooks/{notebook_id}/artifacts/{artifact_id}/download",
    dependencies=[Depends(require_token)],
)
async def artifact_download(
    notebook_id: str,
    artifact_id: str,
    type: str = Query(..., description="audio|video|report|quiz|flashcards|mind_map|data_table|slide_deck|infographic"),
    inline: bool = Query(False, description="If true, serve inline (for in-browser preview) with no download header"),
) -> FileResponse:
    path = await nlm.download_artifact(notebook_id, artifact_id, type)
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="Downloaded file missing")
    media_type = _INLINE_MEDIA_TYPES.get(type)
    if inline:
        return FileResponse(path, media_type=media_type, headers={"Content-Disposition": "inline"})
    return FileResponse(path, filename=Path(path).name, media_type=media_type)


@app.get(
    "/api/notebooks/{notebook_id}/artifacts/{artifact_id}/preview",
    dependencies=[Depends(require_token)],
)
async def artifact_preview(notebook_id: str, artifact_id: str, type: str = Query(...)) -> dict[str, object]:
    """Return artifact content as JSON-friendly text for in-browser rendering.

    For text-based types (report=markdown, quiz/mind_map/flashcards=json,
    data_table=csv) returns the raw text. For binary types returns a URL the
    browser can load with credentials (audio/video/pdf/png served via the
    normal download endpoint with inline=true).
    """
    if type in {"report", "quiz", "mind_map", "flashcards", "data_table"}:
        path = await nlm.download_artifact(notebook_id, artifact_id, type)
        if not Path(path).exists():
            raise HTTPException(status_code=404, detail="File missing")
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        return {"kind": "text", "type": type, "content": text}
    if type in {"audio", "video", "slide_deck", "infographic"}:
        return {"kind": "media", "type": type}
    raise HTTPException(status_code=400, detail=f"Preview not supported for type: {type}")


class RefreshAuthBody(BaseModel):
    storage_state: str = Field(..., min_length=10)


@app.post("/api/admin/refresh-auth", dependencies=[Depends(require_token)])
async def admin_refresh_auth(body: RefreshAuthBody) -> dict[str, object]:
    import json as _json

    payload = body.storage_state.strip()
    try:
        parsed = _json.loads(payload)
    except _json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict) or "cookies" not in parsed:
        raise HTTPException(status_code=400, detail="storage_state must contain 'cookies'")
    sid_present = any(c.get("name") == "SID" for c in parsed.get("cookies", []))
    if not sid_present:
        raise HTTPException(status_code=400, detail="storage_state missing SID cookie — login may not have completed")

    if not settings.render_api_key or not settings.render_service_id:
        raise HTTPException(
            status_code=503,
            detail="RENDER_API_KEY and RENDER_SERVICE_ID env vars must be configured for auto-refresh",
        )

    try:
        result = await render_api.replace_env_var("NOTEBOOKLM_AUTH_JSON", payload)
    except Exception as exc:
        logger.exception("Render API update failed")
        raise HTTPException(status_code=502, detail=f"Render API error: {exc}") from exc

    # Hot-reload: update os.environ so the new value is visible without restart
    os.environ["NOTEBOOKLM_AUTH_JSON"] = payload
    settings.notebooklm_auth_json = payload
    await nlm.reset_client()
    _yt_refresh_cookies()

    return {
        "ok": True,
        "message": "NOTEBOOKLM_AUTH_JSON updated. Render will redeploy; in-process state already refreshed.",
        "render": result,
        "cookie_count": len(parsed.get("cookies", [])),
    }


# Static frontend
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
