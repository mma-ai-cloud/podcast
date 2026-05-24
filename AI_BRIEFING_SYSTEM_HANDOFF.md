# AI 브리핑 전송 시스템 재구현 작업 지시서

이 문서는 Codex CLI, Gemini CLI, 또는 유사한 로컬 LLM CLI 환경에서 현재의 병무청 뉴스 AI 브리핑 시스템을 새 작업환경에 최대한 비슷하게 재구현하기 위한 지시서입니다.

민감 정보는 절대 문서나 로그에 남기지 마세요. GitHub 토큰, 네이버 API 키, 카카오톡 계정 정보는 모두 환경변수, GitHub Secrets, Google Cloud Scheduler HTTP 헤더에만 둡니다.

## 1. 최종 목표

새 저장소 또는 새 PC 환경에서 아래 두 가지 자동화가 동작해야 합니다.

1. 매일 오전 7시 KST 병무청 뉴스 브리핑
   - 네이버 뉴스 API로 전날 기사 수집
   - 키워드: `대체역심사위원회`, `양심적병역거부`, `여호와의증인`, `대체복무`, `병무청`
   - Codex CLI 또는 Gemini CLI로 카카오톡용 요약과 TTS 대본 생성
   - 카카오톡 요약은 8~10개 항목, 숫자 이모티콘 사용, 각 항목 아래 대표 기사 URL 1개만 표시
   - Edge TTS로 한국어 음성 파일 생성
   - GitHub Pages에 `index.html`, `data.json`, `briefing.mp3`, `history.json`, `archive/` 배포
   - PC 카카오톡으로 브리핑 본문과 음성요약 링크 메시지를 분리 전송

2. 15분 간격 병무청 부정이슈 탐지
   - 네이버 뉴스에서 병무청 관련 부정 이슈 후보 검색
   - LLM CLI로 실제 부정 이슈인지 판단
   - 중복 이슈는 8시간 동안 재전송하지 않음
   - 부정 이슈가 탐지되면 PC 카카오톡으로 한 메시지 전송
   - 15분 간격은 유지하되 매시 `05, 20, 35, 50분` 실행으로 오전 7시 브리핑과 충돌을 피함

## 2. 권장 아키텍처

```text
Google Cloud Scheduler
  -> GitHub repository_dispatch
    -> GitHub Actions
      -> Windows self-hosted runner
        -> Python scripts
          -> Naver News API
          -> Codex CLI or Gemini CLI
          -> Edge TTS
          -> GitHub Pages deploy
          -> PC KakaoTalk Win32 sender
```

중요한 판단:

- 카카오톡 전송은 서버 API가 아니라 로컬 Windows PC의 PC카카오톡을 Win32/클립보드 방식으로 조작한다.
- 그래서 GitHub Actions는 GitHub-hosted runner가 아니라 Windows self-hosted runner에서 실행해야 한다.
- PlayMCP 카카오톡 전송은 저장만 해둘 수 있지만, 현재 운영 흐름에서는 사용하지 않는다.
- self-hosted runner가 한 대면 긴 작업 하나가 전체 큐를 막을 수 있으므로 timeout과 스케줄 충돌 회피가 반드시 필요하다.

## 3. 필수 외부 계정과 도구

- GitHub 저장소
- GitHub Pages 활성화
- GitHub Actions self-hosted runner, Windows X64
- Google Cloud Scheduler
- Naver Search API 애플리케이션
- PC 카카오톡 로그인 상태
- Python 3.11 이상 권장
- Codex CLI 또는 Gemini CLI
- Edge TTS 의존성
- Windows 패키지: `pywin32`, `pyperclip`

## 4. GitHub Secrets

저장소 Secrets에 아래 값을 넣습니다.

```text
NAVER_CLIENT_ID
NAVER_CLIENT_SECRET
KAKAOTALK_ROOM_NAME
```

선택값:

```text
CODEX_MODEL
CODEX_COMMAND
GEMINI_MODEL
GEMINI_COMMAND
```

