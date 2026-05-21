import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime

import requests
from requests import HTTPError

from playmcp_sender import send_playmcp_memo


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


KST = timezone(timedelta(hours=9))
DEFAULT_STATE_FILE = "negative_issue_state.json"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_ANALYZER = "codex"
DEFAULT_QUERIES = [
    "병무청 논란",
    "병무청 의혹",
    "병무청 비리",
    "병무청 수사",
    "병무청 고발",
    "병무청 감사",
    "병무청 부실",
    "병무청 소송",
    "병무청 민원",
    "병무청 개인정보",
    "병역비리 병무청",
    "병역기피 병무청",
    "사회복무요원 병무청 논란",
    "대체복무 병무청 논란",
]
AGENCY_TERMS = [
    "병무청",
    "지방병무청",
    "병무",
    "병역",
    "사회복무요원",
    "대체복무",
    "대체역",
]
NEGATIVE_TERMS = {
    "논란": 2,
    "의혹": 2,
    "비리": 3,
    "수사": 2,
    "고발": 3,
    "감사": 2,
    "징계": 2,
    "처벌": 2,
    "적발": 3,
    "구속": 3,
    "불법": 3,
    "부정": 2,
    "부실": 2,
    "오류": 2,
    "실수": 1,
    "민원": 1,
    "소송": 2,
    "패소": 3,
    "위법": 3,
    "기피": 2,
    "병역기피": 3,
    "입국금지": 2,
    "거부": 1,
    "반발": 1,
    "비판": 2,
    "차별": 2,
    "인권위": 2,
    "폭행": 3,
    "괴롭힘": 3,
    "사망": 3,
    "자살": 3,
    "갑질": 3,
    "성추행": 3,
    "개인정보": 2,
    "유출": 3,
    "채용비리": 3,
}
POSITIVE_ROUTINE_TERMS = [
    "설명회",
    "협약",
    "홍보",
    "격려",
    "방문",
    "봉사",
    "할인",
    "혜택",
    "챌린지",
    "상담",
]


def load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def now_kst():
    return datetime.now(KST)


def clean_text(value):
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_match(value):
    text = clean_text(value).lower()
    text = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    return text


def issue_tokens(value):
    tokens = re.findall(r"[가-힣A-Za-z0-9]{2,}", clean_text(value).lower())
    stopwords = {
        "병무청",
        "법무부",
        "관련",
        "기사",
        "논란",
        "의혹",
        "소송",
        "항소심",
        "재개",
        "시작",
        "대상",
        "제공",
        "밝혔다",
        "대한",
        "이번",
    }
    return {token for token in tokens if token not in stopwords}


def is_same_issue_text(left, right):
    left_norm = normalize_for_match(left)
    right_norm = normalize_for_match(right)
    if not left_norm or not right_norm:
        return False
    if left_norm in right_norm or right_norm in left_norm:
        return True

    left_tokens = issue_tokens(left)
    right_tokens = issue_tokens(right)
    shared_tokens = left_tokens & right_tokens
    similarity = SequenceMatcher(None, left_norm, right_norm).ratio()
    shared_event_terms = [
        term
        for term in NEGATIVE_TERMS
        if normalize_for_match(term) in left_norm and normalize_for_match(term) in right_norm
    ]
    high_signal_shared = [
        token
        for token in shared_tokens
        if len(token) >= 3 and token not in {"병무청", "법무부", "사회복무요원", "대체복무", "병역기피"}
    ]
    if high_signal_shared and shared_event_terms:
        return True
    return len(shared_tokens) >= 2 and similarity >= 0.35


