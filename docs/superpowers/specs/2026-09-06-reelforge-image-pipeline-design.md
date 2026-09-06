# reelforge — 이미지 생성 파이프라인 설계

작성: 2026-09-06

## 한 줄 정의

터미널의 Claude Code / Codex CLI가 **오케스트레이터**가 되어, 핀터레스트 레퍼런스를
근거로 프롬프트를 짜고, 장르에 맞는 생성 모델을 골라 이미지를 만들고, 스스로 채점해
재생성하는 파이프라인. HTML 대시보드는 그 결과를 보는 창.

## 확정된 결정

| 항목 | 결정 | 이유 |
|---|---|---|
| 실행 구조 | CLI가 주인, HTML은 읽기 전용 대시보드 | 서버·세션·승인 관리 전부 불필요. 코드량 최소 |
| v1 산출물 | **이미지 1장** | 핵심 루프를 먼저 증명. 영상은 같은 루프 재사용해 확장 |
| 모델 선택 | **장르별 라우팅 표** | Kling이 하는 방식. 사람이 고칠 수 있는 YAML 한 장 |
| 레퍼런스 | 핀터레스트 무인증 스크래핑 | 로그인·API 키 불필요. 검증 완료 |
| 상태 저장 | `runs/<slug>/run.json` 한 파일 | DB 없음. 에이전트가 읽고 쓰기 쉬움 |

## 아키텍처

```
사용자 (터미널)
   │  "홍대 감성 카페 인테리어 이미지 만들어줘"
   ▼
Claude Code / Codex CLI          ← 오케스트레이터 (판단 담당)
   │  skills/reelforge/SKILL.md 를 따라 9단계 진행
   ├─► scripts/rf.py             ← 결정론적 잡일 담당 (네트워크·파일·상태)
   │      ├─ new     run.json 생성
   │      ├─ refs    핀터레스트 검색 + 레퍼런스 다운로드
   │      ├─ routing 장르 → 모델/파라미터/프롬프트 템플릿 조회
   │      ├─ gen     Gemini API 직접 호출 (백엔드 A)
   │      ├─ adopt   외부에서 만든 이미지를 run에 편입 (백엔드 B용)
   │      └─ index   runs/ 전체 → viewer/data.js
   ├─► Higgsfield MCP            ← 백엔드 B (generate_image / upscale)
   └─► runs/<slug>/{run.json, refs/, out/}
            ▲
            │ 상대경로로 이미지 참조
      viewer/index.html          ← file:// 로 바로 열림, 빌드 없음
```

**책임 분리 원칙**: 판단(장르 분류·프롬프트 작문·채점)은 AI가, 결정론적 작업
(HTTP·파일 IO·상태 갱신)은 `rf.py`가. AI가 셸에서 임의 curl을 짜지 않게 만든다.

## 파이프라인 9단계

| # | 단계 | 담당 | 산출 |
|---|---|---|---|
| 1 | `brief` | AI | 사용자 요청 → 주제·용도·비율·분위기로 정규화 |
| 2 | `genre` | AI | 라우팅 표의 장르 중 하나로 분류 (+확신도) |
| 3 | `reference` | rf.py | 장르별 검색어 접미사 붙여 핀터레스트 검색 → 8~12장 다운로드 |
| 4 | `moodboard` | AI | 레퍼런스 이미지를 실제로 보고 공통 시각 특성 추출 |
| 5 | `prompt` | AI | 장르 프롬프트 템플릿 + 무드보드 → 최종 프롬프트 + 네거티브 |
| 6 | `route` | rf.py | 장르 → 모델 id·파라미터 확정 |
| 7 | `generate` | rf.py 또는 MCP | 이미지 생성 → `out/attempt-N.png` |
| 8 | `critique` | AI | 결과물을 직접 보고 브리프·레퍼런스 대비 0~100 채점 |
| 9 | `refine` | AI | 점수 < 임계값이면 프롬프트 수정 후 7로. 최대 3회 |

