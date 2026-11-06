"""결과를 마크다운·JSON으로 저장하고 터미널에 보여준다. 가사는 어디에도 출력하지 않는다."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import config
from .canon import CanonInfo
from .models import NarrativePlaylist


def _bar(v: float, width: int = 10) -> str:
    """valence -1~1 을 ▁▂▃▄▅▆▇█ 로."""
    blocks = "▁▂▃▄▅▆▇█"
    return blocks[min(7, max(0, int((v + 1) / 2 * 7.999)))]


def to_markdown(pl: NarrativePlaylist, canon_infos: dict[str, CanonInfo] | None = None) -> str:
    canon_infos = canon_infos or {}
    curve = "".join(_bar(p.analysis.valence) for p in pl.ordered_songs)
    out = [f"# {pl.title}", "", pl.description, "", f"감정 곡선: `{curve}`  (낮을수록 어두움)", ""]
    for i, ch in enumerate(pl.chapters, 1):
        out.append(f"## {i}. {ch.title}  <sub>{ch.stage}</sub>")
        if ch.blurb:
            out.append(f"_{ch.blurb}_")
        out.append("")
        for p in ch.songs:
            info = canon_infos.get(p.track.video_id, CanonInfo())
            mark = " 📌" if info.is_pinned else (" 💿" if info.album_order_matters else "")
            lyr = "" if p.analysis.has_lyrics else " ·가사없음"
            out.append(f"{p.position}. **{p.track.title}** — {p.track.artist_str}{mark}  ")
            out.append(f"   {p.note}  <sub>v{p.analysis.valence:+.1f} e{p.analysis.arousal:.1f}{lyr}</sub>")
        out.append("")
    out.append("<sub>📌 작가 의도로 고정된 곡 · 💿 앨범 순서를 따르는 곡</sub>")
    return "\n".join(out)


PASTE_INSTRUCTION = "아래 곡들로 플레이리스트를 만들어 줘. 순서는 그대로 유지하고, 목록에 없는 곡은 넣지 마."


def to_paste(pl: NarrativePlaylist) -> str:
    """유튜브 뮤직 AI 플레이리스트에 그대로 붙여넣을 텍스트."""
    lines = [PASTE_INSTRUCTION, ""]
    lines += [f"{p.position}. {p.track.title} - {p.track.artist_str}" for p in pl.ordered_songs]
    return "\n".join(lines)


def to_story(pl: NarrativePlaylist) -> str:
    """앨범 소개처럼 짧은 설명."""
    flow = " → ".join(ch.title for ch in pl.chapters)
    return f"{pl.title}\n\n{pl.description}\n\n{flow}"


def save(pl: NarrativePlaylist, canon_infos=None, out_dir: Path | None = None) -> tuple[Path, Path]:
    out_dir = out_dir or config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    md_path = out_dir / f"playlist_{stamp}.md"
    js_path = out_dir / f"playlist_{stamp}.json"
    txt_path = out_dir / f"playlist_{stamp}.txt"
    txt_path.write_text(f"{to_story(pl)}\n\n{'-' * 40}\n\n{to_paste(pl)}\n", encoding="utf-8")
    md_path.write_text(to_markdown(pl, canon_infos), encoding="utf-8")
    js = {
        "title": pl.title,
        "description": pl.description,
        "arc": pl.arc_name,
        "chapters": [
            {
                "stage": ch.stage,
                "title": ch.title,
                "blurb": ch.blurb,
                "songs": [
                    {
                        "position": p.position,
                        "video_id": p.track.video_id,
                        "title": p.track.title,
                        "artists": p.track.artists,
                        "note": p.note,
                        "valence": p.analysis.valence,
                        "arousal": p.analysis.arousal,
                        "pinned": (canon_infos or {}).get(p.track.video_id, CanonInfo()).is_pinned,
                    }
                    for p in ch.songs
                ],
            }
            for ch in pl.chapters
        ],
    }
    js_path.write_text(json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, js_path


def print_summary(pl: NarrativePlaylist, canon_infos=None) -> None:
    rule = "─" * 44
    print(f"\n{rule}\n🎧 {to_story(pl)}\n{rule}")
    print("▼ 유튜브 뮤직 → 보관함 → 새로 만들기 → AI 플레이리스트에 붙여넣기\n")
    print(to_paste(pl))
    print(rule + "\n")
