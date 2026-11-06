"""유튜브 뮤직 입출력 — 곡 목록 읽기, 가사 가져오기, 플레이리스트 생성.

ytmusicapi(비공식)를 쓴다. 인증은 브라우저 헤더(browser.json) 방식.
"""

from __future__ import annotations

from pathlib import Path

from . import config
from .models import Track


def connect(auth_file: Path | None = None):
    from ytmusicapi import YTMusic

    auth_file = Path(auth_file or config.YTM_AUTH_FILE)
    if not auth_file.exists():
        raise FileNotFoundError(
            f"인증 파일이 없습니다: {auth_file}\n"
            "먼저 `python -m narrative_playlist auth` 로 browser.json 을 만드세요."
        )
    return YTMusic(str(auth_file))


def _to_track(raw: dict) -> Track | None:
    vid = raw.get("videoId")
    if not vid:
        return None
    artists = [a.get("name") for a in (raw.get("artists") or []) if a.get("name")]
    album = (raw.get("album") or {}).get("name") if isinstance(raw.get("album"), dict) else None
    return Track(
        video_id=vid,
        title=raw.get("title") or "",
        artists=artists,
        album=album,
        duration_seconds=raw.get("duration_seconds"),
    )


def fetch_tracks(
    yt,
    source: str = "liked",
    playlist_id: str | None = None,
    limit: int | None = 500,
    artist_filter: str | list[str] | None = None,
) -> list[Track]:
    """source: liked | library | playlist. artist_filter 에 여러 명을 주면 그중 누구라도 참여한 곡."""
    if isinstance(artist_filter, str):
        artist_filter = [artist_filter]
    wanted = [w.lower() for w in (artist_filter or []) if w]
    if source == "liked":
        raw = yt.get_liked_songs(limit=limit or 5000).get("tracks", [])
    elif source == "library":
        raw = yt.get_library_songs(limit=limit or 5000)
    elif source == "playlist":
        if not playlist_id:
            raise ValueError("--playlist-id 가 필요합니다.")
        raw = yt.get_playlist(playlist_id, limit=limit).get("tracks", [])
    else:
        raise ValueError(f"알 수 없는 source: {source}")

    # ytmusicapi 는 limit 를 '최소 이만큼'으로 취급해서 페이지 단위로 더 가져온다. 정확히 자른다.
    if limit:
        raw = raw[:limit]

    tracks: list[Track] = []
    seen: set[str] = set()
    for r in raw:
        t = _to_track(r)
        if not t or t.video_id in seen:
            continue
        if wanted and not any(w in a.lower() for w in wanted for a in t.artists):
            continue
        seen.add(t.video_id)
        tracks.append(t)
    return tracks


def fetch_yt_lyrics(yt, video_id: str) -> str | None:
    """유튜브 뮤직이 제공하는 가사. 없으면 None."""
    try:
        watch = yt.get_watch_playlist(videoId=video_id, limit=1)
        browse_id = watch.get("lyrics")
        if not browse_id:
            return None
        lyr = yt.get_lyrics(browse_id)
        if not lyr:
            return None
        body = lyr.get("lyrics")
        if isinstance(body, list):  # 타임스탬프 가사
            body = "\n".join(getattr(line, "text", str(line)) for line in body)
        return body or None
    except Exception:
        return None


def publish_playlist(yt, title: str, description: str, video_ids: list[str], privacy: str = "PRIVATE") -> str:
    """새 플레이리스트를 만들고 ID를 돌려준다. 기본은 비공개."""
    result = yt.create_playlist(title, description[:5000], privacy_status=privacy, video_ids=video_ids)
    if isinstance(result, dict):  # 실패 시 응답 dict가 온다
        raise RuntimeError(f"플레이리스트 생성 실패: {result}")
    return result
