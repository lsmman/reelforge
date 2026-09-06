---
name: reelforge
description: 사용자가 이미지를 만들어 달라고 할 때 쓴다. 핀터레스트에서 레퍼런스를 모으고, 장르를 판별해 그 장르에 맞는 생성 모델을 고르고, 이미지를 만든 뒤 스스로 채점해 재생성한다. "이미지 만들어줘", "썸네일 뽑아줘", "포스터 만들어줘", "레퍼런스 찾아서 만들어줘", "reelforge" 같은 요청에 반드시 쓴다.
---

# reelforge — 레퍼런스 기반 이미지 생성 파이프라인

너는 오케스트레이터다. 판단은 네가 하고, 네트워크·파일·상태 관리는 `scripts/rf.py`가 한다.
셸에서 직접 curl 을 짜지 마라. 이미 만들어진 서브커맨드를 써라.

모든 명령은 저장소 루트에서 실행한다. `SLUG`은 이 런의 짧은 영문 kebab-case 이름이다.

## 9단계

### 1. brief — 요청을 정규화한다

사용자 요청에서 뽑는다: 주제, 용도(어디 쓸 건지), 비율, 분위기 3~5개.
용도가 안 나오면 **묻는다**. 비율은 용도에서 추론한다
(인스타 피드 4:5, 릴스·쇼츠 9:16, 유튜브 썸네일 16:9, 포스터 2:3, 기본 3:2).

```bash
./scripts/rf.py new SLUG --request "사용자 원문" --aspect 3:2
./scripts/rf.py set SLUG brief.subject='"..."' brief.purpose='"..."' brief.mood='["...","..."]'
```

### 2. genre — 장르를 고른다

```bash
./scripts/rf.py routing          # 12개 장르와 설명
```

`match` 설명을 읽고 하나 고른다. 확신이 0.5 미만이면 `general`을 쓰지 말고
**사용자에게 두 후보를 제시해 고르게 한다.** 장르가 틀리면 뒤의 모든 단계가 틀린다.

```bash
./scripts/rf.py set SLUG genre.id='"architecture"' genre.confidence=0.86 genre.why='"..."'
```

### 3. reference — 핀터레스트에서 레퍼런스를 모은다

검색어는 **영어로, 시각적 특성 위주로** 쓴다. 한국어 검색어는 결과가 빈약하다.
"홍대 감성 카페" → `warm minimal cafe interior daylight`.
장르 접미사는 `--genre`가 자동으로 붙인다.

```bash
./scripts/rf.py refs SLUG --query "warm minimal cafe interior daylight" --genre architecture -n 10
```

0장이 나오면 검색어를 두 번까지 바꿔 재시도하고, 그래도 실패하면 사용자에게
직접 이미지를 `runs/SLUG/refs/`에 넣어 달라고 요청한다.

### 4. moodboard — 레퍼런스를 실제로 본다

**Read 도구로 받은 이미지를 직접 열어서 봐라.** 파일명만 보고 지어내지 마라.
최소 5장을 보고 공통점을 뽑는다: 팔레트(hex 4~6개), 조명, 구도, 질감, 피할 것.

```bash
./scripts/rf.py set SLUG moodboard='{"palette":["#..."],"lighting":"...","composition":"...","texture":"...","avoid":"..."}'
```

### 5. route — 쓸 모델을 확정한다

```bash
./scripts/rf.py route SLUG --genre architecture
```

이게 백엔드 가용성(키·크레딧)을 보고 primary → fallback 순으로 고른다.
둘 다 못 쓰면 exit 2 로 멈춘다. **그때는 조용히 다른 걸 시도하지 말고**
어떤 자격증명이 필요한지 사용자에게 그대로 알려라.

Higgsfield를 쓰려면 먼저 MCP `balance` 도구로 크레딧을 확인하고,
크레딧이 있으면 `RF_HIGGSFIELD_READY=1` 을 붙여 `route`를 실행한다.

### 6. prompt — 프롬프트를 쓴다

`route` 출력의 `prompt_template` 의 `{}` 자리를 무드보드와 브리프로 채운다.
템플릿 밖의 문장을 새로 지어내지 마라 — 장르별로 검증된 뼈대다.
`negative`는 그대로 쓰되 무드보드의 `avoid`를 덧붙인다.

프롬프트는 파일로 저장한다. 셸 인용 지옥을 피한다.

