"""Web search via Firecrawl."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException, status

from .config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.firecrawl.dev/v2"


async def search_web(query: str, limit: int = 10) -> list[dict[str, Any]]:
    if not settings.firecrawl_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FIRECRAWL_API_KEY env var is not configured",
        )
    limit = max(1, min(int(limit), 30))
    body = {"query": query, "limit": limit}
    headers = {
        "Authorization": f"Bearer {settings.firecrawl_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(f"{_BASE_URL}/search", headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Firecrawl request failed: {exc}") from exc
    if r.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Firecrawl error {r.status_code}: {r.text[:300]}",
        )
    data = r.json()
    web = (data.get("data") or {}).get("web") or []
    out: list[dict[str, Any]] = []
    for item in web:
        out.append({
            "url": item.get("url"),
            "title": item.get("title"),
            "description": item.get("description"),
            "site": _domain(item.get("url")),
        })
    return out


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        return host.removeprefix("www.")
    except Exception:
        return None
