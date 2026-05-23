import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from difflib import SequenceMatcher


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


class LLMSummarizer:
    def __init__(self, codex_command=None, model=None, timeout_sec=None):
        self.codex_command = self._resolve_codex_command(codex_command or os.environ.get("CODEX_COMMAND", "codex"))
        self.model = model or os.environ.get("CODEX_MODEL")
        self.timeout_sec = int(timeout_sec or os.environ.get("CODEX_TIMEOUT_SECONDS", "300"))

    def summarize_news(self, news_items):
        """
        수집된 뉴스 아이템 리스트를 받아
        1. PC 카카오톡 텍스트 메시지용 요약문
        2. TTS(음성) 낭독용 스크립트
        두 가지를 생성하여 반환합니다.
        """
        if not news_items:
            no_news_message = (
                "안녕하십니까. 병무청 관련 아침 브리핑입니다. "
                "어제 하루 동안 새로 확인된 주요 병무청 관련 뉴스는 없습니다. "
                "오늘도 평온하고 건강한 하루 보내시기 바랍니다. 감사합니다."
            )
            return {
                "kakao_message": (
                    "📢 [오늘의 병무청 브리핑]\n\n"
                    "어제 하루 동안 새로 확인된 주요 병무청 관련 뉴스가 없습니다.\n"
                    "오늘도 평온하고 건강한 하루 되세요!"
                ),
                "tts_script": no_news_message,
            }

        news_input = self._format_news_items(news_items)
        prompt = f"""
당신은 한국어 뉴스 브리핑 작가입니다.
아래 뉴스 목록은 '대체역심사위원회', '양심적병역거부', '여호와의증인', '대체복무', '병무청' 키워드로 전날 수집한 기사입니다.
기사 제목과 설명에 있는 사실만 사용하고, 추측이나 과장은 하지 마세요.

[분석할 뉴스 데이터]
{news_input}

[작성 규칙]
1. kakao_message
- 단톡방에서 아침에 빠르게 읽을 수 있게 핵심 이슈를 가능한 한 10개 항목으로 정리하세요.
- 수집된 뉴스가 너무 적거나 서로 중복되면 8~10개 항목으로 정리하세요.
- 각 항목은 제목 한 줄과 설명 한두 문장으로 쓰세요.
- 각 항목 바로 아래에는 반드시 "기사 링크: URL" 형식으로 해당 내용을 대표하는 기사 링크 1개를 넣으세요.
- 여러 기사를 묶은 항목이라도 가장 대표적인 기사 링크 1개만 넣고, URL은 위 뉴스 데이터의 "링크" 값에서 그대로 복사하세요.
- 친절하지만 과장 없는 한국어 문체를 사용하세요.
- 첫 줄은 "📢 [오늘의 병무청 브리핑]"로 시작하세요.
- 항목 번호는 반드시 "1️⃣", "2️⃣", "3️⃣" 같은 숫자 이모티콘을 사용하세요. "1.", "2.", "1)" 형식은 쓰지 마세요.
- 마크다운 굵게 표시나 기호를 쓰지 마세요. 특히 "**", "__", "#", "`" 문자는 절대 쓰지 마세요.
- 음성 브리핑 링크 문장은 쓰지 마세요. 시스템이 플레이어 주소를 별도 카카오톡 메시지로 보냅니다.

2. tts_script
- 아침 라디오 브리핑처럼 차분한 한국어 낭독문으로 쓰세요.
- 마크다운 기호, URL, 괄호, 슬래시, 표, 목록 기호는 넣지 마세요.
- 영어 약자와 숫자는 가능한 한 한국어로 자연스럽게 풀어 쓰세요.
- 전체 길이는 공백 포함 400~600자 안팎으로 맞추세요.

[출력 형식]
아래 JSON 객체만 반환하세요. 설명, 코드블록, 주석은 절대 붙이지 마세요.
{{
  "kakao_message": "카카오톡 메시지 내용",
  "tts_script": "TTS 낭독용 한국어 대본"
}}
"""

        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                print(f"[정보] Codex CLI 요약 요청 중... (시도 {attempt}/{max_retries})")
                result = self._run_codex_json(prompt)
                self._validate_result(result)
                result["kakao_message"] = self._normalize_kakao_message(result["kakao_message"])
                result["kakao_message"] = self._ensure_article_links(result["kakao_message"], news_items)
                print(f"[정보] Codex CLI 요약 성공! (시도 {attempt}회)")
                return result
            except Exception as e:
                print(f"[경고] Codex CLI 요약 실패 (시도 {attempt}/{max_retries}): {e}", file=sys.stderr)
                if attempt < max_retries:
                    wait_sec = 2 ** attempt
                    print(f"[정보] {wait_sec}초 후 재시도합니다...")
                    time.sleep(wait_sec)

        print("[오류] Codex CLI 최대 재시도 횟수 초과. 폴백 메시지를 사용합니다.", file=sys.stderr)
        return self._fallback_result(news_items)

    def _fallback_result(self, news_items):
        selected = news_items[:10]
        lines = ["📢 [오늘의 병무청 브리핑]", ""]
        number_emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

        for index, item in enumerate(selected):
            title = item.get("title", "").strip() or "병무청 관련 소식"
            description = item.get("description", "").strip()
            link = self._item_link(item)
            lines.append(f"{number_emoji[index]} {title}")
            if description:
                lines.append(self._clip_text(description, 110))
            if link:
                lines.append(f"기사 링크: {link}")
            lines.append("")

        if not selected:
            lines.append("뉴스 요약 중 오류가 발생했습니다. 플레이어 링크를 참고해 주세요.")

        title_summary = " ".join(
            item.get("title", "").strip()
            for item in selected[:5]
            if item.get("title", "").strip()
        )
        tts_script = (
            "안녕하세요. 오늘 아침 병무청 뉴스 브리핑입니다. "
            "요약 시스템에 일시적인 지연이 있어 주요 기사 제목 중심으로 안내드립니다. "
            f"{title_summary}"
        ).strip()

        return {
            "kakao_message": "\n".join(lines).strip(),
            "tts_script": tts_script or (
                "안녕하세요. 오늘 아침 병무청 뉴스 브리핑 시스템에 일시적인 지연이 발생했습니다. "
                "대단히 죄송합니다. 잠시 후 다시 실행해 주시기 바랍니다. 감사합니다."
            ),
        }

    def _format_news_items(self, news_items):
        lines = []
        for idx, item in enumerate(news_items, 1):
            title = item.get("title", "").strip()
            description = item.get("description", "").strip()
            pub_date = item.get("pubDate", "").strip()
            link = item.get("link") or item.get("originallink") or ""
            lines.append(
                f"[{idx}]\n"
                f"제목: {title}\n"
                f"일시: {pub_date}\n"
                f"설명: {description}\n"
                f"링크: {link}\n"
            )
        return "\n".join(lines)

    def _run_codex_json(self, prompt):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "codex_response.txt")
            schema_path = os.path.join(temp_dir, "summary_schema.json")
            with open(schema_path, "w", encoding="utf-8") as f:
                json.dump(self._output_schema(), f, ensure_ascii=False, indent=2)

            command = [
                self.codex_command,
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
            if self.model:
                command.extend(["--model", self.model])
            command.append("-")

            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_sec,
                check=False,
            )

            if completed.returncode != 0:
                stderr_tail = completed.stderr[-2000:].strip()
                raise RuntimeError(f"codex exec 종료 코드 {completed.returncode}: {stderr_tail}")

            raw_output = ""
            if os.path.exists(output_path):
                with open(output_path, "r", encoding="utf-8") as f:
                    raw_output = f.read().strip()
            if not raw_output:
                raw_output = completed.stdout.strip()

            return self._parse_json(raw_output)

    def _parse_json(self, raw_output):
        cleaned = raw_output.strip()
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

    def _validate_result(self, result):
        if not isinstance(result, dict):
            raise ValueError("Codex 응답이 JSON 객체가 아닙니다.")
        for key in ("kakao_message", "tts_script"):
            if not isinstance(result.get(key), str) or not result[key].strip():
                raise ValueError(f"Codex 응답에 유효한 {key} 값이 없습니다.")

    def _normalize_kakao_message(self, message):
        """카카오톡용 메시지에서 마크다운과 일반 숫자 목록을 제거합니다."""
        number_emoji = {
            "1": "1️⃣",
            "2": "2️⃣",
            "3": "3️⃣",
            "4": "4️⃣",
            "5": "5️⃣",
            "6": "6️⃣",
            "7": "7️⃣",
            "8": "8️⃣",
            "9": "9️⃣",
            "10": "🔟",
        }

        normalized = message
        for marker in ("**", "__", "`", "###", "##", "#"):
            normalized = normalized.replace(marker, "")

        def replace_number(match):
            indent, number = match.groups()
            return f"{indent}{number_emoji.get(number, number + '️⃣')} "

        normalized = re.sub(r"(?m)^(\s*)(10|[1-9])[\.\)]\s+", replace_number, normalized)
        normalized = re.sub(r"(?m)^(\s*)[-*]\s+", r"\1", normalized)
        return normalized.strip()

    def _ensure_article_links(self, message, news_items):
        """각 번호 항목 아래에 대표 기사 링크 한 개를 붙입니다."""
        if not news_items:
            return message.strip()

        item_blocks = self._split_numbered_blocks(message)
        if not item_blocks:
            return message.strip()

        rebuilt = []
        used_links = set()
        for kind, block in item_blocks:
            if kind == "preamble":
                if block.strip():
                    rebuilt.append(block.strip())
                continue

            existing_link = self._first_link(block)
            block_without_links = self._remove_link_lines(block)
            link = existing_link or self._representative_link(block_without_links, news_items, used_links)
            if link:
                rebuilt.append(f"{block_without_links.rstrip()}\n기사 링크: {link}".strip())
                used_links.add(link)
            else:
                rebuilt.append(block_without_links.strip())

        return "\n\n".join(part for part in rebuilt if part).strip()

    def _split_numbered_blocks(self, message):
        markers = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")
        blocks = []
        current = []
        current_kind = "preamble"

        for line in message.splitlines():
            stripped = line.lstrip()
            if any(stripped.startswith(marker) for marker in markers):
                if current:
                    blocks.append((current_kind, "\n".join(current).strip()))
                current = [line]
                current_kind = "item"
            else:
                current.append(line)

        if current:
            blocks.append((current_kind, "\n".join(current).strip()))
        return blocks

    def _remove_link_lines(self, block):
        lines = []
        for line in block.splitlines():
            stripped = line.strip()
            if re.match(r"^(?:기사\s*)?링크\s*:", stripped):
                continue
            if re.fullmatch(r"https?://\S+", stripped):
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def _first_link(self, block):
        match = re.search(r"https?://\S+", block or "")
        if not match:
            return ""
        return match.group(0).rstrip(".,;)")

    def _representative_link(self, block, news_items, used_links=None):
        used_links = used_links or set()
        best_item = None
        best_score = -1
        best_unused_item = None
        best_unused_score = -1
        block_key = self._normalize_for_match(block)
        block_tokens = set(self._tokenize(block))

        for item in news_items:
            title = item.get("title", "")
            description = item.get("description", "")
            item_text = f"{title} {description}"
            item_key = self._normalize_for_match(item_text)
            item_tokens = set(self._tokenize(item_text))
            token_score = len(block_tokens & item_tokens) / max(len(block_tokens | item_tokens), 1)
            char_score = SequenceMatcher(None, block_key, item_key).ratio()
            title_key = self._normalize_for_match(title)
            title_bonus = 0.15 if title_key and title_key in block_key else 0
            score = (token_score * 0.65) + (char_score * 0.35) + title_bonus
            if score > best_score:
                best_score = score
                best_item = item
            if self._item_link(item) not in used_links and score > best_unused_score:
                best_unused_score = score
                best_unused_item = item

        if best_unused_item:
            return self._item_link(best_unused_item)
        return self._item_link(best_item) if best_item else ""

    def _item_link(self, item):
        if not item:
            return ""
        return (item.get("link") or item.get("originallink") or "").strip()

    def _normalize_for_match(self, value):
        return re.sub(r"[\W_]+", "", value or "", flags=re.UNICODE).lower()

    def _tokenize(self, value):
        return re.findall(r"[가-힣A-Za-z0-9]{2,}", value or "")

    def _clip_text(self, value, limit):
        text = re.sub(r"\s+", " ", value or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    def _output_schema(self):
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["kakao_message", "tts_script"],
            "properties": {
                "kakao_message": {"type": "string"},
                "tts_script": {"type": "string"},
            },
        }

    def _resolve_codex_command(self, command):
        if os.name != "nt" or os.path.basename(command).lower() != "codex":
            return command

        for candidate in ("codex.cmd", "codex.bat", "codex.exe", "codex"):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
        return command


if __name__ == "__main__":
    dummy_news = [
        {
            "title": "대체복무요원 교육 과정 개편 논의",
            "description": "대체복무 관련 교육과 복무기관 운영 기준을 개선하기 위한 논의가 진행됐다는 소식입니다.",
            "pubDate": "2026-05-20 10:00:00",
            "link": "https://example.com/news/1",
        },
        {
            "title": "양심적 병역거부 관련 판례 분석 세미나 열려",
            "description": "법조계와 시민단체가 양심적 병역거부와 대체복무 제도 운영 현황을 점검했습니다.",
            "pubDate": "2026-05-20 14:30:00",
            "link": "https://example.com/news/2",
        },
    ]
    summarizer = LLMSummarizer()
    res = summarizer.summarize_news(dummy_news)
    print("====== 카카오톡 메시지 ======")
    print(res["kakao_message"])
    print("\n====== TTS 낭독 스크립트 ======")
    print(res["tts_script"])
