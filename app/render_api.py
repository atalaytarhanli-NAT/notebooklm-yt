"""Thin wrapper around the Render API for self-updating env vars."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.render.com/v1"


def _headers() -> dict[str, str]:
    if not settings.render_api_key:
        raise RuntimeError("RENDER_API_KEY env var is not configured")
    return {
        "Authorization": f"Bearer {settings.render_api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _service_id() -> str:
    if not settings.render_service_id:
        raise RuntimeError("RENDER_SERVICE_ID env var is not configured")
    return settings.render_service_id


async def list_env_vars() -> list[dict[str, str]]:
    """Return all env vars on the configured service."""
    sid = _service_id()
    items: list[dict[str, str]] = []
    cursor: str | None = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params: dict[str, Any] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            r = await client.get(f"{_BASE_URL}/services/{sid}/env-vars", headers=_headers(), params=params)
            r.raise_for_status()
            data = r.json()
            for entry in data:
                ev = entry.get("envVar", entry)
                if "key" in ev:
                    items.append({"key": ev["key"], "value": ev.get("value", "")})
            cursor = data[-1].get("cursor") if data and isinstance(data[-1], dict) else None
            if not cursor or len(data) < 100:
                break
    return items


async def replace_env_var(key: str, value: str) -> dict[str, Any]:
    """Replace one env var's value, keeping all other env vars unchanged.

    Returns the Render API response. The change automatically triggers a redeploy.
    """
    sid = _service_id()
    current = await list_env_vars()
    next_vars: list[dict[str, str]] = []
    found = False
    for ev in current:
        if ev["key"] == key:
            next_vars.append({"key": key, "value": value})
            found = True
        else:
            next_vars.append({"key": ev["key"], "value": ev["value"]})
    if not found:
        next_vars.append({"key": key, "value": value})
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.put(
            f"{_BASE_URL}/services/{sid}/env-vars",
            headers=_headers(),
            json=next_vars,
        )
        r.raise_for_status()
        return {"status": "updated", "env_vars_count": len(next_vars), "key": key, "found_existing": found}
