# 라우팅 표 읽는 법

`config/routing.yaml` 이 전부다. 모델을 바꾸고 싶으면 이 파일만 고친다.
코드는 안 고쳐도 된다.

## 왜 장르별로 나누나

한 모델이 모든 걸 잘하지 않는다. 실제로 갈리는 지점:

| 장르 | 어려운 지점 | 그래서 고른 모델 |
|---|---|---|
| portrait | 피부 질감, 손, 눈 | `soul_2` — UGC·에디토리얼 인물 전용 |
| cinematic_still | 색보정, 아나모픽 느낌 | `cinematic_studio_2_5` — 4K 시네마 스틸 |
| product | 라벨 글자, 재질 반사 | `marketing_studio_image` — 광고 컷 특화 |
| food | 신선함, 습기 표현 | `kling_omni_image` — 사실적 표현 강함 |
| landscape | 대기 원근, 하늘 | `soul_location` — 환경 생성 전용 |
| architecture | 수직선 왜곡 | `nano_banana_pro` — 기하 정확도 높음 |
| anime_illustration | 선 품질, 해부학 | `seedream_v4_5` — 스타일 변환 강함 |
| concept_art | 실루엣 가독성 | `soul_cinematic` — 컨셉 아트 태그 |
| typography_poster | **글자 철자** | `openai_hazel` — 텍스트 렌더링 최상 |
| logo_icon | 벡터 느낌, 평면성 | `recraft_v4_1` (`model_type: vector`) |
| diagram | 라벨 겹침, 철자 | `nano_banana_pro` — 다이어그램 태그 |
| general | — | `nano_banana_pro` — 범용 폴백 |

## primary / fallback

`primary` 는 그 장르 전용 모델(대부분 Higgsfield).
`fallback` 은 범용 Gemini. `rf.py route` 가 실제로 쓸 수 있는 쪽을 고른다.

가용성 판정:
- `gemini` → 환경변수 `GEMINI_API_KEY` (또는 `GOOGLE_API_KEY`) 존재 여부
- `higgsfield` → 환경변수 `RF_HIGGSFIELD_READY=1`.
  자동 판정이 아니다. 오케스트레이터가 MCP `balance` 도구로 크레딧을 확인한 뒤
  직접 세팅한다. 크레딧 0인 계정에 잡을 던져 실패하는 걸 막는 장치다.

## 프롬프트 템플릿

`{}` 자리는 오케스트레이터가 무드보드·브리프로 채운다.
템플릿의 문장 구조 자체는 바꾸지 않는다. 장르마다 모델이 반응하는 어순이 다르고,
이 뼈대는 그걸 반영한 것이다.

`negative` 는 그 장르에서 실제로 자주 터지는 실패만 넣는다.
길게 쓸수록 좋아지지 않는다.

## 장르 추가하기

`genres:` 밑에 항목 하나 더 쓰면 끝이다. 필수 키:
`label`, `match`, `pinterest_suffix`, `primary`, `prompt_template`, `negative`.
`match` 는 AI 가 장르를 고를 때 읽는 설명이므로 구체적으로 쓴다.
