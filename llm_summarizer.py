import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time


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
                "안녕하십니까. 대체복무 관련 아침 브리핑입니다. "
                "어제 하루 동안 새로 확인된 주요 대체복무 관련 뉴스는 없습니다. "
                "오늘도 평온하고 건강한 하루 보내시기 바랍니다. 감사합니다."
            )
            return {
                "kakao_message": (
                    "📢 [오늘의 대체복무 브리핑]\n\n"
                    "어제 하루 동안 새로 확인된 주요 대체복무 관련 뉴스가 없습니다.\n"
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
- 친절하지만 과장 없는 한국어 문체를 사용하세요.
- 첫 줄은 "📢 [오늘의 대체복무 브리핑]"로 시작하세요.
- 항목 번호는 반드시 "1️⃣", "2️⃣", "3️⃣" 같은 숫자 이모티콘을 사용하세요. "1.", "2.", "1)" 형식은 쓰지 마세요.
- 마크다운 굵게 표시나 기호를 쓰지 마세요. 특히 "**", "__", "#", "`" 문자는 절대 쓰지 마세요.
- 마지막에는 반드시 "🎧 음성 브리핑 바로 듣기: [이동하기]" 문장을 포함하세요. URL은 쓰지 마세요.

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
                print(f"[정보] Codex CLI 요약 성공! (시도 {attempt}회)")
                return result
            except Exception as e:
                print(f"[경고] Codex CLI 요약 실패 (시도 {attempt}/{max_retries}): {e}", file=sys.stderr)
                if attempt < max_retries:
                    wait_sec = 2 ** attempt
                    print(f"[정보] {wait_sec}초 후 재시도합니다...")
                    time.sleep(wait_sec)

        print("[오류] Codex CLI 최대 재시도 횟수 초과. 폴백 메시지를 사용합니다.", file=sys.stderr)
        return {
            "kakao_message": (
                "📢 [오늘의 대체복무 브리핑]\n\n"
                "뉴스 요약 중 오류가 발생했습니다. 플레이어 링크를 참고해 주세요."
            ),
            "tts_script": (
                "안녕하세요. 오늘 아침 대체복무 뉴스 브리핑 시스템에 일시적인 지연이 발생했습니다. "
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
