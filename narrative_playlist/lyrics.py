"""가사 수집 — 유튜브 뮤직 우선, 없으면 LRCLIB(무료·키 없음)으로 보완. 결과는 캐시."""

from __future__ import annotations

import time

import requests

from . import config
from .cache import JsonCache
from .models import Track
from .ytmusic import fetch_yt_lyrics

LRCLIB = "https://lrclib.net/api"


def fetch_lrclib(track: Track) -> str | None:
    headers = {"User-Agent": config.USER_AGENT}
    artist = track.artists[0] if track.artists else ""
    params = {"track_name": track.title, "artist_name": artist}
    if track.album:
        params["album_name"] = track.album
    if track.duration_seconds:
        params["duration"] = track.duration_seconds
    try:
        r = requests.get(f"{LRCLIB}/get", params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            d = r.json()
            if d.get("plainLyrics"):
                return d["plainLyrics"]
        # 정확 매칭 실패 → 검색
        r = requests.get(
            f"{LRCLIB}/search",
            params={"track_name": track.title, "artist_name": artist},
            headers=headers,
            timeout=10,
        )
        if r.status_code == 200:
            for cand in r.json():
                if cand.get("plainLyrics") and not cand.get("instrumental"):
                    return cand["plainLyrics"]
    except requests.RequestException:
        return None
    return None


def collect_lyrics(yt, tracks: list[Track], log=print) -> dict[str, str | None]:
    cache = JsonCache("lyrics")
    out: dict[str, str | None] = {}
    for i, t in enumerate(tracks, 1):
        hit = cache.get(t.video_id)
        if hit is not None:
            out[t.video_id] = hit.get("text")
            continue
        text, source = None, None
        if yt is not None:
            text = fetch_yt_lyrics(yt, t.video_id)
            source = "ytmusic" if text else None
        if not text:
            text = fetch_lrclib(t)
            source = "lrclib" if text else None
            time.sleep(0.3)  # LRCLIB 예의상 간격
        cache.set(t.video_id, {"text": text, "source": source})
        out[t.video_id] = text
        log(f"  [{i}/{len(tracks)}] {t.title} — {source or '가사 없음'}")
    return out
