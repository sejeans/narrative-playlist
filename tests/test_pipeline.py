"""네트워크 없이 유튜브 뮤직·LLM 응답을 흉내 내서 build 전체 흐름을 확인한다."""

from types import SimpleNamespace

import pytest

from narrative_playlist import analyze, config, lyrics, pipeline, titling, ytmusic
from narrative_playlist.models import LOVE_STAGES


class FakeYT:
    def __init__(self):
        self.created = None

    def get_liked_songs(self, limit=100):
        mk = lambda vid, title, artist, album: {  # noqa: E731
            "videoId": vid, "title": title, "artists": [{"name": artist}],
            "album": {"name": album} if album else None, "duration_seconds": 200,
        }
        return {"tracks": [
            mk("a", "Love Is All", "검정치마", "TEAM BABY"),
            mk("b", "피와 갈증 (King of Hurts)", "검정치마", "THIRSTY"),
            mk("c", "상수역", "검정치마", "THIRSTY"),
            mk("d", "Everything", "검정치마", "201"),
            mk("e", "다른 노래", "다른 가수", None),
            mk("a", "Love Is All", "검정치마", "TEAM BABY"),  # 중복
            {"videoId": None, "title": "삭제된 곡"},
        ]}

    def get_watch_playlist(self, videoId, limit=1):
        return {"lyrics": f"L{videoId}" if videoId != "d" else None}

    def get_lyrics(self, browseId):
        return {"lyrics": f"가사 {browseId}", "source": "x", "hasTimestamps": False}

    def create_playlist(self, title, description, privacy_status="PRIVATE", video_ids=None):
        self.created = (title, privacy_status, video_ids)
        return "PLfake"


def fake_structured_call(*, tool_name, user, **_):
    if tool_name == "record_song_analysis":
        # LLM은 '피와 갈증'을 갈등으로 본다고 가정 — canon 이 이별로 끌어와야 한다
        fit = {s: 0.1 for s in LOVE_STAGES}
        if "피와 갈증" in user:
            fit["갈등"] = 0.95
            assert "<author_intent>" in user and "막바지" in user
        elif "Love Is All" in user:
            fit["설렘"] = 0.9
        else:
            fit["권태"] = 0.6
        return {"stage_fit": fit, "valence": 0.0, "arousal": 0.5, "tension": 0.5, "imagery": ["밤"],
                "perspective": "p", "summary": "s", "confidence": 0.8}
    n_ch = user.count("## 챕터")
    n_songs = sum(1 for line in user.splitlines() if line[:1].isdigit())
    return {"title": "T", "description": "D",
            "chapters": [{"title": f"c{i}", "blurb": "b"} for i in range(n_ch)],
            "song_notes": [f"n{i}" for i in range(n_songs)]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    yt = FakeYT()
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(ytmusic, "connect", lambda *a, **k: yt)
    monkeypatch.setattr(lyrics, "fetch_lrclib", lambda t: None)
    monkeypatch.setattr(lyrics.time, "sleep", lambda s: None)
    monkeypatch.setattr(analyze, "structured_call", fake_structured_call)
    monkeypatch.setattr(titling, "structured_call", fake_structured_call)
    return yt


def test_build_end_to_end(env):
    pl, md = pipeline.build(artist="검정치마", length=4, publish=True, log=lambda *a: None)
    songs = pl.ordered_songs
    titles = [p.track.title for p in songs]
    assert "다른 노래" not in titles and len(titles) == len(set(titles)) == 4
    blood = next(p for p in songs if p.track.title.startswith("피와 갈증"))
    assert blood.stage == "이별"
    assert next(p for p in songs if p.track.title == "Love Is All").stage == "설렘"
    assert pl.title == "T" and all(p.note for p in songs)
    # 리포트에 가사가 새지 않는다
    assert "가사 L" not in md.read_text(encoding="utf-8")
    # 게시: 비공개, 순서 유지
    assert env.created == ("T", "PRIVATE", [p.track.video_id for p in songs])


def test_analysis_cached(env, monkeypatch):
    pipeline.build(artist="검정치마", length=4, log=lambda *a: None)
    calls = []
    monkeypatch.setattr(analyze, "structured_call", lambda **k: calls.append(1) or fake_structured_call(**k))
    pipeline.build(artist="검정치마", length=4, log=lambda *a: None)
    assert calls == []


def test_timed_lyrics_flattened(monkeypatch):
    yt = SimpleNamespace(
        get_watch_playlist=lambda videoId, limit: {"lyrics": "B"},
        get_lyrics=lambda b: {"lyrics": [SimpleNamespace(text="한 줄"), SimpleNamespace(text="두 줄")]},
    )
    assert ytmusic.fetch_yt_lyrics(yt, "v") == "한 줄\n두 줄"


def test_paste_text(env):
    from narrative_playlist.report import PASTE_INSTRUCTION, to_paste, to_story

    pl, md = pipeline.build(artist="검정치마", length=4, log=lambda *a: None)
    paste = to_paste(pl).splitlines()
    assert paste[0] == PASTE_INSTRUCTION
    assert paste[2:] == [f"{p.position}. {p.track.title} - 검정치마" for p in pl.ordered_songs]
    assert to_story(pl).startswith("T\n\nD")
    txt = md.with_suffix(".txt").read_text(encoding="utf-8")
    assert PASTE_INSTRUCTION in txt and "가사 L" not in txt


def test_multiple_artists(env):
    yt = env
    from narrative_playlist.canon import Canon

    tracks = ytmusic.fetch_tracks(yt, artist_filter=["검정치마", "다른 가수"])
    assert {t.title for t in tracks} >= {"Love Is All", "다른 노래"}
    assert len(ytmusic.fetch_tracks(yt, artist_filter="다른 가수")) == 1
    # canon 별칭 확장: 'The Black Skirts' 로 입력해도 '검정치마' 표기 곡이 잡힌다
    names = Canon.load().expand_artists(["The Black Skirts"])
    assert "검정치마" in names
    assert len(ytmusic.fetch_tracks(yt, artist_filter=names)) == 4
    pl, _ = pipeline.build(artist=["검정치마", "다른 가수"], length=5, log=lambda *a: None)
    assert "다른 노래" in {p.track.title for p in pl.ordered_songs}


def test_limit_is_exact():
    class Overshoot:
        def get_liked_songs(self, limit=100):  # ytmusicapi 처럼 페이지 단위로 더 돌려줌
            return {"tracks": [{"videoId": f"v{i}", "title": f"t{i}", "artists": []} for i in range(396)]}

    assert len(ytmusic.fetch_tracks(Overshoot(), limit=300)) == 300
    assert len(ytmusic.fetch_tracks(Overshoot(), limit=None)) == 396