`KAKAOTALK_ROOM_NAME`은 실제 전송할 PC 카카오톡 방 이름입니다. 현재 운영 예시는 `대화반`입니다.

## 5. 저장소 파일 구성

새 환경에서도 아래 역할을 유지하면 재구현이 쉽습니다.

```text
app.py
  매일 브리핑 전체 파이프라인 진입점
  뉴스 수집 -> LLM 요약 -> TTS 생성 -> data.json/history/archive 생성

news_collector.py
  네이버 뉴스 API 호출
  전날 KST 기사만 필터링
  키워드 중복 제거

llm_summarizer.py
  Codex CLI 또는 Gemini CLI 호출
  카카오톡 요약문과 TTS 대본을 JSON으로 생성
  번호 이모티콘, 마크다운 제거, 각 항목 대표 URL 보강

tts_generator.py
  edge-tts로 briefing.mp3 생성

index.html
  GitHub Pages 음성요약 플레이어
  data.json과 history.json을 읽어 최신/이전 브리핑 표시

app_local_sender.py
  data.json을 읽어 PC 카카오톡으로 전송
  본문 메시지와 음성요약 링크 메시지를 분리 전송

kakaotalk_sender.py
  PC 카카오톡 창 탐색
  RICHEDIT50W 입력창에 클립보드 기반으로 메시지 입력 후 전송

negative_issue_detector.py
  15분 부정이슈 탐지
  검색, 후보 선별, LLM 분석, 8시간 중복 억제, 카카오톡 전송

negative_issue_state.json
  최근 8시간 이내 전송한 이슈 기록
  링크, 제목, 요약, 유사도 판단용 텍스트 저장

.github/workflows/daily_briefing.yml
  매일 브리핑 빌드, Pages 배포, 카카오톡 전송

.github/workflows/negative_issue_monitor.yml
  부정이슈 탐지와 상태파일 커밋
```

## 6. 매일 브리핑 메시지 형식

카카오톡 본문은 아래 형식을 목표로 합니다.

```text
📢 [오늘의 병무청 브리핑]

1️⃣ 제목
내용 한두 문장
https://대표기사URL

2️⃣ 제목
내용 한두 문장
https://대표기사URL
```

규칙:

- `**`, `#`, 백틱 같은 마크다운 문법은 사용하지 않는다.
- `1.`, `2.` 대신 `1️⃣`, `2️⃣`, `🔟`을 사용한다.
- 각 항목 아래 URL만 단독 줄로 둔다. `기사 링크:` 라벨은 붙이지 않는다.
- 여러 기사를 묶은 항목도 대표 URL 하나만 둔다.
- 음성요약 URL은 본문 끝에 붙이지 않고 별도 메시지로 보낸다.

음성요약 링크 메시지는 아래 형식입니다.

```text
🎧2026년 5월 24일 병무청 뉴스 AI 음성요약 듣기
https://OWNER.github.io/REPO/
```

## 7. LLM CLI 구현 지시

Codex CLI 기준:

- `codex exec --ephemeral --ignore-user-config --ignore-rules --output-schema schema.json --output-last-message output.txt -`
- stdin으로 프롬프트를 전달한다.
- 출력은 반드시 JSON 객체로 제한한다.

Gemini CLI 기준:

- 같은 프롬프트와 JSON 스키마를 사용한다.
- Gemini CLI가 스키마 출력을 직접 지원하지 않으면 응답에서 JSON 객체만 추출하는 파서를 둔다.
- `llm_summarizer.py`에서 LLM 호출부를 provider adapter로 분리하면 Codex/Gemini 교체가 쉽다.

권장 인터페이스:

```python
class SummaryProvider:
    def summarize(prompt: str, schema: dict) -> dict:
        ...
```

필수 검증:

- `kakao_message`와 `tts_script`가 모두 문자열인지 검사
- JSON 파싱 실패 시 재시도
- 재시도 후에도 실패하면 폴백 메시지를 생성하되, 기사 URL은 가능한 한 유지

