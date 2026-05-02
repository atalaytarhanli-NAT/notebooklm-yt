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


# In-memory cache: video_id -> upload_date (YYYYMMDD or None for "tried, failed")
_DATE_CACHE: dict[str, str | None] = {}
_PER_VIDEO_TIMEOUT = 3.0  # seconds, hard cap per video extraction
_TOTAL_BUDGET = 6.0  # seconds, max time spent on enrichment per search


def _enrich_with_upload_date(entry: dict[str, Any], cookies_file: str | None) -> dict[str, Any]:
    vid = entry.get("id")
    if not vid:
        return entry
    if entry.get("upload_date"):
        _DATE_CACHE[vid] = entry["upload_date"]
        return entry
    if vid in _DATE_CACHE:
        cached = _DATE_CACHE[vid]
        if cached:
            entry["upload_date"] = cached
        return entry

    opts: dict[str, Any] = dict(_BASE_OPTS)
    opts["ignoreerrors"] = True
    opts["socket_timeout"] = _PER_VIDEO_TIMEOUT
    if cookies_file:
        opts["cookiefile"] = cookies_file
    url = f"https://www.youtube.com/watch?v={vid}"
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False, process=False)
    except Exception as exc:
        logger.debug("enrich fail %s: %s", vid, exc)
        _DATE_CACHE[vid] = None
        return entry
    if info:
        if info.get("upload_date"):
            entry["upload_date"] = info["upload_date"]
            _DATE_CACHE[vid] = info["upload_date"]
        elif info.get("timestamp"):
            try:
                from datetime import datetime, timezone
                dt = datetime.fromtimestamp(info["timestamp"], tz=timezone.utc).strftime("%Y%m%d")
                entry["upload_date"] = dt
                _DATE_CACHE[vid] = dt
            except (TypeError, ValueError, OSError):
                _DATE_CACHE[vid] = None
        else:
            _DATE_CACHE[vid] = None
    return entry


def _search_sync(query: str, count: int, with_dates: bool = True) -> list[dict[str, Any]]:
    count = max(1, min(int(count), 50))
    cookies_file = _write_youtube_cookies()

    opts_flat: dict[str, Any] = dict(_BASE_OPTS)
    opts_flat["extract_flat"] = "in_playlist"
    opts_flat["socket_timeout"] = 8.0
    if cookies_file:
        opts_flat["cookiefile"] = cookies_file

    with YoutubeDL(opts_flat) as ydl:
        info = ydl.extract_info(f"ytsearch{count}:{query}", download=False)

    entries = list((info or {}).get("entries") or [])
    entries = [e for e in entries if e]

    # Enrich with upload_date — bounded by total budget; on timeout, return partials.
    if with_dates and entries:
        import time as _time
        from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
        start = _time.monotonic()
        # Pre-fill from cache (fast path, no thread needed)
        to_fetch: list[dict[str, Any]] = []
        for e in entries:
            vid = e.get("id")
            if vid and vid in _DATE_CACHE:
                cached = _DATE_CACHE[vid]
                if cached:
                    e["upload_date"] = cached
            else:
                to_fetch.append(e)
        if to_fetch:
            pool = ThreadPoolExecutor(max_workers=min(4, len(to_fetch)))
            try:
                futures = {pool.submit(_enrich_with_upload_date, e, cookies_file): e for e in to_fetch}
                deadline = start + _TOTAL_BUDGET
                while futures:
                    remaining = deadline - _time.monotonic()
                    if remaining <= 0:
                        logger.info("enrichment budget exceeded, %d/%d videos enriched",
                                    len(to_fetch) - len(futures), len(to_fetch))
                        break
                    done, _pending = wait(futures.keys(), timeout=remaining, return_when=FIRST_COMPLETED)
                    if not done:
                        break  # timeout
                    for fut in done:
                        del futures[fut]
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
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


async def search_youtube(query: str, count: int = 5, with_dates: bool = True) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_search_sync, query, count, with_dates)