```bash
cat > runs/SLUG/prompt-01.txt <<'PROMPT'
...완성된 프롬프트...
PROMPT
```

### 7. generate — 만든다

백엔드가 `gemini`면:
```bash
./scripts/rf.py gen SLUG --prompt-file runs/SLUG/prompt-01.txt
```

백엔드가 `higgsfield`면 MCP `generate_image` 를 호출하고, 결과 URL을 편입한다:
```bash
./scripts/rf.py adopt SLUG "https://...png" --backend higgsfield --model soul_2 --prompt "$(cat runs/SLUG/prompt-01.txt)"
```

### 8. critique — 결과물을 본다

**Read 도구로 생성된 이미지를 직접 열어서 봐라.** 안 보고 채점하는 건 거짓말이다.
0~100 점, 그리고 다음 시도에서 고칠 것 한 가지를 적는다.

채점 기준 (각 20점): 브리프 충실도 · 레퍼런스와의 시각적 일치 · 구도 ·
기술적 결함 없음(손·글자·기하) · 용도 적합성.

```bash
./scripts/rf.py set SLUG attempts.0.score=72 attempts.0.critique='"..."' attempts.0.fix='"..."'
```

### 9. refine — 고쳐서 다시 만든다

점수가 `defaults.score_threshold`(80) 미만이면 `fix` 를 반영해 프롬프트를 고치고
7단계로 돌아간다. **최대 3회.** 3회 후에도 미달이면 멈춘다:

```bash
./scripts/rf.py set SLUG status='"needs_human"'
```

통과하면:
```bash
./scripts/rf.py set SLUG final='"out/attempt-02.png"' status='"done"'
./scripts/rf.py index
```

사용자가 영상까지 원하면 10단계로 간다. 아니면 여기서 `viewer/index.html`
경로를 알려주고 끝낸다.

### 10. motion — 움직임을 정한다

영상은 **이미지가 통과한 다음에만** 만든다. 나쁜 스틸을 움직여도 나쁜 영상이다.

`config/routing.yaml` 의 `video.motion` 에 장르별 기본 무브가 있다. 그대로 쓰거나,
브리프에 맞게 `--motion` 으로 덮어쓴다. **화려한 무브를 넣지 마라** — 생성 영상은
카메라가 많이 움직일수록 형태가 무너진다.

### 11. animate — 만든다

```bash
./scripts/rf.py video SLUG --prompt "장면을 한 문장으로"
```

최종 이미지를 그대로 첫 프레임으로 써서 image-to-video 로 넘어간다.
Veo 는 16:9 와 9:16 만 받으므로 원본이 가로면 16:9, 세로면 9:16 으로 자동 매핑된다.
**21:9 나 4:5 원본은 잘린다.** 영상까지 갈 계획이면 1단계에서 비율을 16:9 나 9:16 으로
잡아두는 편이 낫다.

비용을 아끼려면 `--cheap` 을 붙여 fast 모델을 쓴다.

### 12. critique — 영상을 본다

프레임을 뽑아서 **실제로 봐라.**

```bash
ffmpeg -v error -i runs/SLUG/out/video-01.mp4 \
  -vf "select='eq(n\,0)+eq(n\,60)+eq(n\,120)+eq(n\,179)',scale=480:-1,tile=2x2" \
  -frames:v 1 -y /tmp/frames.jpg
```

볼 것: 스틸의 색과 구도가 유지되는가 · 형태가 무너지는 구간이 없는가 ·
무브가 지시대로인가 · 8초 내내 쓸 만한가.

```bash
./scripts/rf.py set SLUG videos.0.score=88 videos.0.critique='"..."' videos.0.fix='"..."'
./scripts/rf.py index
```

## 하지 말 것

- 레퍼런스를 안 보고 무드보드를 지어내기
- 생성 이미지를 안 보고 점수 매기기
- `route`가 막혔는데 다른 백엔드를 몰래 시도하기
- 라우팅 표에 없는 모델 id 를 즉석에서 만들어내기
- 3회를 넘겨 계속 재생성하기 (비용이 든다)
- 이미지가 임계값을 못 넘었는데 영상으로 넘어가기
- 프레임을 안 뽑아보고 영상을 채점하기

## 상세 참조

- 라우팅 표 구조와 모델 선택 근거: `references/routing.md`
- `rf.py` 서브커맨드 전체: `./scripts/rf.py --help`
