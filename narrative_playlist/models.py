"""파이프라인 전체에서 쓰는 데이터 구조."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# 사랑 서사의 6단계. 곡 분석은 템플릿과 무관하게 항상 이 6단계 적합도를 매긴다.
LOVE_STAGES = ["만남", "설렘", "권태", "갈등", "이별", "회상"]


@dataclass
class Track:
    video_id: str
    title: str
    artists: list[str]
    album: str | None = None
    duration_seconds: int | None = None

    @property
    def artist_str(self) -> str:
        return ", ".join(self.artists) if self.artists else "Unknown"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Track":
        return cls(**d)


@dataclass
class SongAnalysis:
    """LLM이 가사·메타데이터를 읽고 매긴 곡의 서사적 특징."""

    video_id: str
    stage_fit: dict[str, float]  # LOVE_STAGES 각 단계에 얼마나 어울리는지 0~1
    valence: float  # 감정 극성: -1(절망) ~ 1(행복)
    arousal: float  # 에너지: 0(고요) ~ 1(격앙)
    tension: float  # 관계의 긴장·갈등 정도: 0 ~ 1
    imagery: list[str] = field(default_factory=list)  # 핵심 이미지 키워드 (바다, 밤, 방 ...)
    perspective: str = ""  # 화자 시점 한 줄
    summary: str = ""  # 곡의 정서를 자기 말로 요약 (가사 인용 X)
    confidence: float = 0.5  # 가사 없이 추정했으면 낮게
    has_lyrics: bool = True

    @property
    def primary_stage(self) -> str:
        return max(self.stage_fit, key=self.stage_fit.get)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SongAnalysis":
        return cls(**d)


@dataclass
class PlacedSong:
    """곡선 위 한 자리에 배치된 곡."""

    position: int
    stage: str
    track: Track
    analysis: SongAnalysis
    note: str = ""  # 이 자리에 이 곡이 오는 이유 (LLM 작성)


@dataclass
class Chapter:
    stage: str
    title: str
    blurb: str
    songs: list[PlacedSong]


@dataclass
class NarrativePlaylist:
    title: str
    description: str
    arc_name: str
    chapters: list[Chapter]

    @property
    def ordered_songs(self) -> list[PlacedSong]:
        return [s for ch in self.chapters for s in ch.songs]