def clip(value, limit):
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def issue_hash(*parts):
    joined = "\n".join(part or "" for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


class RecentNaverNewsFetcher:
    def __init__(self, client_id=None, client_secret=None):
        self.client_id = client_id or os.environ.get("NAVER_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("NAVER_CLIENT_SECRET")
        self.api_url = "https://openapi.naver.com/v1/search/news.json"

    def fetch_recent(self, queries, lookback_hours, display_per_query):
        if not self.client_id or not self.client_secret:
            raise RuntimeError("NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET 환경 변수가 없습니다.")

        since = now_kst() - timedelta(hours=lookback_hours)
        deduped = {}
        for query in queries:
            for item in self._request(query, display_per_query):
                normalized = self._normalize_item(item, query)
                if not normalized:
                    continue
                if normalized["published_at_dt"] < since:
                    continue
                if not self._is_agency_related(normalized):
                    continue
                key = normalized.get("originallink") or normalized.get("link") or normalize_for_match(
                    normalized["title"] + normalized["description"]
                )
                deduped.setdefault(key, normalized)
            time.sleep(float(os.environ.get("NAVER_SEARCH_DELAY_SECONDS", "0.35")))

        items = sorted(deduped.values(), key=lambda item: item["published_at_dt"], reverse=True)
        for item in items:
            item.pop("published_at_dt", None)
        return items

    def _request(self, query, display):
        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }
        params = {
            "query": query,
            "display": min(display, 100),
            "start": 1,
            "sort": "date",
        }
        data = None
        for attempt in range(1, 3):
            try:
                response = requests.get(self.api_url, headers=headers, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                break
            except HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status == 429 and attempt == 1:
                    wait_sec = float(os.environ.get("NAVER_429_RETRY_SECONDS", "3"))
                    print(f"[경고] 네이버 API 호출 제한 감지. {wait_sec}초 후 재시도합니다: {query}", file=sys.stderr)
                    time.sleep(wait_sec)
                    continue
                print(f"[경고] 네이버 API 호출 실패로 검색어를 건너뜁니다 ({query}): {exc}", file=sys.stderr)
                return []
            except Exception as exc:
                print(f"[경고] 네이버 API 호출 실패로 검색어를 건너뜁니다 ({query}): {exc}", file=sys.stderr)
                return []

        if data is None:
            return []
        print(f"[정보] '{query}' 검색 결과 {len(data.get('items', []))}개 수신")
        return data.get("items", [])

    def _normalize_item(self, item, query):
        pub_date_str = item.get("pubDate")
        if not pub_date_str:
            return None
        try:
            published_at = parsedate_to_datetime(pub_date_str).astimezone(KST)
        except Exception as exc:
            print(f"[경고] pubDate 파싱 실패: {pub_date_str} ({exc})", file=sys.stderr)
            return None

        title = clean_text(item.get("title"))
        description = clean_text(item.get("description"))
        if not title:
            return None

        return {
            "query": query,
            "title": title,
            "description": description,
            "originallink": item.get("originallink"),
            "link": item.get("link") or item.get("originallink"),
            "pubDate": published_at.strftime("%Y-%m-%d %H:%M:%S"),
            "published_at_dt": published_at,
        }

    def _is_agency_related(self, item):
        text = normalize_for_match(item["title"] + " " + item["description"])
        return any(normalize_for_match(term) in text for term in AGENCY_TERMS)


def score_negative_candidate(item):
    text = normalize_for_match(item["title"] + " " + item["description"])
    score = 0
    matched_terms = []
    for term, weight in NEGATIVE_TERMS.items():
        if normalize_for_match(term) in text:
            score += weight
            matched_terms.append(term)

    if score and any(normalize_for_match(term) in text for term in POSITIVE_ROUTINE_TERMS):
        score -= 1
    return max(score, 0), matched_terms


def load_state(path):
    if not os.path.exists(path):
        return {"version": 1, "sent_issues": []}
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        return {"version": 1, "sent_issues": []}
    data.setdefault("version", 1)
    data.setdefault("sent_issues", [])
    return data


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def prune_state(state, suppress_hours):
    cutoff = now_kst() - timedelta(hours=suppress_hours)
    kept = []
    for issue in state.get("sent_issues", []):
        sent_at = parse_iso(issue.get("sent_at"))
        if sent_at and sent_at >= cutoff:
            kept.append(issue)
    changed = len(kept) != len(state.get("sent_issues", []))
    state["sent_issues"] = kept
    return changed


def build_openai_prompt(candidates, recent_sent):
    candidate_payload = []
    for index, item in enumerate(candidates, 1):
        candidate_payload.append(
            {
                "source_index": index,
                "query": item.get("query"),
                "title": item.get("title"),
                "description": item.get("description"),
                "published_at": item.get("pubDate"),
                "link": item.get("link"),
                "rule_score": item.get("rule_score", 0),
                "matched_terms": item.get("matched_terms", []),
            }
        )

    sent_payload = [
        {
            "id": issue.get("id"),
            "issue_title": issue.get("issue_title"),
            "issue_summary": issue.get("issue_summary"),
            "source_title": issue.get("source_title"),
            "sent_at": issue.get("sent_at"),
        }
        for issue in recent_sent
    ]

    return f"""
JSON만 반환하세요.

당신은 한국 공공기관 뉴스의 부정 이슈 모니터링 분석가입니다.
아래 후보 기사들이 병무청, 병역행정, 사회복무요원, 대체복무와 관련된 부정 이슈인지 판별하세요.

부정 이슈 예:
- 비리, 의혹, 부정, 수사, 고발, 감사, 징계, 처벌, 위법, 패소, 부실행정, 개인정보 유출
- 병역기피 논란, 병무청 조치에 대한 소송이나 비판, 사회복무요원 인권·사고·괴롭힘 이슈
- 병역행정 신뢰를 훼손할 수 있는 민원, 오류, 논란

제외할 것:
- 단순 설명회, 협약, 홍보, 방문, 격려, 할인 혜택, 봉사활동 같은 통상·긍정 기사
- 병무청이 단순히 부스 참여 기관으로 언급된 기사
- 병무청과 직접 관련성이 약한 일반 군·국방 기사

중복 판별:
- 제목만 보지 말고 설명 내용까지 보고 같은 사건인지 판단하세요.
- 최근 8시간 안에 이미 보낸 이슈와 같은 사건이면 duplicate_of_sent_issue_id에 해당 id를 넣으세요.
- 같은 후보 기사끼리 같은 사건이면 같은 issue_key를 쓰세요.

[최근 8시간 전송 이슈]
{json.dumps(sent_payload, ensure_ascii=False)}

[후보 기사]
{json.dumps(candidate_payload, ensure_ascii=False)}

다음 JSON 형식으로만 답하세요.
{{
  "analysis": [
    {{
      "source_index": 1,
      "is_negative": true,
      "alert_recommended": true,
      "severity": "low|medium|high|critical",
      "issue_key": "같은 사건을 묶는 짧은 한국어 키",
      "issue_title": "카카오톡에 보낼 짧은 제목",
      "issue_summary": "핵심 내용 1문장",
      "negative_reason": "부정 이슈로 본 이유",
      "duplicate_of_sent_issue_id": null
    }}
  ]
}}
"""


def call_openai_json(prompt):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    model = os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    payload = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "당신은 JSON만 출력하는 한국어 뉴스 리스크 분석가입니다.",
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 1800,
    }
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def output_schema():
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["analysis"],
        "properties": {
            "analysis": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "source_index",
                        "is_negative",
                        "alert_recommended",
                        "severity",
                        "issue_key",
                        "issue_title",
                        "issue_summary",
                        "negative_reason",
                        "duplicate_of_sent_issue_id",
                    ],
                    "properties": {
                        "source_index": {"type": "integer"},
                        "is_negative": {"type": "boolean"},
                        "alert_recommended": {"type": "boolean"},
                        "severity": {
                            "type": "string",
                            "enum": ["low", "medium", "high", "critical"],
                        },
                        "issue_key": {"type": "string"},
                        "issue_title": {"type": "string"},
                        "issue_summary": {"type": "string"},
                        "negative_reason": {"type": "string"},
                        "duplicate_of_sent_issue_id": {
                            "anyOf": [{"type": "string"}, {"type": "null"}]
                        },
                    },
                },
            }
        },
    }


