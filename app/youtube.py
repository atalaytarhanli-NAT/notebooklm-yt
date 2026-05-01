from __future__ import annotations

import asyncio
from typing import Any

from yt_dlp import YoutubeDL


_YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": "in_playlist",
    "noplaylist": True,
}


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


def _search_sync(query: str, count: int) -> list[dict[str, Any]]:
    count = max(1, min(int(count), 50))
    with YoutubeDL(_YDL_OPTS) as ydl:
        info = ydl.extract_info(f"ytsearch{count}:{query}", download=False)
    entries = (info or {}).get("entries") or []
    out: list[dict[str, Any]] = []
    for e in entries:
        if not e:
            continue
        thumbs = e.get("thumbnails") or []
        thumb_url = e.get("thumbnail") or (thumbs[0]["url"] if thumbs and isinstance(thumbs, list) and thumbs[0].get("url") else None)
        if not thumb_url and e.get("id"):
            thumb_url = f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg"
        out.append({
            "id": e.get("id"),
            "title": e.get("title"),
            "url": e.get("url") or e.get("webpage_url") or (f"https://www.youtube.com/watch?v={e.get('id')}" if e.get("id") else None),
            "channel": e.get("channel") or e.get("uploader"),
            "view_count": e.get("view_count"),
            "duration": e.get("duration"),
            "duration_string": _format_duration(e.get("duration")),
            "upload_date": _format_upload_date(e.get("upload_date")),
            "thumbnail": thumb_url,
        })
    return out


async def search_youtube(query: str, count: int = 5) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_search_sync, query, count)