## 8. TTS와 음성요약 페이지

`edge-tts`를 사용해 `briefing.mp3`를 생성합니다.

권장 voice:

```text
ko-KR-SunHiNeural
```

`data.json`에는 최소 아래 필드를 저장합니다.

```json
{
  "archive_id": "20260524-071951",
  "date": "2026년 5월 24일",
  "kakao_message": "...",
  "player_url": "https://OWNER.github.io/REPO/",
  "kakao_link_message": "🎧2026년 5월 24일 병무청 뉴스 AI 음성요약 듣기\nhttps://OWNER.github.io/REPO/",
  "audio_src": "briefing.mp3",
  "audio_duration_seconds": 46.944,
  "tts_script": "...",
  "news_list": [],
  "updated_at": "2026-05-24 07:19:51 KST"
}
```

모바일에서 음성 길이가 `0:00`으로만 보이는 문제를 피하려면 `audio_duration_seconds`를 미리 계산해서 `data.json`에 넣습니다.

## 9. GitHub Pages 배포

`gh-pages` 브랜치에 아래 파일을 배포합니다.

```text
index.html
data.json
history.json
briefing.mp3
archive/
```

현재 방식처럼 Git worktree를 사용하면 main 브랜치와 Pages 산출물이 섞이지 않습니다.

배포 시 주의:

- `briefing.mp3`는 `.gitignore`에 걸릴 수 있으므로 `git add -f briefing.mp3`가 필요할 수 있다.
- 이전 브리핑 접근을 위해 `history.json`과 `archive/<archive_id>/data.json`, `archive/<archive_id>/briefing.mp3`를 유지한다.

## 10. PC 카카오톡 전송

PC 카카오톡 전송은 다음 조건이 필요합니다.

- Windows 데스크톱 세션이 살아 있어야 한다.
- PC 카카오톡이 로그인되어 있어야 한다.
- 전송 대상 방 이름이 정확해야 한다.
- self-hosted runner가 해당 사용자 세션에서 GUI 접근 가능해야 한다.

전송 방식:

1. 카카오톡 창을 찾는다.
2. 대상 대화방을 연다.
3. `RICHEDIT50W` 입력창을 찾는다.
4. 클립보드에 메시지를 넣고 붙여넣기한다.
5. Enter로 전송한다.

PC 카카오톡 방식에서는 긴 브리핑도 한 메시지로 보낼 수 있습니다. 음성요약 링크는 미리보기 생성을 위해 별도 메시지로 보냅니다.

## 11. 부정이슈 탐지 설계

검색 키워드 예시:

```text
병무청 논란
병무청 의혹
병무청 비리
병무청 수사
병무청 고발
병무청 감사
병무청 부실
병무청 소송
병무청 민원
병무청 개인정보
병역비리 병무청
병역기피 병무청
사회복무요원 병무청 논란
대체복무 병무청 논란
```

동작 방식:

- 최근 6시간 기사 검색
- 부정 키워드와 병무청 관련성으로 후보 선별
- LLM CLI로 실제 이슈인지 판단
- 최대 3개까지 알림
- `negative_issue_state.json`에 기록
- 8시간 이내 동일/유사 이슈는 재전송하지 않음

중복 판단 기준:

- 링크가 같으면 중복
- 정규화한 제목/내용이 서로 포함 관계면 중복
- `SequenceMatcher` 문자 유사도 기준값 이상이면 중복
- 핵심 토큰과 부정 이벤트 단어가 함께 겹치면 중복

부정이슈 카카오톡 메시지 예:

```text
🚨 병무청 부정이슈 탐지
제목: ...
내용: ...
판단: ...
원문 링크: ...
```

## 12. GitHub Actions 주의사항

Windows self-hosted runner 한 대에서는 workflow가 동시에 실행되지 못합니다. 아래를 반드시 적용합니다.

Daily briefing:

- 매일 오전 7시 KST
- GitHub Actions cron으로는 `0 22 * * *` UTC
- Cloud Scheduler로 repository_dispatch를 쏘는 경우 body는 `{"event_type":"trigger_daily_briefing"}`

