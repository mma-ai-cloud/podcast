import os
import sys
import json
from datetime import datetime, timedelta, timezone

from news_collector import DEFAULT_KEYWORDS, NewsCollector
from llm_summarizer import LLMSummarizer
from tts_generator import TTSGenerator

def load_dotenv():
    """
    외부 라이브러리 없이 로컬의 .env 파일을 파싱하여 환경 변수에 직접 주입합니다.
    """
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()

# 스크립트 로드 시 .env 환경변수를 자동으로 로드합니다.
load_dotenv()

def get_github_pages_url():
    """
    GitHub Actions 환경 변수로부터 배포될 GitHub Pages의 Base URL을 빌드합니다.
    """
    repo = os.environ.get("GITHUB_REPOSITORY")  # 예: "username/my-repo"
    if not repo:
        return "https://localhost:8000"  # 로컬 테스트용 폴백

    owner, repo_name = repo.split("/")
    # GitHub Pages 주소 형식: https://owner.github.io/repo_name/
    return f"https://{owner}.github.io/{repo_name}/"

def main():
    print("==================================================")
    print("[SYSTEM] Start Alternative Service News Briefing Pipeline (V4)")
    print("==================================================")

    # 1. 뉴스 수집
    print("\n[Step 1] Fetching news via Naver API...")
    collector = NewsCollector()
    news_items = collector.fetch_yesterday_news(query=DEFAULT_KEYWORDS)
    
    # 2. LLM 요약 및 스크립트 작성
    print("\n[Step 2] Summarizing news via Codex CLI...")
    try:
        summarizer = LLMSummarizer()
        briefing_result = summarizer.summarize_news(news_items)
    except Exception as e:
        print(f"[ERROR] LLM 요약 실패: {e}", file=sys.stderr)
        sys.exit(1)

    kakao_base_msg = briefing_result.get("kakao_message", "")
    tts_script = briefing_result.get("tts_script", "")

    # 3. 고품질 TTS 음성 생성
    print("\n[Step 3] Generating speech via edge-tts...")
    output_mp3 = "briefing.mp3"
    tts = TTSGenerator(voice="ko-KR-SunHiNeural")  # 아나운서 스타일 여성 목소리
    tts_success = tts.generate_speech(tts_script, output_mp3)

    if not tts_success:
        print("[WARNING] TTS 생성에 실패했습니다. 기본 오디오 없이 텍스트 전송만 준비합니다.")

    # 4. GitHub Pages용 JSON 데이터 세이브 (index.html이 fetch로 읽어갈 구조)
    print("\n[Step 4] Creating data.json for web player...")
    timezone_kst = timezone(timedelta(hours=9))
    today_str = datetime.now(timezone_kst).strftime("%Y년 %m월 %d일")
    
    # 카카오톡 메시지에 실제 배포될 웹 플레이어 링크 결합
    pages_url = get_github_pages_url()
    final_kakao_message = kakao_base_msg
    if "[이동하기]" in final_kakao_message:
        final_kakao_message = final_kakao_message.replace("[이동하기]", pages_url)
    else:
        final_kakao_message += f"\n\n🎧 음성 브리핑 바로 듣기:\n{pages_url}"

    web_data = {
        "date": today_str,
        "kakao_message": final_kakao_message,  # 카카오톡 전송 시 바로 활용할 수 있도록 최종 메시지 저장
        "player_url": pages_url,
        "tts_script": tts_script,
        "news_list": news_items,
        "updated_at": datetime.now(timezone_kst).strftime("%Y-%m-%d %H:%M:%S KST")
    }

    try:
        with open("data.json", "w", encoding="utf-8") as f:
            json.dump(web_data, f, ensure_ascii=False, indent=2)
        print("[INFO] data.json 저장 완료.")
    except Exception as e:
        print(f"[ERROR] data.json 파일 생성 실패: {e}", file=sys.stderr)

    print("\n==================================================")
    print("SUCCESS: Pipeline build and data generation completed!")
    print("==================================================")

if __name__ == "__main__":
    main()