def resolve_codex_command():
    configured = os.environ.get("CODEX_COMMAND")
    if configured:
        return configured

    for candidate in ("codex", "codex.cmd", "codex.exe", "codex.bat"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    raise FileNotFoundError("codex CLI 실행 파일을 찾을 수 없습니다.")


def parse_json_output(raw_output):
    cleaned = (raw_output or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def call_codex_json(prompt):
    timeout_sec = int(os.environ.get("CODEX_TIMEOUT_SECONDS", "600"))
    model = os.environ.get("CODEX_MODEL")

    with tempfile.TemporaryDirectory() as temp_dir:
        schema_path = os.path.join(temp_dir, "negative_issue_schema.json")
        output_path = os.path.join(temp_dir, "codex_negative_issue_response.txt")
        with open(schema_path, "w", encoding="utf-8") as file:
            json.dump(output_schema(), file, ensure_ascii=False, indent=2)

        command = [
            resolve_codex_command(),
            "-a",
            "never",
            "-s",
            "read-only",
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--output-schema",
            schema_path,
            "--output-last-message",
            output_path,
        ]
        if model:
            command.extend(["--model", model])
        command.append("-")

        completed = subprocess.run(
            command,
            input=prompt,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=timeout_sec,
            check=False,
        )
        if completed.returncode != 0:
            stderr_tail = (completed.stderr or "")[-2000:].strip()
            raise RuntimeError(f"codex exec 종료 코드 {completed.returncode}: {stderr_tail}")

        raw_output = ""
        if os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8") as file:
                raw_output = file.read().strip()
        if not raw_output:
            raw_output = completed.stdout.strip()

        return parse_json_output(raw_output)


def fallback_analysis(candidates, recent_sent):
    analysis = []
    for index, item in enumerate(candidates, 1):
        score = item.get("rule_score", 0)
        is_negative = score >= 2
        issue_title = clip(item["title"], 70)
        issue_summary = clip(item.get("description") or item["title"], 120)
        duplicate_id = find_duplicate_sent(
            {"issue_title": issue_title, "issue_summary": issue_summary, "source": item},
            recent_sent,
        )
        analysis.append(
            {
                "source_index": index,
                "is_negative": is_negative,
                "alert_recommended": is_negative and not duplicate_id,
                "severity": "high" if score >= 5 else "medium" if score >= 3 else "low",
                "issue_key": normalize_for_match(issue_title)[:50],
                "issue_title": issue_title,
                "issue_summary": issue_summary,
                "negative_reason": "규칙 기반 탐지: " + ", ".join(item.get("matched_terms", [])),
                "duplicate_of_sent_issue_id": duplicate_id,
            }
        )
    return {"analysis": analysis}


def find_duplicate_sent(alert, recent_sent):
    alert_text = normalize_for_match(
        f"{alert.get('issue_title', '')} {alert.get('issue_summary', '')} "
        f"{alert.get('source', {}).get('title', '')} {alert.get('source', {}).get('description', '')}"
    )
    alert_link = (alert.get("source") or {}).get("link")

    for sent in recent_sent:
        if alert_link and alert_link in sent.get("links", []):
            return sent.get("id")

        sent_text = normalize_for_match(
            f"{sent.get('issue_title', '')} {sent.get('issue_summary', '')} {sent.get('source_title', '')}"
        )
        if not alert_text or not sent_text:
            continue
        if alert_text in sent_text or sent_text in alert_text:
            return sent.get("id")
        if SequenceMatcher(None, alert_text, sent_text).ratio() >= 0.72:
            return sent.get("id")
        if is_same_issue_text(alert_text, sent_text):
            return sent.get("id")
    return None


def prepare_candidates(items, max_candidates):
    prepared = []
    for item in items:
        score, matched_terms = score_negative_candidate(item)
        if score <= 0:
            continue
        enriched = dict(item)
        enriched["rule_score"] = score
        enriched["matched_terms"] = matched_terms
        prepared.append(enriched)

    prepared.sort(key=lambda item: (item["rule_score"], item["pubDate"]), reverse=True)
    return prepared[:max_candidates]


def select_alerts(candidates, analysis_payload, recent_sent, max_alerts):
    by_index = {}
    for entry in analysis_payload.get("analysis", []):
        try:
            by_index[int(entry.get("source_index"))] = entry
        except Exception:
            continue

    alerts = []
    seen_keys = set()
    seen_issue_texts = []
    for index, item in enumerate(candidates, 1):
        entry = by_index.get(index)
        if not entry:
            continue
        if not entry.get("is_negative") or not entry.get("alert_recommended"):
            continue
        if entry.get("duplicate_of_sent_issue_id"):
            continue

        alert = {
            "issue_key": entry.get("issue_key") or normalize_for_match(item["title"])[:50],
            "issue_title": clip(entry.get("issue_title") or item["title"], 80),
            "issue_summary": clip(entry.get("issue_summary") or item.get("description"), 170),
            "negative_reason": clip(entry.get("negative_reason") or "", 120),
            "severity": entry.get("severity") or "medium",
            "source": item,
        }
        duplicate_id = find_duplicate_sent(alert, recent_sent)
        if duplicate_id:
            print(f"[정보] 최근 전송 이슈와 중복으로 제외: {alert['issue_title']} ({duplicate_id})")
            continue

        run_key = normalize_for_match(alert["issue_key"] + alert["issue_title"] + alert["issue_summary"])
        if any(SequenceMatcher(None, run_key, existing).ratio() >= 0.78 for existing in seen_keys):
            print(f"[정보] 이번 실행 내 중복으로 제외: {alert['issue_title']}")
            continue
        issue_text = f"{alert['issue_title']} {alert['issue_summary']} {item.get('title', '')} {item.get('description', '')}"
        if any(is_same_issue_text(issue_text, existing) for existing in seen_issue_texts):
            print(f"[정보] 이번 실행 내 같은 사건으로 제외: {alert['issue_title']}")
            continue

        seen_keys.add(run_key)
        seen_issue_texts.append(issue_text)
        alerts.append(alert)
        if len(alerts) >= max_alerts:
            break
    return alerts


def build_alert_messages(alert):
    source = alert["source"]
    link = source.get("link") or source.get("originallink") or ""
    messages = [
        f"🚨 병무청 부정이슈 탐지 | {alert['issue_title']}",
        f"내용: {alert['issue_summary']} | 판단: {alert['negative_reason']}",
    ]
    if link:
        messages.append(f"원문 링크: {link}")
    return [clip(message, 900) for message in messages]


def send_alert(alert, send_mode):
    messages = build_alert_messages(alert)
    if send_mode == "none":
        for message in messages:
            print(f"[DRY-RUN] {message}")
        return True
    if send_mode != "playmcp":
        raise ValueError(f"지원하지 않는 전송 모드입니다: {send_mode}")

    for message in messages:
        result = send_playmcp_memo(message)
        print(f"[정보] PlayMCP 전송 성공: {result}")
        time.sleep(0.8)
    return True


def append_sent_issue(state, alert, suppress_hours):
    source = alert["source"]
    sent_at = now_kst()
    record_id = issue_hash(alert["issue_key"], alert["issue_title"], alert["issue_summary"])
    link = source.get("link") or source.get("originallink")
    state.setdefault("sent_issues", []).append(
        {
            "id": record_id,
            "issue_key": alert["issue_key"],
            "issue_title": alert["issue_title"],
            "issue_summary": alert["issue_summary"],
            "negative_reason": alert["negative_reason"],
            "severity": alert["severity"],
            "source_title": source.get("title"),
            "source_description": source.get("description"),
            "links": [link] if link else [],
            "sent_at": sent_at.isoformat(),
            "expires_at": (sent_at + timedelta(hours=suppress_hours)).isoformat(),
        }
    )


def save_state(path, state):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
        file.write("\n")


def parse_queries(value):
    if not value:
        return DEFAULT_QUERIES
    return [query.strip() for query in value.split("|") if query.strip()]


def run(args):
    analyzer = os.environ.get("NEGATIVE_ISSUE_ANALYZER", DEFAULT_ANALYZER).strip().lower()
    if (
        args.send_mode != "none"
        and analyzer == "rule"
        and os.environ.get("ALLOW_RULE_BASED_ALERTS", "").lower() not in {"1", "true", "yes"}
    ):
        raise RuntimeError(
            "자동 카카오톡 전송에는 Codex CLI 또는 OpenAI API 분석이 필요합니다. "
            "규칙 기반 알림만 보내려면 ALLOW_RULE_BASED_ALERTS=true를 설정하세요."
        )

    state = load_state(args.state_file)
    state_changed = prune_state(state, args.suppress_hours)
    recent_sent = state.get("sent_issues", [])

    queries = parse_queries(os.environ.get("NEGATIVE_SEARCH_QUERIES"))
    print(f"[정보] 최근 {args.lookback_hours}시간 기준 부정이슈 검색을 시작합니다.")
    print(f"[정보] 검색어 {len(queries)}개: {', '.join(queries)}")

    fetcher = RecentNaverNewsFetcher()
    recent_items = fetcher.fetch_recent(queries, args.lookback_hours, args.display_per_query)
    candidates = prepare_candidates(recent_items, args.max_candidates)
    print(f"[정보] 최근 기사 {len(recent_items)}개 중 부정 후보 {len(candidates)}개")

    if not candidates:
        if state_changed:
            save_state(args.state_file, state)
        print("[정보] 전송할 부정이슈가 없습니다.")
        return 0

    analysis_payload = None
    analysis_prompt = build_openai_prompt(candidates, recent_sent)
    if analyzer == "codex":
        try:
            analysis_payload = call_codex_json(analysis_prompt)
            print("[정보] Codex CLI 분석 완료")
        except Exception as exc:
            if args.send_mode == "none" or os.environ.get("ALLOW_RULE_BASED_ALERTS", "").lower() in {"1", "true", "yes"}:
                print(f"[경고] Codex CLI 분석 실패. 규칙 기반 판별로 대체합니다: {exc}", file=sys.stderr)
            else:
                raise
    elif analyzer == "openai":
        try:
            analysis_payload = call_openai_json(analysis_prompt)
            print("[정보] OpenAI API 분석 완료")
        except Exception as exc:
            if args.send_mode == "none" or os.environ.get("ALLOW_RULE_BASED_ALERTS", "").lower() in {"1", "true", "yes"}:
                print(f"[경고] OpenAI API 분석 실패. 규칙 기반 판별로 대체합니다: {exc}", file=sys.stderr)
            else:
                raise
    elif analyzer == "rule":
        print("[정보] 규칙 기반 분석 모드를 사용합니다.")
    else:
        raise ValueError(f"지원하지 않는 분석 모드입니다: {analyzer}")

    analysis_payload = analysis_payload or fallback_analysis(candidates, recent_sent)
    alerts = select_alerts(candidates, analysis_payload, recent_sent, args.max_alerts)
    print(f"[정보] 전송 대상 부정이슈 {len(alerts)}개")

    for alert in alerts:
        print(f"[정보] 전송: {alert['issue_title']}")
        send_alert(alert, args.send_mode)
        if args.send_mode != "none":
            append_sent_issue(state, alert, args.suppress_hours)
            state_changed = True

    if state_changed:
        save_state(args.state_file, state)
        print(f"[정보] 상태 파일 저장 완료: {args.state_file}")
    return 0


def build_arg_parser():
    parser = argparse.ArgumentParser(description="병무청 관련 부정이슈를 탐지하고 카카오톡 알림을 보냅니다.")
    parser.add_argument("--state-file", default=os.environ.get("NEGATIVE_STATE_FILE", DEFAULT_STATE_FILE))
    parser.add_argument("--lookback-hours", type=float, default=float(os.environ.get("NEGATIVE_LOOKBACK_HOURS", "6")))
    parser.add_argument("--suppress-hours", type=float, default=float(os.environ.get("NEGATIVE_SUPPRESS_HOURS", "8")))
    parser.add_argument("--display-per-query", type=int, default=int(os.environ.get("NEGATIVE_DISPLAY_PER_QUERY", "30")))
    parser.add_argument("--max-candidates", type=int, default=int(os.environ.get("NEGATIVE_MAX_CANDIDATES", "20")))
    parser.add_argument("--max-alerts", type=int, default=int(os.environ.get("NEGATIVE_MAX_ALERTS", "3")))
    parser.add_argument(
        "--send-mode",
        choices=["none", "playmcp"],
        default=os.environ.get("NEGATIVE_ALERT_SEND_MODE", "none"),
    )
    return parser


if __name__ == "__main__":
    load_dotenv()
    raise SystemExit(run(build_arg_parser().parse_args()))