Negative issue monitor:

- `timeout-minutes: 12`
- `concurrency.group` 지정
- Cloud Scheduler는 `5,20,35,50 * * * *` Asia/Seoul 권장
- 오전 7시 정각 브리핑과 충돌하지 않게 한다.

Git 인증 주의:

- workflow 내부 git pull/push가 Git Credential Manager 팝업을 기다리면 runner가 멈춘다.
- `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=Never`를 설정한다.
- `github.token`을 Basic Auth extraheader로 넣고 git 명령에는 `credential.helper=`와 `core.askPass=`를 비운다.
- 명령이 끝나면 extraheader를 제거한다.

## 13. Google Cloud Scheduler 설정

위치는 예시로 `asia-northeast3`를 사용합니다.

Daily briefing:

```text
name: daily-briefing-trigger
schedule: 0 7 * * *
timeZone: Asia/Seoul
target: POST https://api.github.com/repos/OWNER/REPO/dispatches
body: {"event_type":"trigger_daily_briefing"}
```

Negative issue monitor:

```text
name: negative-issue-monitor-trigger
schedule: 5,20,35,50 * * * *
timeZone: Asia/Seoul
target: POST https://api.github.com/repos/OWNER/REPO/dispatches
body: {"event_type":"trigger_negative_issue_scan"}
```

HTTP headers:

```text
Accept: application/vnd.github+json
Authorization: Bearer <GitHub token>
Content-Type: application/octet-stream
User-Agent: Google-Cloud-Scheduler
X-GitHub-Api-Version: 2022-11-28
```

절대 토큰이 터미널 출력이나 문서에 남지 않게 합니다.

## 14. 테스트 체크리스트

로컬 단위 테스트:

```powershell
python -m py_compile app.py app_local_sender.py llm_summarizer.py negative_issue_detector.py
python news_collector.py
python tts_generator.py
```

브리핑 생성 테스트:

```powershell
$env:GITHUB_REPOSITORY="OWNER/REPO"
$env:CODEX_TIMEOUT_SECONDS="600"
python app.py
```

검증:

- `data.json` 생성 여부
- `kakao_message`에 8~10개 항목이 있는지
- URL이 각 항목 아래 단독 줄로 있는지
- `kakao_link_message`가 제목과 URL 두 줄인지
- `briefing.mp3`가 생성됐는지
- `audio_duration_seconds`가 0보다 큰지

카카오톡 전송 테스트:

```powershell
python app_local_sender.py
```

GitHub Actions 테스트:

```powershell
gh workflow run daily_briefing.yml
gh run list --workflow daily_briefing.yml --limit 5
gh run view <run_id> --json status,conclusion,jobs
```

부정이슈 테스트:

```powershell
python negative_issue_detector.py --lookback-hours 6 --max-alerts 1 --max-candidates 5 --display-per-query 10
```

## 15. 장애 대응

7시 브리핑이 안 온 경우:

1. Cloud Scheduler 마지막 실행 시각 확인
2. GitHub Actions daily run이 생성됐는지 확인
3. run 상태가 `queued`면 self-hosted runner가 busy인지 확인
4. runner가 busy면 어떤 workflow가 잡고 있는지 확인
5. 부정이슈 workflow가 git auth에서 멈췄다면 해당 run 취소
6. runner가 풀리면 daily run이 이어서 실행되는지 확인
7. 카톡 전송 단계가 성공했는지 확인

카카오톡 전송 실패:

- PC 카카오톡 로그인 확인
- 대상 방 이름 확인
- Windows 세션 잠금 여부 확인
- `RICHEDIT50W` 입력창 탐색 로그 확인
- 수동으로 `python app_local_sender.py` 실행

링크 미리보기 실패:

- 브리핑 본문과 음성요약 주소를 분리 전송한다.
- 음성요약 주소 메시지 앞에 제목을 붙인다.

