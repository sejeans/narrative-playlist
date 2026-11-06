"""작가 의도(canon) 레이어.

LLM의 추정보다 '작가가 분명히 의도한 서사'를 우선하기 위한 사람이 쓰는 지식 파일.
canon/*.yaml 에 아티스트별로 적는다.

세 가지 수준으로 반영된다.
1. 곡 고정(pin): 이 곡은 반드시 이 단계에, (선택) 단계 안 초반/중반/후반에 놓인다. 플레이리스트에 반드시 포함된다.
2. 앨범 사전분포(stage_prior): 앨범 전체가 서사의 어느 국면을 다루는지. LLM 판단과 섞인다.
3. 트랙 순서(tracklist + track_order_matters): 같은 챕터에 같은 앨범 곡이 모이면 앨범 순서를 따른다.
또한 note 들은 LLM 분석 프롬프트에 '확인된 사실'로 들어가서 분석 자체를 그 방향으로 이끈다.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import config
from .models import LOVE_STAGES, Track

CANON_DIR = config.PROJECT_ROOT / "canon"
WHERE_TO_FRAC = {"early": 0.15, "mid": 0.5, "late": 0.9}


def norm(s: str | None) -> str:
    """제목 매칭용 정규화: 괄호 부가설명 제거, 소문자, 공백·구두점 제거."""
    if not s:
        return ""
    s = re.sub(r"[\(\[].*?[\)\]]", "", s)
    s = s.lower()
    return re.sub(r"[\s\W_]+", "", s)


@dataclass
class CanonInfo:
    pin_stage: str | None = None
    pin_where: str | None = None  # early | mid | late
    album_key: str | None = None
    album_index: int | None = None  # 앨범 내 트랙 번호 (0부터)
    album_order_matters: bool = False
    stage_prior: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def is_pinned(self) -> bool:
        return self.pin_stage is not None

    @property
    def pin_frac(self) -> float | None:
        return WHERE_TO_FRAC.get(self.pin_where) if self.pin_where else None

    def fingerprint(self) -> str:
        """canon 이 바뀌면 분석 캐시를 다시 돌리기 위한 해시."""
        raw = f"{self.pin_stage}|{self.pin_where}|{sorted(self.stage_prior.items())}|{self.notes}"
        return hashlib.sha1(raw.encode()).hexdigest()[:8]


class Canon:
    def __init__(self, entries: list[dict]):
        self.entries = entries

    @classmethod
    def load(cls, paths: list[Path] | None = None) -> "Canon":
        if paths is None:
            paths = sorted(CANON_DIR.glob("*.yaml")) if CANON_DIR.exists() else []
        entries = []
        for p in paths:
            data = yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
            _validate(data, p)
            entries.append(data)
        return cls(entries)

    def expand_artists(self, names: str | list[str] | None) -> list[str] | None:
        """'검정치마'만 줘도 canon 에 적힌 다른 표기('The Black Skirts')까지 필터에 포함한다."""
        if not names:
            return None
        if isinstance(names, str):
            names = [names]
        out = list(names)
        for n in names:
            for e in self.entries:
                all_names = [e.get("artist", "")] + list(e.get("artist_aliases", []))
                if norm(n) in {norm(x) for x in all_names}:
                    out += [x for x in all_names if x not in out]
        return out

    def _artist_entries(self, track: Track) -> list[dict]:
        names = {norm(a) for a in track.artists}
        out = []
        for e in self.entries:
            keys = {norm(e.get("artist"))} | {norm(a) for a in e.get("artist_aliases", [])}
            if names & keys:
                out.append(e)
        return out

    def lookup(self, track: Track) -> CanonInfo:
        info = CanonInfo()
        t_title = norm(track.title)
        t_album = norm(track.album)
        for e in self._artist_entries(track):
            if e.get("source_notes"):
                info.notes.append(f"[{e['artist']} 전반] {e['source_notes'].strip()}")

            # 앨범: 트랙의 앨범명 또는 tracklist 에 곡이 있는지로 찾는다
            for alb in e.get("albums", []):
                alb_keys = {norm(alb["name"])} | {norm(a) for a in alb.get("aliases", [])}
                tracklist = [norm(x) for x in alb.get("tracklist", [])]
                hit_idx = _find_in_tracklist(t_title, alb.get("tracklist", []))
                if t_album in alb_keys or hit_idx is not None:
                    info.album_key = norm(alb["name"])
                    info.album_index = hit_idx
                    info.album_order_matters = bool(alb.get("track_order_matters")) and hit_idx is not None
                    info.stage_prior = {k: float(v) for k, v in (alb.get("stage_prior") or {}).items()}
                    if alb.get("note"):
                        info.notes.append(f"[앨범 {alb['name']}] {alb['note'].strip()}")
                    if hit_idx is not None and tracklist:
                        info.notes.append(f"[앨범 {alb['name']}] 이 곡은 {len(tracklist)}곡 중 {hit_idx + 1}번 트랙")
                    break

            for s in e.get("songs", []):
                keys = {norm(s["title"])} | {norm(a) for a in s.get("aliases", [])}
                if t_title in keys:
                    info.pin_stage = s.get("stage")
                    info.pin_where = s.get("where")
                    if s.get("note"):
                        info.notes.append(f"[곡 고정] {s['note'].strip()}")
                    break
        return info


def _find_in_tracklist(t_title: str, tracklist: list) -> int | None:
    for i, item in enumerate(tracklist):
        # tracklist 항목은 "피와 갈증 | Blood and Thirst" 처럼 | 로 별칭을 줄 수 있다
        names = [norm(x) for x in str(item).split("|")]
        if t_title in names:
            return i
    return None


def _validate(data: dict, path: Path) -> None:
    if "artist" not in data:
        raise ValueError(f"{path}: artist 항목이 필요합니다.")
    for s in data.get("songs", []):
        if s.get("stage") and s["stage"] not in LOVE_STAGES:
            raise ValueError(f"{path}: '{s['title']}' 의 stage '{s['stage']}' 는 {LOVE_STAGES} 중 하나여야 합니다.")
        if s.get("where") and s["where"] not in WHERE_TO_FRAC:
            raise ValueError(f"{path}: where 는 early / mid / late 중 하나여야 합니다.")
    for a in data.get("albums", []):
        for k in (a.get("stage_prior") or {}):
            if k not in LOVE_STAGES:
                raise ValueError(f"{path}: 앨범 {a['name']} stage_prior 의 '{k}' 는 {LOVE_STAGES} 중 하나여야 합니다.")


def blend_stage_fit(llm_fit: dict[str, float], info: CanonInfo, prior_weight: float = 0.4) -> dict[str, float]:
    """LLM 단계 적합도와 앨범 사전분포를 섞고, 핀이 있으면 그 단계를 1로 고정한다."""
    fit = dict(llm_fit)
    if info.stage_prior:
        mx = max(info.stage_prior.values()) or 1.0
        prior = {s: info.stage_prior.get(s, 0.0) / mx for s in LOVE_STAGES}
        fit = {s: (1 - prior_weight) * fit.get(s, 0.0) + prior_weight * prior[s] for s in LOVE_STAGES}
    if info.pin_stage:
        fit = {s: (1.0 if s == info.pin_stage else v * 0.3) for s, v in fit.items()}
    return fit
