"""곡 하나하나를 LLM에게 읽혀 '서사 태그'를 붙인다.

가사 전문은 모델 입력으로만 쓰고, 결과(summary 등)에는 가사를 인용하지 않게 한다.
나중에 공개 앱으로 가도 화면에 가사가 노출되지 않도록 하기 위함.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config
from .cache import JsonCache
from .canon import CanonInfo
from .llm import structured_call
from .models import LOVE_STAGES, SongAnalysis, Track

MAX_LYRICS_CHARS = 3500

SYSTEM = """너는 한국 인디·대중음악을 깊이 이해하는 음악 평론가이자 플레이리스트 큐레이터다.
곡 하나를 받으면, 이 곡이 '한 연애의 서사' 속 어느 장면에 놓이면 가장 자연스러운지 판단한다.

판단 기준
- 가사의 상황(누구에게, 언제, 무슨 일이 일어나는지)을 1순위로 본다.
- 곡의 분위기(템포감, 편곡, 음색)를 네가 아는 범위에서 2순위로 반영한다.
- 밝은 멜로디에 슬픈 가사처럼 둘이 어긋나면, 서사 배치는 가사 쪽을 따르되 valence에 그 아이러니를 조금 반영한다.
- 사랑 노래가 아닌 곡도 '그 감정이 연애의 어느 국면과 닮았는지'로 점수를 매긴다.

출력 규칙
- summary, perspective는 반드시 너의 말로 쓴다. 가사를 그대로 옮기지 않는다(3단어 이상 연속 인용 금지).
- 가사가 주어지지 않았다면 제목·아티스트·앨범과 네 지식으로만 추정하고 confidence를 0.4 이하로 둔다.
  곡을 모르면 아는 척하지 말고 confidence를 0.2 이하로 둔다."""

SCHEMA = {
    "type": "object",
    "properties": {
        "stage_fit": {
            "type": "object",
            "description": "각 서사 단계에 이 곡이 어울리는 정도 (0~1). 여러 단계에 걸칠 수 있다.",
            "properties": {s: {"type": "number", "minimum": 0, "maximum": 1} for s in LOVE_STAGES},
            "required": LOVE_STAGES,
        },
        "valence": {"type": "number", "minimum": -1, "maximum": 1, "description": "감정 극성. -1 절망 ~ 1 행복"},
        "arousal": {"type": "number", "minimum": 0, "maximum": 1, "description": "에너지. 0 고요 ~ 1 격앙"},
        "tension": {"type": "number", "minimum": 0, "maximum": 1, "description": "관계의 긴장·갈등 정도"},
        "imagery": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
            "description": "곡의 핵심 이미지·공간 키워드 (예: 바다, 새벽, 방, 비, 기차). 한국어 명사 1~2단어.",
        },
        "perspective": {"type": "string", "description": "화자가 누구에게 어떤 처지에서 말하는지 한 문장"},
        "summary": {"type": "string", "description": "곡의 정서와 상황을 자기 말로 1~2문장. 가사 인용 금지."},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["stage_fit", "valence", "arousal", "tension", "imagery", "perspective", "summary", "confidence"],
}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def analyze_one(track: Track, lyrics: str | None, canon_info: CanonInfo | None = None) -> SongAnalysis:
    meta = f"제목: {track.title}\n아티스트: {track.artist_str}\n앨범: {track.album or '-'}"
    if lyrics:
        body = lyrics.strip()[:MAX_LYRICS_CHARS]
        user = f"{meta}\n\n<lyrics>\n{body}\n</lyrics>"
    else:
        user = f"{meta}\n\n(가사를 구하지 못했다. 메타데이터와 네 지식으로만 판단하라.)"
    if canon_info and canon_info.notes:
        notes = "\n".join(f"- {n}" for n in canon_info.notes)
        user += (
            "\n\n<author_intent>\n사용자가 확인한 작가 의도다. 네 해석과 다르면 이쪽을 따르고, "
            f"수치(valence 등)도 이 맥락에 맞춰라.\n{notes}\n</author_intent>"
        )

    d = structured_call(
        model=config.ANALYSIS_MODEL,
        system=SYSTEM,
        user=user,
        tool_name="record_song_analysis",
        tool_desc="곡의 서사적 특징을 기록한다.",
        schema=SCHEMA,
        max_tokens=1200,
    )
    fit = {s: _clamp(d["stage_fit"].get(s, 0), 0, 1) for s in LOVE_STAGES}
    return SongAnalysis(
        video_id=track.video_id,
        stage_fit=fit,
        valence=_clamp(d["valence"], -1, 1),
        arousal=_clamp(d["arousal"], 0, 1),
        tension=_clamp(d["tension"], 0, 1),
        imagery=[str(x) for x in d.get("imagery", [])][:5],
        perspective=d.get("perspective", ""),
        summary=d.get("summary", ""),
        confidence=_clamp(d.get("confidence", 0.5), 0, 1),
        has_lyrics=bool(lyrics),
    )


def analyze_all(
    tracks: list[Track],
    lyrics: dict[str, str | None],
    canon_infos: dict[str, CanonInfo] | None = None,
    log=print,
) -> dict[str, SongAnalysis]:
    cache = JsonCache(f"analysis_{config.ANALYSIS_VERSION}")
    canon_infos = canon_infos or {}
    results: dict[str, SongAnalysis] = {}
    todo: list[Track] = []

    def key(t: Track) -> str:
        info = canon_infos.get(t.video_id)
        return f"{t.video_id}:{info.fingerprint()}" if info and info.notes else t.video_id

    for t in tracks:
        hit = cache.get(key(t))
        if hit:
            results[t.video_id] = SongAnalysis.from_dict(hit)
        else:
            todo.append(t)

    if todo:
        log(f"LLM 분석: {len(todo)}곡 (캐시 {len(results)}곡)")
    with ThreadPoolExecutor(max_workers=config.LLM_WORKERS) as pool:
        futs = {
            pool.submit(analyze_one, t, lyrics.get(t.video_id), canon_infos.get(t.video_id)): t for t in todo
        }
        for i, fut in enumerate(as_completed(futs), 1):
            t = futs[fut]
            try:
                a = fut.result()
            except Exception as e:  # 한 곡 실패가 전체를 막지 않게
                log(f"  [{i}/{len(todo)}] {t.title} — 실패: {e}")
                continue
            cache.set(key(t), a.to_dict())
            results[t.video_id] = a
            log(f"  [{i}/{len(todo)}] {t.title} → {a.primary_stage} (v={a.valence:+.1f}, a={a.arousal:.1f})")
    return results
