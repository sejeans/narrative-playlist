"""전체 흐름: 곡 수집 → 작가 의도 매칭 → 가사 → LLM 분석 → 곡선 배치 → 작명 → 저장/게시."""

from __future__ import annotations

import json
from pathlib import Path

from . import config
from .analyze import analyze_all
from .arc import arrange
from .canon import Canon
from .lyrics import collect_lyrics
from .models import SongAnalysis, Track
from .report import print_summary, save
from .titling import compose

FIXTURES = config.PROJECT_ROOT / "fixtures"


def _count_by_artist(tracks: list[Track], top: int = 6) -> str:
    from collections import Counter

    c = Counter(t.artists[0] if t.artists else "?" for t in tracks)
    return ", ".join(f"{a} {n}" for a, n in c.most_common(top)) + (" ..." if len(c) > top else "")


def build(
    *,
    source: str = "liked",
    playlist_id: str | None = None,
    artist: str | list[str] | None = None,
    limit: int | None = 500,
    length: int = 15,
    arc: str = "love",
    publish: bool = False,
    llm_titles: bool = True,
    canon_paths: list[Path] | None = None,
    log=print,
):
    from . import ytmusic

    yt = ytmusic.connect()
    canon = Canon.load(canon_paths)
    log("곡 목록 가져오는 중...")
    tracks = ytmusic.fetch_tracks(
        yt, source=source, playlist_id=playlist_id, limit=limit, artist_filter=canon.expand_artists(artist)
    )
    log(f"→ {len(tracks)}곡 ({_count_by_artist(tracks)})")
    if not tracks:
        raise SystemExit("곡이 없습니다. --source / --artist 를 확인하세요.")

    infos = {t.video_id: canon.lookup(t) for t in tracks}
    pinned = [t.title for t in tracks if infos[t.video_id].is_pinned]
    if pinned:
        log(f"📌 작가 의도 고정 곡: {', '.join(pinned)}")

    log("가사 수집 중...")
    lyrics = collect_lyrics(yt, tracks, log=log)
    analyses = analyze_all(tracks, lyrics, infos, log=log)

    placed = arrange(tracks, analyses, infos, arc_name=arc, length=length)
    pl = compose(placed, arc, infos, use_llm=llm_titles, log=log)
    print_summary(pl, infos)
    md, js = save(pl, infos)
    log(f"저장: {md.with_suffix('.txt')}")

    if publish:
        pid = ytmusic.publish_playlist(yt, pl.title, pl.description, [p.track.video_id for p in pl.ordered_songs])
        log(f"유튜브 뮤직에 비공개 플레이리스트를 만들었습니다: https://music.youtube.com/playlist?list={pid}")
    return pl, md


def demo(arc: str = "love", length: int = 12, llm_titles: bool = False, log=print):
    """네트워크·API 키 없이 배치 알고리즘만 돌려보는 모드. 가상의 밴드 데이터를 쓴다."""
    data = json.loads((FIXTURES / "demo_songs.json").read_text(encoding="utf-8"))
    tracks = [Track.from_dict(d["track"]) for d in data]
    analyses = {d["track"]["video_id"]: SongAnalysis.from_dict(d["analysis"]) for d in data}
    canon = Canon.load([FIXTURES / "demo_canon.yaml"])
    infos = {t.video_id: canon.lookup(t) for t in tracks}

    placed = arrange(tracks, analyses, infos, arc_name=arc, length=length)
    pl = compose(placed, arc, infos, use_llm=llm_titles, log=log)
    print_summary(pl, infos)
    md, _ = save(pl, infos)
    log(f"저장: {md.with_suffix('.txt')}")
    return pl, md


def check_canon(*, source="liked", playlist_id=None, artist=None, limit=500, log=print):
    """좋아요 곡 중 작가 의도 파일과 매칭되는 곡을 보여준다. 제목 표기가 달라 안 잡히는 곡을 찾을 때."""
    from . import ytmusic

    yt = ytmusic.connect()
    canon = Canon.load()
    tracks = ytmusic.fetch_tracks(
        yt, source=source, playlist_id=playlist_id, limit=limit, artist_filter=canon.expand_artists(artist)
    )
    for t in tracks:
        info = canon.lookup(t)
        if not (info.is_pinned or info.album_key):
            continue
        tags = []
        if info.is_pinned:
            tags.append(f"📌 {info.pin_stage}{'/' + info.pin_where if info.pin_where else ''}")
        if info.album_key:
            tags.append(f"앨범={info.album_key}" + (f" #{info.album_index + 1}" if info.album_index is not None else ""))
        log(f"  {t.title} [{t.album}] → {' · '.join(tags)}")
