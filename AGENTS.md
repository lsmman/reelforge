# reelforge — 에이전트 안내

이 저장소는 **AI 에이전트가 운전석에 앉는** 이미지 생성 파이프라인이다.
너(Claude Code / Codex / Gemini CLI)가 오케스트레이터고, 웹 UI는 결과를 보는 창일 뿐이다.

## 사용자가 이미지를 만들어 달라고 하면

`.claude/skills/reelforge/SKILL.md` 를 읽고 그 9단계를 그대로 따른다.
Claude Code 라면 `reelforge` 스킬이 자동으로 잡히므로 Skill 도구로 부르면 된다.
Codex / Gemini CLI 라면 그 파일을 직접 읽어라.

요약:

```
1 brief      요청 → 주제·용도·비율·분위기
2 genre      12개 장르 중 하나로 분류
3 reference  핀터레스트에서 레퍼런스 10장
4 moodboard  레퍼런스를 실제로 보고 시각 특성 추출
5 route      장르 → 실제 쓸 수 있는 모델 확정
6 prompt     장르 템플릿 채워 프롬프트 작성
7 generate   이미지 생성
8 critique   결과물을 실제로 보고 0~100 채점
9 refine     80점 미만이면 고쳐서 7로. 최대 3회
```

## 규칙

- 네트워크·파일·상태는 `scripts/rf.py` 로만 건드린다. 직접 curl 금지.
- 이미지를 **실제로 열어보고** 무드보드와 채점을 한다. 지어내지 않는다.
- 생성 백엔드가 없으면 멈추고 필요한 키를 말한다. 우회하지 않는다.
- 모델 id 는 `config/routing.yaml` 에 있는 것만 쓴다.

## 구조

```
config/routing.yaml   장르 → 모델·프롬프트 템플릿 (사람이 고치는 파일)
scripts/rf.py         결정론적 작업 전담 CLI
runs/<slug>/          런 하나의 전부 (run.json, refs/, out/)
viewer/index.html     대시보드. file:// 로 열면 됨
```

## 자격증명

| 백엔드 | 필요한 것 |
|---|---|
| gemini | `GEMINI_API_KEY`. 환경변수 또는 저장소 루트 `.env` (gitignore 됨) |
| higgsfield | Higgsfield MCP 연결 + 크레딧. 확인 후 `RF_HIGGSFIELD_READY=1` |

둘 다 없으면 6단계까지만 진행된다 (프롬프트까지 완성, 생성은 중단).
