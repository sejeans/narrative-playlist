"""환경 변수와 경로 설정. .env 파일이 있으면 먼저 읽는다."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv는 선택 사항
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 유튜브 뮤직 인증 파일 (ytmusicapi browser 인증으로 만든 JSON)
YTM_AUTH_FILE = Path(os.getenv("YTM_AUTH_FILE", PROJECT_ROOT / "browser.json"))

# 캐시와 결과물 위치
CACHE_DIR = Path(os.getenv("NP_CACHE_DIR", PROJECT_ROOT / ".cache"))
OUTPUT_DIR = Path(os.getenv("NP_OUTPUT_DIR", PROJECT_ROOT / "output"))

# LLM 설정 — 곡 분석은 곡 수만큼 호출되므로 가벼운 모델, 챕터 작명은 한 번이라 좋은 모델
# 백엔드: auto(키 있으면 api, 없으면 cli) | cli(Claude 구독 플랜, Claude Code 로그인) | api(API 키)
LLM_BACKEND = os.getenv("NP_LLM_BACKEND", "auto").lower()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANALYSIS_MODEL = os.getenv("NP_ANALYSIS_MODEL", "claude-haiku-5-5")
TITLING_MODEL = os.getenv("NP_TITLING_MODEL", "claude-sonnet-5-5")
CLAUDE_CLI = os.getenv("NP_CLAUDE_CLI", "claude")
CLI_TIMEOUT = int(os.getenv("NP_CLI_TIMEOUT", "180"))
# 구독 플랜은 사용량 한도가 있어서 동시 호출을 조금 낮게
LLM_WORKERS = int(os.getenv("NP_LLM_WORKERS", "2" if LLM_BACKEND != "api" and not ANTHROPIC_API_KEY else "4"))

# 분석 프롬프트나 스키마를 바꾸면 이 값을 올려서 캐시를 무효화한다
ANALYSIS_VERSION = "v1"

# LRCLIB은 클라이언트 식별용 User-Agent를 권장한다
USER_AGENT = "narrative-playlist/0.1.0 (personal project)"
