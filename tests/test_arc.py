import json
from pathlib import Path

import pytest

from narrative_playlist.arc import ARCS, arrange, build_slots
from narrative_playlist.canon import Canon, CanonInfo
from narrative_playlist.models import SongAnalysis, Track

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures"


@pytest.fixture
def demo():
    data = json.loads((FIX / "demo_songs.json").read_text(encoding="utf-8"))
    tracks = [Track.from_dict(d["track"]) for d in data]
    analyses = {d["track"]["video_id"]: SongAnalysis.from_dict(d["analysis"]) for d in data}
    canon = Canon.load([FIX / "demo_canon.yaml"])
    infos = {t.video_id: canon.lookup(t) for t in tracks}
    return tracks, analyses, infos


def _pos(placed, title):
    return next(p for p in placed if p.track.title == title)


@pytest.mark.parametrize("arc", list(ARCS))
@pytest.mark.parametrize("n", [3, 7, 12, 20])
def test_slots_sum_and_cover(arc, n):
    slots = build_slots(ARCS[arc], n)
    assert len(slots) == n
    if n >= len(ARCS[arc]):
        assert {s.seg_index for s in slots} == set(range(len(ARCS[arc])))
    # 챕터 순서가 단조 증가
    assert [s.seg_index for s in slots] == sorted(s.seg_index for s in slots)


def test_pinned_song_goes_to_its_stage_and_late(demo):
    tracks, analyses, infos = demo
    placed = arrange(tracks, analyses, infos, "love", 12)
    p = _pos(placed, "마지막 갈증")
    assert p.stage == "이별"
    same = [x for x in placed if x.stage == "이별"]
    assert same[-1].track.title == "마지막 갈증"  # where: late
    assert _pos(placed, "모든 게 사랑").stage == "설렘"


def test_without_canon_llm_alone_disagrees(demo):
    """작가 의도가 없으면 LLM 점수만으로는 '마지막 갈증'이 갈등으로 간다 — 즉 canon 이 실제로 결과를 바꾼다."""
    tracks, analyses, _ = demo
    placed = arrange(tracks, analyses, {}, "love", 12)
    titles = [p.track.title for p in placed]
    if "마지막 갈증" in titles:
        assert _pos(placed, "마지막 갈증").stage != "이별"


def test_pinned_always_included_even_when_short(demo):
    tracks, analyses, infos = demo
    placed = arrange(tracks, analyses, infos, "love", 2)
    titles = {p.track.title for p in placed}
    assert {"모든 게 사랑", "마지막 갈증"} <= titles


def test_album_order_respected_within_chapter(demo):
    tracks, analyses, infos = demo
    for n in (8, 12, 17):
        placed = arrange(tracks, analyses, infos, "love", n)
        by_stage = {}
        for p in placed:
            info = infos[p.track.video_id]
            if info.album_order_matters:
                by_stage.setdefault(p.stage, []).append(info.album_index)
        for idxs in by_stage.values():
            assert idxs == sorted(idxs)


def test_length_larger_than_pool(demo):
    tracks, analyses, infos = demo
    placed = arrange(tracks, analyses, infos, "love", 100)
    assert len(placed) == len(tracks)
    assert len({p.track.video_id for p in placed}) == len(tracks)


def test_low_confidence_song_dropped_first(demo):
    tracks, analyses, infos = demo
    placed = arrange(tracks, analyses, infos, "love", 12)
    assert "잘 모르는 노래" not in {p.track.title for p in placed}


# ---------------------------------------------------------------- 실제 검정치마 canon 파일


@pytest.fixture
def bs_canon():
    return Canon.load([ROOT / "canon" / "the_black_skirts.yaml"])


@pytest.mark.parametrize(
    "title,artist,album",
    [
        ("피와 갈증", "검정치마", "THIRSTY"),
        ("피와 갈증 (King of Hurts)", "검정치마", "THIRSTY"),
        ("Blood and Thirst (King of Hurts)", "The Black Skirts", "Thirsty"),
        ("피와 갈증", "검정치마", None),  # 앨범 정보 없어도 tracklist 로 찾는다
    ],
)
def test_black_skirts_blood_and_thirst(bs_canon, title, artist, album):
    info = bs_canon.lookup(Track("x", title, [artist], album))
    assert info.pin_stage == "이별" and info.pin_where == "late"
    assert info.album_key == "thirsty" and info.album_index == 11 and info.album_order_matters


def test_black_skirts_love_is_all(bs_canon):
    info = bs_canon.lookup(Track("y", "Love Is All", ["검정치마"], "TEAM BABY"))
    assert info.pin_stage == "설렘"
    assert info.stage_prior["설렘"] == 1.0


def test_other_artist_not_matched(bs_canon):
    info = bs_canon.lookup(Track("z", "Love is all", ["다른 가수"], None))
    assert not info.is_pinned and info.album_key is None


def test_invalid_stage_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("artist: A\nsongs:\n  - title: X\n    stage: 사랑\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Canon.load([bad])


def test_fingerprint_changes_with_canon():
    a = CanonInfo(pin_stage="이별", notes=["n"])
    b = CanonInfo(pin_stage="갈등", notes=["n"])
    assert a.fingerprint() != b.fingerprint()
