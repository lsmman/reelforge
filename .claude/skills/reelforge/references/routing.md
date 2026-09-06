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

## ref_roles — 레퍼런스를 텍스트로만 쓰지 않는다

3단계에서 모은 핀터레스트 레퍼런스는 무드보드를 쓰는 재료로만 끝나지 않고,
`rf.py gen` 이 생성 요청에 직접 붙인다. 구글 가이드의 권장은 **2~4장, 한 장에 한 역할**.
10장을 다 넣으면 서로 충돌해서 오히려 흐려진다.

역할은 장르마다 다르다. 인물에서 훔칠 것과 포스터에서 훔칠 것이 다르기 때문이다.

| 장르 | A | B | C |
|---|---|---|---|
| portrait | 키라이트 위치·연함 | 피부 렌더링·색보정 | 크롭·헤드룸 |
| product | 광원 수·스펙큘러 모양 | 배경 스윕·톤 분리 | 제품 크기·각도 |
| typography_poster | 타이포 계층 | 색 수·잉크 평면성 | 마진·그리드 |
| diagram | 노드 간격·정렬 | 획 굵기·강조색 | 라벨 크기 |

역할 문장은 전부 "이 이미지에서 X만 가져오고 나머지는 무시하라"로 끝난다.
안 그러면 레퍼런스의 피사체를 그대로 베낀다.

## guardrails — 부정문을 쓰지 않는 이유

v1 에는 `negative` 필드가 있었다. Stable Diffusion 계열의 negative prompt 를
흉내낸 것인데, **Gemini 계열에는 그런 경로가 없다.** 프롬프트는 통째로 하나의
텍스트로 읽히므로 "misspelled text 금지"는 프롬프트 안에 misspelled text 라는
개념을 심어 넣는 결과가 된다.

그래서 v2 는 같은 실패를 긍정문으로 바꿔 적는다.

| 막고 싶은 것 | v1 (부정) | v2 (긍정) |
|---|---|---|
| 철자 오류 | misspelled text, garbled letters | every word appears exactly as quoted, correctly spelled |
| 액자 속 액자 | border, frame within frame | the scene runs edge to edge with no border or inset panel |
| 수직 왜곡 | warped verticals, fisheye | all verticals stand straight and parallel |
| 플라스틱 피부 | plastic skin, over-smoothed | skin is photographed, not retouched: pores remain visible |

실제로 이 전환 하나가 A/B 에서 확인됐다 — 아래 참조.

## image_size — 기본값이 1K 다

`imageConfig.imageSize` 를 안 보내면 Gemini 는 1K 로 떨어진다. v1 은 이걸
몰라서 전부 1K 로 뽑았다. v2 의 `defaults.image_size` 는 2K 이고, 인쇄물이면
`--size 4K` 를 쓴다. 같은 프롬프트로 픽셀이 4배가 된다.

## 프롬프트 템플릿

`{}` 자리는 오케스트레이터가 무드보드·브리프로 채운다.
템플릿의 문장 구조 자체는 바꾸지 않는다. 장르마다 모델이 반응하는 어순이 다르고,
이 뼈대는 그걸 반영한 것이다.

`guardrails` 는 그 장르에서 실제로 자주 터지는 실패만, 긍정문으로 넣는다.
길게 쓸수록 좋아지지 않는다.

템플릿은 문장형이다. 모델이 태그 나열보다 짧은 브리프 문장에 훨씬 잘 반응한다.

## 장르 추가하기

`genres:` 밑에 항목 하나 더 쓰면 끝이다. 필수 키:
`label`, `match`, `pinterest_suffix`, `primary`, `prompt_template`, `negative`.
`match` 는 AI 가 장르를 고를 때 읽는 설명이므로 구체적으로 쓴다.
`ref_roles` 를 빼면 `defaults.ref_roles` (조명 / 팔레트 / 구도) 가 쓰인다.

## v2 로 바꾸고 실제로 오른 점수

기존 23런 중 점수가 가장 낮았던 4건을 v2 로 다시 돌렸다. 프롬프트의 의도는
같게 두고 형식만 v2 규칙(문장형 + 긍정 가드레일 + 레퍼런스 3장 + 2K)으로 바꿨다.

| 런 | 장르 | v1 | v2 | 무엇이 달라졌나 |
|---|---|---:|---:|---|
| rooftop-anime | anime_illustration | 87 | **93** | 실종됐던 2단 셀 셰이딩이 들어옴 |
| earbuds | product | 88 | **94** | 배경·제품 톤 분리, 제품이 프레임의 3/4 |
| portrait-daylight | portrait | 90 | **95** | 나이대·크롭·림라이트 모두 교정 |
| film-week | typography_poster | 91 | **93** | 중앙 그래픽이 필름 스트립으로 읽힘 |

평균 89.0 → 93.75.