## 장르 라우팅 표 (`config/routing.yaml`)

각 장르 항목:

```yaml
portrait:
  label: 인물 / 포트레이트
  pinterest_suffix: "portrait photography lighting"
  primary:   { backend: higgsfield, model: soul_2, params: { quality: "2k" } }
  fallback:  { backend: gemini, model: gemini-3-pro-image-preview }
  prompt_template: |
    ...장르별 프롬프트 뼈대...
  negative: "plastic skin, extra fingers, ..."
  upscale: { backend: higgsfield, model: topaz_image }
```

장르 12종: portrait, cinematic_still, product, food, landscape, architecture,
anime_illustration, concept_art, typography_poster, logo_icon, diagram, general.

`general`은 분류 실패 시 폴백.

## 생성 백엔드

| 백엔드 | 호출 | 상태 |
|---|---|---|
| **gemini** | `rf.py gen` 이 REST 직접 호출 | `GEMINI_API_KEY` 필요 |
| **higgsfield** | AI가 MCP `generate_image` 호출 후 `rf.py adopt` | 크레딧 필요 |

`rf.py route`가 크레딧/키 유무를 보고 실제 사용할 백엔드를 정한다. 둘 다 없으면
프롬프트까지만 만들고 명확히 멈춘다 — 조용히 실패하지 않는다.

## 상태 파일 `runs/<slug>/run.json`

```json
{
  "slug": "hongdae-cafe",
  "created_at": "2026-09-06T15:00:00+09:00",
  "brief": { "request": "...", "subject": "...", "purpose": "...",
             "aspect": "3:2", "mood": ["..."] },
  "genre": { "id": "architecture", "confidence": 0.86, "why": "..." },
  "references": [ { "file": "refs/ref-01.jpg", "pin_id": "...",
                    "source": "https://pinterest.com/pin/...",
                    "dominant_color": "#4f2b4f", "alt": "..." } ],
  "moodboard": { "palette": ["#..."], "lighting": "...", "composition": "...",
                 "texture": "...", "avoid": "..." },
  "route": { "backend": "gemini", "model": "...", "params": {} },
  "attempts": [ { "n": 1, "prompt": "...", "negative": "...",
                  "file": "out/attempt-01.png", "score": 72,
                  "critique": "...", "fix": "..." } ],
  "final": "out/attempt-03.png",
  "status": "done"
}
```

## 대시보드

`viewer/index.html` — 단일 파일, 빌드 없음, `file://` 로 열림.
`rf.py index`가 만든 `viewer/data.js`(`window.RF_DATA = {...}`)를 `<script src>`로
읽는다. fetch를 안 쓰므로 file:// CORS 문제 없음.

화면: 런 목록 → 런 상세(브리프 / 레퍼런스 그리드 / 무드보드 / 시도별 이미지+점수
타임라인 / 최종본). 라이트·다크 대응.

## 오류 처리

- 핀터레스트 403/구조 변경 → `refs` 가 0장 반환하면 명시적 실패. AI가 `--manual`로
  사용자 이미지 받는 경로 안내.
- 생성 백엔드 인증 없음 → 6단계에서 즉시 중단, 필요한 키 이름을 그대로 출력.
- 3회 재시도해도 점수 미달 → `status: "needs_human"` 으로 기록하고 멈춤.

## 검증 기준

1. `rf.py refs` 가 실제 핀터레스트 이미지 8장 이상을 디스크에 저장한다.
2. `rf.py routing portrait` 가 모델 id를 포함한 JSON을 출력한다.
3. 인증 있을 때 `rf.py gen` 이 `out/attempt-01.png` 를 만든다.
4. `viewer/index.html` 을 브라우저로 열면 런과 이미지가 보인다.

## v1에서 뺀 것 (YAGNI)

영상 합성, 대본 분할, 멀티 씬, 내레이션·자막·BGM, 웹 서버, 로그인, DB,
사용자 계정, 비용 대시보드. 전부 이미지 1장 루프가 증명된 뒤에.
