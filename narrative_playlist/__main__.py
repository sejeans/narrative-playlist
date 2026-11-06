"""CLI 진입점: python -m narrative_playlist <명령>"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import config
from .arc import ARCS

AUTH_GUIDE = """
유튜브 뮤직 인증 (browser 방식)
 1. PC 브라우저로 https://music.youtube.com 에 로그인한다.
 2. 개발자도구(F12) → Network 탭 → 필터에 'browse' 입력.
 3. 라이브러리 등을 눌러 POST 요청 하나를 고른다.
 4. Request Headers 전체를 복사한다.
    - Firefox: 요청 우클릭 → Copy Value → Copy Request Headers
    - Chrome : Headers 탭의 Request Headers 를 'raw' 로 보고 전체 선택 복사
 5. 아래에 붙여넣고, 빈 줄에서 Enter (macOS/Linux: Ctrl-D, Windows: Ctrl-Z 후 Enter).
"""


def main(argv=None):
    p = argparse.ArgumentParser(prog="narrative_playlist", description="좋아하는 노래로 서사가 있는 플레이리스트 만들기")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("auth", help="유튜브 뮤직 인증 파일(browser.json) 만들기")

    def add_source_args(sp):
        sp.add_argument("--source", choices=["liked", "library", "playlist"], default="liked")
        sp.add_argument("--playlist-id", help="--source playlist 일 때 플레이리스트 ID")
        sp.add_argument(
            "--artist", nargs="+", metavar="NAME",
            help="이 아티스트(들) 곡만. 여러 명은 띄어 쓰기 (예: --artist 검정치마 혁오 \"The Black Skirts\")",
        )
        sp.add_argument("--limit", type=int, default=500, help="가져올 최대 곡 수")

    b = sub.add_parser("build", help="플레이리스트 만들기")
    add_source_args(b)
    b.add_argument("--length", type=int, default=15, help="플레이리스트 곡 수")
    b.add_argument("--arc", choices=list(ARCS), default="love", help="서사 곡선 템플릿")
    b.add_argument("--publish", action="store_true", help="유튜브 뮤직에 비공개 플레이리스트로 올리기")
    b.add_argument("--no-llm-titles", action="store_true", help="챕터 제목을 LLM 없이 기본값으로")
    b.add_argument("--canon", nargs="*", type=Path, help="작가 의도 파일 지정 (기본: canon/*.yaml 전부)")

    c = sub.add_parser("canon", help="작가 의도 파일이 내 곡들과 잘 매칭되는지 확인")
    add_source_args(c)

    d = sub.add_parser("demo", help="API 키·인증 없이 가상 데이터로 배치 알고리즘 체험")
    d.add_argument("--arc", choices=list(ARCS), default="love")
    d.add_argument("--length", type=int, default=12)
    d.add_argument("--llm-titles", action="store_true", help="챕터 제목·설명을 LLM으로 (구독 플랜 또는 API 키)")

    args = p.parse_args(argv)

    if args.cmd == "auth":
        import ytmusicapi

        print(AUTH_GUIDE)
        ytmusicapi.setup(filepath=str(config.YTM_AUTH_FILE))
        print(f"\n저장 완료: {config.YTM_AUTH_FILE}")
    elif args.cmd == "build":
        from .pipeline import build

        build(
            source=args.source,
            playlist_id=args.playlist_id,
            artist=args.artist,
            limit=args.limit,
            length=args.length,
            arc=args.arc,
            publish=args.publish,
            llm_titles=not args.no_llm_titles,
            canon_paths=args.canon or None,
        )
    elif args.cmd == "canon":
        from .pipeline import check_canon

        check_canon(source=args.source, playlist_id=args.playlist_id, artist=args.artist, limit=args.limit)
    elif args.cmd == "demo":
        from .pipeline import demo

        demo(arc=args.arc, length=args.length, llm_titles=args.llm_titles)


if __name__ == "__main__":
    main()
