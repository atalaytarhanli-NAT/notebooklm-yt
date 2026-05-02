from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL

logger = logging.getLogger(__name__)


_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
}

_YT_COOKIES_PATH = "/tmp/yt-cookies.txt"


def _write_youtube_cookies() -> str | None:
    """Convert YouTube cookies from NotebookLM storage_state.json to Netscape format.

    Allows yt-dlp to do full per-video extraction (returns upload_date) without
    triggering YouTube's bot challenge.
    """
    auth_json = os.environ.get("NOTEBOOKLM_AUTH_JSON", "").strip()
    if not auth_json:
        nb_home = os.environ.get("NOTEBOOKLM_HOME") or os.path.expanduser("~/.notebooklm")
        sp = Path(nb_home) / "storage_state.json"
        if sp.exists():
            try:
                auth_json = sp.read_text(encoding="utf-8")
            except OSError:
                return None
    if not auth_json:
        return None
    try:
        data = json.loads(auth_json)
    except json.JSONDecodeError:
        return None

    yt_cookies = [
        c for c in data.get("cookies", [])
        if "youtube.com" in (c.get("domain") or "")
    ]
    if not yt_cookies:
        return None

    lines = ["# Netscape HTTP Cookie File"]
    for c in yt_cookies:
        domain = c["domain"]
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path") or "/"
        secure = "TRUE" if c.get("secure") else "FALSE"
        expires = int(c.get("expires") or 0)
        name = c.get("name") or ""
        value = c.get("value") or ""
        lines.append("\t".join([domain, include_subdomains, path, secure, str(expires), name, value]))

    try:
        Path(_YT_COOKIES_PATH).write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write cookies file: %s", exc)
        return None
    return _YT_COOKIES_PATH


def refresh_cookies() -> str | None:
    """Re-write yt-dlp cookies file. Call after NOTEBOOKLM_AUTH_JSON changes."""
    return _write_youtube_cookies()


def _format_upload_date(d: str | None) -> str | None:
    if not d or len(d) != 8:
        return None
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"


def _format_duration(seconds: int | None) -> str | None:
    if not seconds:
        return None
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _enrich_with_upload_date(entry: dict[str, Any], cookies_file: str | None) -> dict[str, Any]:
    """Per-video extraction (process=False) to fetch upload_date.

    Falls through silently on any error — the entry is still usable without dates.
    """
    if entry.get("upload_date") or not entry.get("id"):
        return entry
    opts: dict[str, Any] = dict(_BASE_OPTS)
    opts["ignoreerrors"] = True
    if cookies_file:
        opts["cookiefile"] = cookies_file
    url = f"https://www.youtube.com/watch?v={entry['id']}"
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False, process=False)
    except Exception as exc:
        logger.debug("upload_date enrichment failed for %s: %s", entry.get("id"), exc)
        return entry
    if info:
        for key in ("upload_date", "timestamp", "release_timestamp"):
            if info.get(key) and not entry.get(key):
                entry[key] = info[key]
    return entry


def _search_sync(query: str, count: int) -> list[dict[str, Any]]:
    count = max(1, min(int(count), 50))
    cookies_file = _write_youtube_cookies()

    opts_flat: dict[str, Any] = dict(_BASE_OPTS)
    opts_flat["extract_flat"] = "in_playlist"
    if cookies_file:
        opts_flat["cookiefile"] = cookies_file

    with YoutubeDL(opts_flat) as ydl:
        info = ydl.extract_info(f"ytsearch{count}:{query}", download=False)

    entries = list((info or {}).get("entries") or [])
    entries = [e for e in entries if e]

    # Enrich with upload_date in parallel (best-effort, skip on failure)
    if entries:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(8, len(entries))) as pool:
            entries = list(pool.map(lambda e: _enrich_with_upload_date(e, cookies_file), entries))
    out: list[dict[str, Any]] = []
    for e in entries:
        if not e:
            continue
        thumbs = e.get("thumbnails") or []
        thumb_url = e.get("thumbnail") or (thumbs[0]["url"] if thumbs and isinstance(thumbs, list) and thumbs[0].get("url") else None)
        if not thumb_url and e.get("id"):
            thumb_url = f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg"
        upload_date = _format_upload_date(e.get("upload_date"))
        if not upload_date and e.get("timestamp"):
            try:
                from datetime import datetime, timezone
                upload_date = datetime.fromtimestamp(e["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                upload_date = None
        out.append({
            "id": e.get("id"),
            "title": e.get("title"),
            "url": e.get("webpage_url") or e.get("url") or (f"https://www.youtube.com/watch?v={e.get('id')}" if e.get("id") else None),
            "channel": e.get("channel") or e.get("uploader"),
            "view_count": e.get("view_count"),
            "duration": e.get("duration"),
            "duration_string": _format_duration(e.get("duration")),
            "upload_date": upload_date,
            "thumbnail": thumb_url,
        })
    return out


async def search_youtube(query: str, count: int = 5) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_search_sync, query, count)