```text
🎧2026년 5월 24일 병무청 뉴스 AI 음성요약 듣기
https://OWNER.github.io/REPO/
```

## 16. Codex 또는 Gemini에게 줄 구현 지시문

새 환경에서 아래 지시문을 그대로 주고 시작해도 됩니다.

```text
이 저장소에 병무청 뉴스 AI 브리핑 시스템을 구현해줘.

목표는 두 가지야.
첫째, 매일 오전 7시 KST에 네이버 뉴스 API로 전날 병무청 관련 뉴스를 수집하고, Codex CLI 또는 Gemini CLI로 8~10개 항목의 카카오톡 요약과 TTS 대본을 생성해. 요약은 "📢 [오늘의 병무청 브리핑]"으로 시작하고, 번호는 1️⃣ 형식으로 쓰고, 각 항목 아래에는 대표 기사 URL만 한 줄로 넣어. 마크다운 굵게 표시나 "기사 링크:" 라벨은 쓰지 마. Edge TTS로 briefing.mp3를 만들고, data.json/history.json/archive를 생성해서 GitHub Pages에 배포해. 카카오톡 본문과 음성요약 링크 메시지는 별도로 PC 카카오톡 방에 보내.

둘째, 15분마다 병무청 관련 부정이슈를 탐지해. 네이버 뉴스에서 논란, 의혹, 비리, 수사, 고발, 감사, 부실, 소송, 민원, 개인정보, 병역비리, 병역기피 등의 검색어를 사용해 최근 6시간 기사를 찾고, LLM CLI로 실제 부정 이슈인지 판단해. 같은 이슈는 8시간 안에는 다시 보내지 않도록 negative_issue_state.json에 상태를 저장해. 알림은 PC 카카오톡으로 한 메시지로 보내.

아키텍처는 Google Cloud Scheduler -> GitHub repository_dispatch -> GitHub Actions -> Windows self-hosted runner -> Python scripts -> GitHub Pages 및 PC 카카오톡 전송이야. GitHub-hosted runner가 아니라 로컬 Windows self-hosted runner를 사용해야 해.

필수 파일은 app.py, news_collector.py, llm_summarizer.py, tts_generator.py, index.html, app_local_sender.py, kakaotalk_sender.py, negative_issue_detector.py, .github/workflows/daily_briefing.yml, .github/workflows/negative_issue_monitor.yml이야.

GitHub Secrets는 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, KAKAOTALK_ROOM_NAME을 사용해. 토큰이나 키는 코드와 로그에 남기지 마.

Daily workflow는 repository_dispatch trigger_daily_briefing과 workflow_dispatch를 지원해. Negative workflow는 trigger_negative_issue_scan과 workflow_dispatch를 지원하고, timeout-minutes 12를 넣어. Negative Scheduler는 5,20,35,50분으로 돌려서 오전 7시 브리핑과 충돌하지 않게 해.

workflow 안에서 git pull/push를 할 때 Git Credential Manager 팝업으로 멈추지 않도록 GIT_TERMINAL_PROMPT=0, GCM_INTERACTIVE=Never, github.token 기반 extraheader 인증을 사용해.

구현 후 python -m py_compile, 로컬 app.py 생성 테스트, app_local_sender.py 카톡 전송 테스트, GitHub Actions 수동 실행 테스트까지 해줘.
```

## 17. 운영상 가장 중요한 교훈

- 스케줄이 성공해도 GitHub Actions가 `queued`면 runner가 막힌 것이다.
- self-hosted runner 한 대에서는 15분 작업과 7시 작업이 충돌할 수 있다.
- Git Credential Manager 팝업 대기는 자동화의 적이다.
- 카카오톡 전송은 로컬 GUI 의존성이 있으므로 PC 카카오톡과 Windows 세션 상태를 항상 확인해야 한다.
- 링크 미리보기를 위해 음성요약 주소는 본문과 분리하고 제목을 붙여 보낸다.
- `data.json`에 오디오 길이를 저장하면 모바일에서 0:00 표시 문제를 줄일 수 있다.
