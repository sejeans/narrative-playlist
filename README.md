# Narrative Playlist

좋아요 누른 노래들로 **처음부터 끝까지 하나의 이야기가 들리는** 플레이리스트를 만든다.
만남 → 설렘 → 권태 → 갈등 → 이별 → 회상처럼 기승전결이 있는 순서로, 가사와 분위기를 읽어서.

그리고 **작가가 분명히 의도한 서사는 AI 추정보다 우선한다.**
예: 검정치마의 `Love is all`은 사랑의 한가운데, `피와 갈증`은 이별의 막바지.

```
🎧 바다가 검게 보이던 해
  [1] 막차의 온도 (만남)
  [2] 여름이 쏟아질 때 (설렘)      Love is all 📌
  ...
  [5] 끝의 끝 (이별)                ... 피와 갈증 📌  ← 챕터 마지막
  [6] 열일곱의 나에게 (회상)
```

## 어떻게 동작하나

1. **수집** — 유튜브 뮤직 좋아요 / 라이브러리 / 특정 플레이리스트 ([ytmusicapi](https://github.com/sigma67/ytmusicapi))
2. **작가 의도 매칭** — `canon/*.yaml`에서 곡·앨범을 찾는다 (아래 참고)
3. **가사** — 유튜브 뮤직 가사, 없으면 [LRCLIB](https://lrclib.net)
4. **곡 분석 (LLM)** — 곡마다 서사 단계 적합도, 감정(밝기·에너지·긴장도), 핵심 이미지, 한 줄 요약.
   작가 의도가 있으면 프롬프트에 '확인된 사실'로 같이 넣는다.
5. **배치** — 감정 곡선 템플릿을 N개 자리로 쪼개고, 곡×자리 비용 행렬을 헝가리안 알고리즘으로 최적 배정.
   그다음 챕터 안에서 자리를 바꿔가며 전환(에너지 급변, 이미지 연결)을 다듬는다.
6. **작명 (LLM)** — 플레이리스트 제목, 챕터 제목, 곡별 "왜 여기에" 한 줄
7. **출력** — 터미널과 `output/playlist_*.txt`에 두 가지를 낸다.
   - 앨범 소개 같은 짧은 설명 (제목 + 줄거리 + 챕터 흐름)
   - 유튜브 뮤직 **보관함 → 새로 만들기 → AI 플레이리스트**에 그대로 붙여넣을 곡 목록
   
   `--publish`를 주면 붙여넣기 대신 API로 바로 비공개 플레이리스트를 만든다. 상세 해설은 `.md`에.

가사는 분석 입력으로만 쓰고 결과물 어디에도 출력하지 않는다.

## 설치

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Claude 연결 — 구독 플랜 (API 키 불필요)

[Claude Code](https://code.claude.com/docs/en/setup)를 설치하고 터미널에서 `claude`를 한 번 실행해 내 Claude 계정(Pro/Max)으로 로그인하면 끝이다.
프로그램이 `claude -p`를 호출하고, 사용량은 내 구독 플랜에서 차감된다.

- 곡마다 한 번씩 호출하므로 좋아요가 많으면 플랜 사용량 한도에 걸릴 수 있다. `--artist`나 `--limit`으로 줄이자.
  한 번 분석한 곡은 캐시돼서 다시 호출하지 않는다. 한도에 걸려 실패한 곡은 다음 실행 때 이어서 분석한다.
- API 키로 쓰고 싶으면 `.env`에 `ANTHROPIC_API_KEY`를 넣는다 (있으면 자동으로 API를 쓴다. `NP_LLM_BACKEND=cli`로 강제 가능).

### 유튜브 뮤직 인증

```bash
python -m narrative_playlist auth
```

화면 안내대로 music.youtube.com 요청 헤더를 붙여넣으면 `browser.json`이 생긴다.
(ytmusicapi의 OAuth 방식은 현재 유튜브 뮤직에서 잘 막혀서 브라우저 헤더 방식을 쓴다. 로그아웃하면 다시 만들어야 한다.)

## 사용법

```bash
# 먼저 인증 없이 알고리즘 체험 (가상의 밴드 데이터)
python -m narrative_playlist demo

# 작가 의도 파일이 내 곡들과 잘 매칭되는지 확인
python -m narrative_playlist canon --artist 검정치마

# 검정치마 좋아요 곡으로 15곡짜리 연애 서사
python -m narrative_playlist build --artist 검정치마

# 여러 아티스트 섞기 (띄어쓰기로 구분, 이름에 공백 있으면 따옴표)
python -m narrative_playlist build --artist 검정치마 혁오 "Car, the garden" --length 20

# 아티스트 지정 없이 좋아요 전체에서
python -m narrative_playlist build --limit 200

# 12곡, 짧은 이별 서사, 유튜브 뮤직에 올리기
python -m narrative_playlist build --artist 검정치마 --length 12 --arc heartbreak --publish

# 특정 플레이리스트에서
python -m narrative_playlist build --source playlist --playlist-id PLxxxx
```

| 곡선 `--arc` | 챕터 |
|---|---|
| `love` (기본) | 만남 · 설렘 · 권태 · 갈등 · 이별 · 회상 |
| `heartbreak` | 설렘 · 균열 · 갈등 · 이별 |
| `kishotenketsu` | 기 · 승 · 전 · 결 (사랑 노래가 아닌 모음에도) |

## 작가 의도 파일 (`canon/*.yaml`)

AI가 가사만 보고 헷갈릴 수 있는 곡을 사람이 바로잡는 곳. 블로그·인터뷰·라이너노트에서 **확인한 것만** 적는다.

```yaml
artist: 검정치마
artist_aliases: [The Black Skirts]

albums:
  - name: THIRSTY
    stage_prior: {갈등: 1.0, 이별: 0.8}   # 앨범 전체가 다루는 국면 (LLM 판단과 6:4로 섞임)
    track_order_matters: true            # 같은 챕터에 모이면 앨범 순서대로
    tracklist:
      - 틀린질문 | Wrong Question          # | 로 다른 표기 추가
      - ...
      - 피와 갈증 | Blood and Thirst | King of Hurts

songs:
  - title: 피와 갈증
    stage: 이별       # 만남/설렘/권태/갈등/이별/회상
    where: late       # 그 단계 안에서 early / mid / late
    note: 이별의 막바지에 놓이는 곡.
```

반영 강도: **곡 고정(`songs`)** — 반드시 포함, 반드시 그 단계 > **앨범 순서** > **앨범 사전분포** > LLM 판단.

`canon/the_black_skirts.yaml`에 사랑 3부작(TEAM BABY → THIRSTY → TEEN TROUBLES) 구조와
`Love is all`, `피와 갈증` 고정이 들어 있다. TEAM BABY·TEEN TROUBLES 트랙 순서와 다른 곡들은 직접 채우면 된다.
제목 표기가 달라 매칭이 안 되면 `canon` 명령으로 확인하고 `aliases`에 추가.

## 설정 (`.env`)

| 변수 | 기본값 | |
|---|---|---|
| `NP_LLM_BACKEND` | `auto` | `cli`(구독 플랜) / `api`(API 키) / `auto`(키 있으면 api) |
| `ANTHROPIC_API_KEY` | — | api 백엔드일 때만 |
| `NP_ANALYSIS_MODEL` | `claude-haiku-5-5` | 곡별 분석 (곡 수만큼 호출). cli 에선 `haiku` 별칭으로 |
| `NP_TITLING_MODEL` | `claude-sonnet-5-5` | 제목·설명 (1회). cli 에선 `sonnet` 별칭으로 |
| `NP_LLM_WORKERS` | cli `2` / api `4` | 동시 분석 수 |

분석 결과는 `.cache/`에 저장돼서 같은 곡은 다시 호출하지 않는다. `canon`을 고치면 해당 곡만 다시 분석한다.

## 테스트

```bash
pytest
```

네트워크 없이 돌아간다 (유튜브 뮤직·LLM 응답을 흉내 냄).

## 로드맵

- [ ] 혼자 써보며 튜닝 — `arc.py`의 가중치, 곡선 템플릿 목표값
- [ ] canon 공유 — 아티스트별 작가 의도 파일을 PR로 모으기
- [ ] 자연어 곡선 — "여름에 만나 겨울에 헤어지는" 같은 문장으로 템플릿 생성
- [ ] 웹 / 앱 — `pipeline.py`를 API로 감싸고 캐시를 DB로

## 주의

- 구독 플랜(cli) 백엔드는 **내가 내 PC에서 쓰는 용도**다. 남에게 서비스하는 웹·앱에서 사용자의 Claude 로그인을 쓰게 하는 건
  Anthropic이 허용하지 않으니, 앱 출시 단계에서는 API 키 백엔드로 바꿔야 한다.
- ytmusicapi는 비공식 라이브러리라 유튜브 쪽 변경으로 깨질 수 있다. 개인 사용·오픈소스 수준은 괜찮지만 상용 앱은 약관 검토가 필요하다.
- 가사는 저작물이다. 분석 입력으로만 쓰고, 결과·로그·캐시를 공개 저장소에 올리지 않는다 (`.gitignore` 처리됨).
