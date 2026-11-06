"""서사 곡선 위에 곡을 배치한다.

1. 템플릿(예: 만남→설렘→권태→갈등→이별→회상)을 N개의 '자리(slot)'로 쪼갠다.
   자리마다 목표 단계와 목표 감정값(valence, arousal, tension)이 있다.
2. 곡×자리 비용 행렬을 만들고 헝가리안 알고리즘으로 최적 배정한다.
   곡이 자리보다 많으면 가장 잘 맞는 곡들만 뽑힌다.
3. 같은 챕터 안에서 곡끼리 자리를 바꿔보며 전환(에너지 급변, 이미지 연결)을 다듬는다.
4. 작가 의도(canon): 고정 곡은 반드시 포함·지정 단계에 놓이고, 순서가 중요한 앨범은 앨범 순서를 지킨다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

from .canon import CanonInfo, blend_stage_fit
from .models import LOVE_STAGES, PlacedSong, SongAnalysis, Track

# ---------------------------------------------------------------- 템플릿


@dataclass(frozen=True)
class Segment:
    name: str  # 챕터 이름
    share: float  # 전체 길이 중 비중
    stage_weights: dict  # LOVE_STAGES 중 이 챕터가 대표하는 단계
    valence: tuple[float, float]  # 챕터 시작 → 끝 목표값
    arousal: tuple[float, float]
    tension: tuple[float, float]


ARCS: dict[str, list[Segment]] = {
    # 연애의 처음부터 끝까지
    "love": [
        Segment("만남", 0.14, {"만남": 1}, (0.2, 0.5), (0.3, 0.45), (0.1, 0.1)),
        Segment("설렘", 0.20, {"설렘": 1}, (0.6, 0.9), (0.5, 0.75), (0.05, 0.1)),
        Segment("권태", 0.14, {"권태": 1}, (0.3, 0.0), (0.35, 0.25), (0.3, 0.45)),
        Segment("갈등", 0.20, {"갈등": 1}, (-0.2, -0.6), (0.6, 0.9), (0.7, 0.9)),
        Segment("이별", 0.18, {"이별": 1}, (-0.6, -0.85), (0.45, 0.2), (0.5, 0.3)),
        Segment("회상", 0.14, {"회상": 1}, (-0.3, 0.1), (0.2, 0.3), (0.2, 0.1)),
    ],
    # 사랑에서 시작해 이별로 끝나는 짧은 버전
    "heartbreak": [
        Segment("설렘", 0.25, {"만남": 0.5, "설렘": 1}, (0.5, 0.85), (0.45, 0.7), (0.05, 0.1)),
        Segment("균열", 0.25, {"권태": 1, "갈등": 0.5}, (0.2, -0.2), (0.4, 0.55), (0.35, 0.6)),
        Segment("갈등", 0.25, {"갈등": 1}, (-0.3, -0.7), (0.65, 0.9), (0.75, 0.9)),
        Segment("이별", 0.25, {"이별": 1, "회상": 0.3}, (-0.7, -0.85), (0.4, 0.15), (0.4, 0.2)),
    ],
    # 사랑 서사가 아닌 곡 모음에도 쓰는 일반 기승전결
    "kishotenketsu": [
        Segment("기", 0.25, {"만남": 1, "설렘": 0.4}, (0.2, 0.4), (0.3, 0.45), (0.1, 0.2)),
        Segment("승", 0.25, {"설렘": 1, "권태": 0.3}, (0.5, 0.8), (0.5, 0.75), (0.1, 0.25)),
        Segment("전", 0.25, {"갈등": 1, "이별": 0.4}, (0.0, -0.6), (0.7, 0.9), (0.6, 0.9)),
        Segment("결", 0.25, {"이별": 0.6, "회상": 1}, (-0.4, 0.1), (0.35, 0.2), (0.3, 0.1)),
    ],
}

# ---------------------------------------------------------------- 가중치

W_STAGE = 3.0  # 단계 적합도
W_EMOTION = 1.5  # 감정 곡선 거리
W_LOWCONF = 0.4  # 확신 낮은 곡 페널티
PIN_STAGE_PENALTY = 50.0  # 고정 곡이 다른 단계에 놓이면
PIN_WHERE_WEIGHT = 4.0  # 고정 곡의 단계 안 위치(early/mid/late)
MUST_INCLUDE_BONUS = 100.0  # 고정 곡은 반드시 뽑히게 (PIN_STAGE_PENALTY 보다 커야 함)
ALBUM_ORDER_PENALTY = 10.0  # 순서 중요한 앨범의 순서 역전
W_AROUSAL_JUMP = 0.8  # 연속 곡 에너지 급변
W_IMAGERY = 0.3  # 연속 곡 이미지 공유 보너스


@dataclass
class Slot:
    index: int
    seg_index: int
    seg: Segment
    frac: float  # 챕터 안 위치 0~1
    valence: float
    arousal: float
    tension: float


def build_slots(arc: list[Segment], n: int, required: set[int] | None = None) -> list[Slot]:
    """비중대로 n개 자리를 나눈다 (최대잉여 방식).

    가능하면 챕터마다 최소 1자리. 곡 수가 챕터 수보다 적으면 required(고정 곡이 있는 챕터)를 먼저 살린다.
    """
    required = required or set()
    shares = np.array([s.share for s in arc], dtype=float)
    shares /= shares.sum()
    raw = shares * n
    counts = np.floor(raw).astype(int)
    floor = np.zeros(len(arc), dtype=int)
    if n >= len(arc):
        floor[:] = 1
    else:
        for i in sorted(required, key=lambda i: -shares[i])[:n]:
            floor[i] = 1
    counts = np.maximum(counts, floor)
    while counts.sum() > n:
        reducible = np.where(counts > floor, counts - raw, -np.inf)
        counts[np.argmax(reducible)] -= 1
    while counts.sum() < n:
        counts[np.argmax(raw - counts)] += 1

    slots: list[Slot] = []
    for si, (seg, k) in enumerate(zip(arc, counts)):
        for j in range(k):
            f = (j + 0.5) / k
            lerp = lambda ab: ab[0] + (ab[1] - ab[0]) * f  # noqa: E731
            slots.append(Slot(len(slots), si, seg, f, lerp(seg.valence), lerp(seg.arousal), lerp(seg.tension)))
    return slots


# ---------------------------------------------------------------- 비용


def _segment_fit(fit: dict[str, float], seg: Segment) -> float:
    total = sum(seg.stage_weights.values())
    return sum(w * fit.get(s, 0.0) for s, w in seg.stage_weights.items()) / total


def _pin_cost(info: CanonInfo, slot: Slot) -> float:
    if not info.is_pinned:
        return 0.0
    w = slot.seg.stage_weights
    share = w.get(info.pin_stage, 0.0) / max(w.values())
    cost = PIN_STAGE_PENALTY * (1.0 - share)
    if share > 0 and info.pin_frac is not None:
        cost += PIN_WHERE_WEIGHT * (slot.frac - info.pin_frac) ** 2 * 4
    return cost - MUST_INCLUDE_BONUS


def slot_cost(a: SongAnalysis, info: CanonInfo, slot: Slot) -> float:
    fit = blend_stage_fit(a.stage_fit, info)
    stage = W_STAGE * (1.0 - _segment_fit(fit, slot.seg))
    emo = W_EMOTION * (((a.valence - slot.valence) / 2) ** 2 + (a.arousal - slot.arousal) ** 2 + (a.tension - slot.tension) ** 2)
    lowconf = 0.0 if info.is_pinned else W_LOWCONF * (1.0 - a.confidence)
    return stage + emo + lowconf + _pin_cost(info, slot)


def transition_cost(a: SongAnalysis, b: SongAnalysis) -> float:
    jump = max(0.0, abs(a.arousal - b.arousal) - 0.35)
    ia, ib = set(a.imagery), set(b.imagery)
    jacc = len(ia & ib) / len(ia | ib) if ia | ib else 0.0
    return W_AROUSAL_JUMP * jump - W_IMAGERY * jacc


# ---------------------------------------------------------------- 배치


def arrange(
    tracks: list[Track],
    analyses: dict[str, SongAnalysis],
    canon_infos: dict[str, CanonInfo] | None = None,
    arc_name: str = "love",
    length: int | None = None,
) -> list[PlacedSong]:
    canon_infos = canon_infos or {}
    pool = [t for t in tracks if t.video_id in analyses]
    if not pool:
        return []
    arc = ARCS[arc_name]
    n_pinned = sum(1 for t in pool if canon_infos.get(t.video_id, CanonInfo()).is_pinned)
    n = min(length or 15, len(pool))
    n = max(n, min(n_pinned, len(pool)))  # 고정 곡 수보다 짧게 만들 수는 없다

    pinned_stages = {canon_infos[t.video_id].pin_stage for t in pool if canon_infos.get(t.video_id, CanonInfo()).is_pinned}
    required = {i for i, seg in enumerate(arc) if any(seg.stage_weights.get(st, 0) == max(seg.stage_weights.values()) for st in pinned_stages)}
    slots = build_slots(arc, n, required)
    info_of = lambda t: canon_infos.get(t.video_id) or CanonInfo()  # noqa: E731
    A = lambda t: analyses[t.video_id]  # noqa: E731

    C = np.array([[slot_cost(A(t), info_of(t), s) for t in pool] for s in slots])
    rows, cols = linear_sum_assignment(C)
    order: list[Track] = [None] * n  # type: ignore[list-item]
    for r, c in zip(rows, cols):
        order[r] = pool[c]

    order = _refine(order, slots, analyses, canon_infos)
    order = _enforce_album_order(order, slots, canon_infos)

    return [
        PlacedSong(position=i + 1, stage=slots[i].seg.name, track=t, analysis=A(t))
        for i, t in enumerate(order)
    ]


def _album_inversions(order: list[Track], slots: list[Slot], canon_infos) -> int:
    inv = 0
    for i in range(len(order)):
        a = canon_infos.get(order[i].video_id)
        if not a or not a.album_order_matters:
            continue
        for j in range(i + 1, len(order)):
            b = canon_infos.get(order[j].video_id)
            if b and b.album_order_matters and b.album_key == a.album_key and slots[i].seg_index == slots[j].seg_index:
                inv += a.album_index > b.album_index
    return inv


def total_cost(order, slots, analyses, canon_infos) -> float:
    info_of = lambda t: canon_infos.get(t.video_id) or CanonInfo()  # noqa: E731
    c = sum(slot_cost(analyses[t.video_id], info_of(t), s) for t, s in zip(order, slots))
    c += sum(transition_cost(analyses[a.video_id], analyses[b.video_id]) for a, b in zip(order, order[1:]))
    c += ALBUM_ORDER_PENALTY * _album_inversions(order, slots, canon_infos)
    return c


def _refine(order, slots, analyses, canon_infos, max_passes: int = 30):
    """같은 챕터 안에서 두 곡 자리 바꾸기를 반복하며 전체 비용을 줄인다."""
    best = total_cost(order, slots, analyses, canon_infos)
    for _ in range(max_passes):
        improved = False
        for i in range(len(order)):
            for j in range(i + 1, len(order)):
                if slots[i].seg_index != slots[j].seg_index:
                    continue
                order[i], order[j] = order[j], order[i]
                c = total_cost(order, slots, analyses, canon_infos)
                if c < best - 1e-9:
                    best, improved = c, True
                else:
                    order[i], order[j] = order[j], order[i]
        if not improved:
            break
    return order


def _enforce_album_order(order, slots, canon_infos):
    """안전장치: 챕터 안에서 같은 '순서 중요' 앨범 곡들은 앨범 순서대로 다시 앉힌다."""
    groups: dict[tuple[int, str], list[int]] = {}
    for i, t in enumerate(order):
        info = canon_infos.get(t.video_id)
        if info and info.album_order_matters:
            groups.setdefault((slots[i].seg_index, info.album_key), []).append(i)
    for idxs in groups.values():
        songs = sorted((order[i] for i in idxs), key=lambda t: canon_infos[t.video_id].album_index)
        for i, t in zip(idxs, songs):
            order[i] = t
    return order


def stage_of_segments(arc_name: str) -> list[str]:
    return [s.name for s in ARCS[arc_name]]


assert all(set(s.stage_weights) <= set(LOVE_STAGES) for arc in ARCS.values() for s in arc)
