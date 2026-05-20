import os
import sys
import time
from google import genai
from google.genai import types

class LLMSummarizer:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY 환경 변수 또는 생성자 인자가 설정되지 않았습니다.")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def summarize_news(self, news_items):
        """
        수집된 뉴스 아이템 리스트를 받아서 
        1. PC 카카오톡 텍스트 메시지용 요약문
        2. TTS(음성) 낭독용 스크립트 대본
        을 각각 생성하여 반환합니다.
        """
        if not news_items:
            # 뉴스가 없는 경우 디폴트 멘트 생성
            no_news_message = "안녕하십니까. 병무청 소식 아침 브리핑입니다. 어제 하루 동안 새로 등록된 주요 병무 행정 관련 뉴스는 없습니다. 평화롭고 활기찬 하루 되시기 바랍니다. 감사합니다."
            return {
                "kakao_message": "[병무청 뉴스 브리핑]\n\n어제 하루 동안 새로 등록된 주요 병무 관련 뉴스가 없습니다.\n오늘도 평화롭고 건강한 하루 되세요!",
                "tts_script": no_news_message
            }

        # Gemini 입력을 위해 뉴스 항목 구조화
        news_input = ""
        for idx, item in enumerate(news_items, 1):
            news_input += f"[{idx}] {item['title']}\n"
            news_input += f"내용: {item['description']}\n\n"

        prompt = f"""
당신은 대한민국 국방 및 병무 행정을 전문으로 다루는 뉴스 아나운서이자 스마트 브리핑 어시스턴트입니다.
아래에 제공된 어제 자 병무청 관련 뉴스 목록을 분석하고, 두 가지 버전의 결과물(1. 카카오톡 메시지, 2. TTS 낭독용 스크립트)을 생성해 주세요.

[분석할 뉴스 데이터]
{news_input}

---

[작성 가이드라인]
1. **결과물 1: 카카오톡 메시지 (kakao_message)**
   - 단톡방 멤버들이 바쁜 아침에 한눈에 파악할 수 있도록 핵심 이슈를 깔끔하게 요약해 주세요.
   - 격식 있으면서도 친절한 문체(이모티콘 적절히 활용)를 사용해 주세요.
   - 구조:
     📢 **[오늘의 병무청 브리핑]** (현재 날짜)
     - 핵심 뉴스 요약 2~3가지 (한 줄 요약 + 짧은 설명)
     - 🎧 **음성 브리핑 바로 듣기:** [이동하기](웹 플레이어 URL은 나중에 템플릿에 매핑되므로 그대로 놔두거나 빈칸으로 표기해 주세요.)

2. **결과물 2: TTS 낭독용 스크립트 (tts_script)**
   - **중요:** 이 텍스트는 인공지능 성우가 오디오 파일(MP3)로 읽을 대본입니다.
   - 따라서 물결표(~), 대괄호([]), 슬래시(/), URL, 영문 약어 등의 기호나 딱딱한 문자를 **최대한 자연스럽게 한국어 말소리로 풀어서 작성**해야 합니다. (예: '10%' -> '십 퍼센트', 'AI' -> '에이아이', '2026.05.21' -> '이천이십육년 오월 이십일일')
   - 부드럽고 차분한 목소리로 신뢰를 주는 아침 라디오 브리핑 멘트 형식으로 작성해 주세요. (예: "안녕하십니까. 오월 이십일일 목요일 아침 병무청 주요 뉴스 브리핑을 시작하겠습니다...")
   - 전체 낭독 시간은 1분 내외(공백 포함 400~600자)로 읽기 좋게 다듬어 주세요.

[출력 형식]
반드시 아래 JSON 형식으로만 정확히 반환해 주세요. 추가 설명이나 주석은 필요 없습니다.

{{
  "kakao_message": "카카오톡 메시지 내용",
  "tts_script": "TTS 낭독용 한국어 풀텍스트 대본"
}}
"""

        import json
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                print(f"[정보] Gemini API 요청 중... (시도 {attempt}/{max_retries})")
                response = self.client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.7
                    )
                )
                result = json.loads(response.text)
                print(f"[정보] Gemini API 요약 성공! (시도 {attempt}회)")
                return result
            except Exception as e:
                print(f"[경고] Gemini API 처리 실패 (시도 {attempt}/{max_retries}): {e}", file=sys.stderr)
                if attempt < max_retries:
                    wait_sec = 2 ** attempt  # 2초, 4초, 8초 exponential backoff
                    print(f"[정보] {wait_sec}초 후 재시도합니다...")
                    time.sleep(wait_sec)

        # 모든 재시도 실패 시 폴백
        print("[오류] Gemini API 최대 재시도 횟수 초과. 폴백 메시지를 사용합니다.", file=sys.stderr)
        return {
            "kakao_message": "[병무청 뉴스 브리핑]\n\n뉴스 요약 중 에러가 발생했습니다. 플레이어 링크를 참고해 주세요.",
            "tts_script": "안녕하세요. 오늘 아침 병무청 뉴스 브리핑 시스템에 일시적인 지연이 발생하였습니다. 대단히 죄송합니다. 잠시 후에 다시 실행해 주시기 바랍니다. 감사합니다."
        }

if __name__ == "__main__":
    # 로컬 개발 및 테스트용 코드
    import json
    dummy_news = [
        {
            "title": "병무청, 2026년도 병역판정검사 일자 및 장소 선택 접수 개시",
            "description": "병무청은 내년도 병역판정검사를 받으려는 대상자들을 위해 원하는 일자와 장소를 직접 선택할 수 있는 신청을 오늘 오전 10시부터 선착순으로 접수한다고 밝혔습니다."
        },
        {
            "title": "강원지방병무청, 모범 사회복무요원 초청 격려 워크숍 개최",
            "description": "강원지방병무청은 지역 내 복무 기관에서 투철한 책임감과 봉사 정신으로 귀감이 된 모범 사회복무요원 30명을 초청하여 힐링과 화합을 위한 워크숍을 진행했다고 전했습니다."
        }
    ]
    try:
        summarizer = LLMSummarizer()
        res = summarizer.summarize_news(dummy_news)
        print("====== 카카오 메시지 ======")
        print(res["kakao_message"])
        print("\n====== TTS 낭독 스크립트 ======")
        print(res["tts_script"])
    except Exception as e:
        print(f"테스트 실패 (API 키 누락 가능성): {e}")
