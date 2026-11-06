"""배치가 끝난 순서를 보고 플레이리스트 제목, 챕터 제목, 곡별 한 줄 해설을 쓴다."""

from __future__ import annotations

from itertools import groupby

from . import config
from .canon import CanonInfo
from .llm import structured_call
from .models import Chapter, NarrativePlaylist, PlacedSong

SYSTEM = """너는 플레이리스트를 한 편의 단편소설처럼 엮는 큐레이터다.
순서가 정해진 곡 목록을 받으면 각 챕터에 짧고 시적인 제목을 붙이고,
각 곡이 왜 그 자리에 있는지 한 줄로 쓴다.
- 가사를 인용하지 말고 너의 말로 쓴다.
- 챕터 제목은 2~8글자, 장면이 떠오르게. 단계 이름(만남, 갈등 등)을 그대로 쓰지 않는다.
- 곡 해설은 앞뒤 곡과의 연결이 느껴지게, 25자 안팎.
- 작가 의도 표시(📌)가 있는 곡은 그 의도를 해설에 자연스럽게 반영한다."""


def _schema(n_chapters: int, n_songs: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "플레이리스트 제목"},
            "description": {
                "type": "string",
                "description": "앨범 소개글처럼 쓴 플레이리스트 설명 3~4문장. 처음부터 끝까지 어떤 이야기가 흐르는지 "
                "줄거리로 보여준다. 곡 제목 나열이나 '이 플레이리스트는' 같은 말은 쓰지 않는다.",
            },
            "chapters": {
                "type": "array",
                "minItems": n_chapters,
                "maxItems": n_chapters,
                "items": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "blurb": {"type": "string", "description": "챕터 한 문장 소개"}},
                    "required": ["title", "blurb"],
                },
            },
            "song_notes": {"type": "array", "minItems": n_songs, "maxItems": n_songs, "items": {"type": "string"}},
        },
        "required": ["title", "description", "chapters", "song_notes"],
    }


def _group(placed: list[PlacedSong]) -> list[tuple[str, list[PlacedSong]]]:
    return [(k, list(g)) for k, g in groupby(placed, key=lambda p: p.stage)]


def compose(
    placed: list[PlacedSong],
    arc_name: str,
    canon_infos: dict[str, CanonInfo] | None = None,
    use_llm: bool = True,
    log=print,
) -> NarrativePlaylist:
    canon_infos = canon_infos or {}
    groups = _group(placed)

    if use_llm:
        lines = []
        for ch_i, (stage, songs) in enumerate(groups, 1):
            lines.append(f"\n## 챕터 {ch_i} ({stage})")
            for p in songs:
                pin = "📌 " if canon_infos.get(p.track.video_id, CanonInfo()).is_pinned else ""
                lines.append(f"{p.position}. {pin}{p.track.title} — {p.track.artist_str} | {p.analysis.summary}")
        try:
            d = structured_call(
                model=config.TITLING_MODEL,
                system=SYSTEM,
                user="곡 순서:\n" + "\n".join(lines),
                tool_name="write_playlist_story",
                tool_desc="플레이리스트의 제목, 챕터, 곡별 해설을 기록한다.",
                schema=_schema(len(groups), len(placed)),
                max_tokens=3000,
            )
            for p, note in zip(placed, d["song_notes"]):
                p.note = note
            chapters = [
                Chapter(stage=stage, title=c["title"], blurb=c["blurb"], songs=songs)
                for (stage, songs), c in zip(groups, d["chapters"])
            ]
            return NarrativePlaylist(d["title"], d["description"], arc_name, chapters)
        except Exception as e:
            log(f"제목 생성 실패, 기본 제목을 씁니다: {e}")

    chapters = [Chapter(stage=s, title=s, blurb="", songs=songs) for s, songs in groups]
    for p in placed:
        p.note = p.analysis.summary
    return NarrativePlaylist("나의 서사 플레이리스트", f"{len(placed)}곡으로 엮은 한 편의 이야기.", arc_name, chapters)
