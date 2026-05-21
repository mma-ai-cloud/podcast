import os
import sys
import json
import re
import shutil
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from datetime import datetime, timedelta, timezone

from news_collector import DEFAULT_KEYWORDS, NewsCollector
from llm_summarizer import LLMSummarizer
from tts_generator import TTSGenerator

ARCHIVE_DIR = "archive"
HISTORY_FILE = "history.json"
HISTORY_LIMIT = 60

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

def get_audio_duration_seconds(audio_path):
    """
    모바일 브라우저가 audio metadata를 늦게 읽는 경우를 대비해
    생성 시점에 MP3 길이를 data.json에 저장합니다.
    """
    if not os.path.exists(audio_path):
        return None

    try:
        from mutagen.mp3 import MP3
        audio_file = MP3(audio_path)
        duration = float(audio_file.info.length)
        if duration > 0:
            return round(duration, 3)
    except Exception as e:
        print(f"[WARNING] MP3 길이 계산 실패: {e}", file=sys.stderr)
    return None

def ensure_trailing_slash(url):
    return url if url.endswith("/") else f"{url}/"

def safe_archive_id(value):
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return cleaned or "briefing"

def archive_id_from_updated_at(updated_at, fallback):
    if not updated_at:
        return fallback

    timestamp = updated_at.replace(" KST", "").strip()
    try:
        parsed = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        return parsed.strftime("%Y%m%d-%H%M%S")
    except ValueError:
        return safe_archive_id(timestamp) or fallback

def read_json_file(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARNING] {path} 읽기 실패: {e}", file=sys.stderr)
        return default

def fetch_url_bytes(url, timeout=15):
    request = Request(
        url,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "military-news-briefing-builder",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()

def fetch_json_url(url, default):
    try:
        payload = fetch_url_bytes(url)
        return json.loads(payload.decode("utf-8"))
    except HTTPError as e:
        if e.code != 404:
            print(f"[WARNING] 원격 JSON 조회 실패({url}): HTTP {e.code}", file=sys.stderr)
    except (URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"[WARNING] 원격 JSON 조회 실패({url}): {e}", file=sys.stderr)
    return default

def load_existing_history(pages_url):
    local_history = read_json_file(HISTORY_FILE, [])
    if local_history:
        return local_history if isinstance(local_history, list) else []

    if not os.environ.get("GITHUB_REPOSITORY"):
        return []

    history_url = urljoin(ensure_trailing_slash(pages_url), HISTORY_FILE)
    remote_history = fetch_json_url(history_url, [])
    return remote_history if isinstance(remote_history, list) else []

def history_entry_for(web_data, archive_id, data_path, audio_path):
    return {
        "id": archive_id,
        "date": web_data.get("date", ""),
        "updated_at": web_data.get("updated_at", ""),
        "title": f"{web_data.get('date', '브리핑')} 브리핑",
        "data_url": data_path,
        "audio_url": audio_path,
        "news_count": len(web_data.get("news_list") or []),
    }

def write_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def write_archive_snapshot(web_data, archive_id, audio_source_path=None, audio_bytes=None):
    archive_path = os.path.join(ARCHIVE_DIR, archive_id)
    os.makedirs(archive_path, exist_ok=True)

    data_path = f"{ARCHIVE_DIR}/{archive_id}/data.json"
    audio_path = f"{ARCHIVE_DIR}/{archive_id}/briefing.mp3"
    archived_data = dict(web_data)
    archived_data["archive_id"] = archive_id
    archived_data["audio_src"] = audio_path if (audio_source_path or audio_bytes) else None
    archived_data["canonical_data_path"] = data_path
    archived_data["is_archive"] = True

    write_json_file(os.path.join(archive_path, "data.json"), archived_data)

    if audio_source_path and os.path.exists(audio_source_path):
        shutil.copy2(audio_source_path, os.path.join(archive_path, "briefing.mp3"))
    elif audio_bytes:
        with open(os.path.join(archive_path, "briefing.mp3"), "wb") as f:
            f.write(audio_bytes)

    return history_entry_for(archived_data, archive_id, data_path, archived_data["audio_src"])

def fetch_previous_live_snapshot(pages_url, existing_history_ids, current_archive_id):
    if not os.environ.get("GITHUB_REPOSITORY"):
        return None

    base_url = ensure_trailing_slash(pages_url)
    previous_data = fetch_json_url(urljoin(base_url, "data.json"), None)
    if not isinstance(previous_data, dict):
        return None

    fallback_id = archive_id_from_updated_at(
        previous_data.get("updated_at"),
        f"previous-{current_archive_id}",
    )
    archive_id = safe_archive_id(previous_data.get("archive_id") or fallback_id)
    if archive_id == current_archive_id or archive_id in existing_history_ids:
        return None

    try:
        audio_bytes = fetch_url_bytes(urljoin(base_url, "briefing.mp3"))
    except (HTTPError, URLError, TimeoutError) as e:
        print(f"[WARNING] 이전 음성 파일 보관 실패: {e}", file=sys.stderr)
        audio_bytes = None

    print(f"[INFO] 이전 배포 브리핑을 archive/{archive_id}/ 에 보관합니다.")
    return write_archive_snapshot(previous_data, archive_id, audio_bytes=audio_bytes)

def merge_history_entries(*entry_groups):
    merged = []
    seen = set()

    for entries in entry_groups:
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id")
            data_url = entry.get("data_url")
            if not entry_id or not data_url or entry_id in seen:
                continue
            merged.append(entry)
            seen.add(entry_id)
            if len(merged) >= HISTORY_LIMIT:
                return merged

    return merged

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

    audio_duration_seconds = get_audio_duration_seconds(output_mp3) if tts_success else None

    # 4. GitHub Pages용 JSON 데이터 세이브 (index.html이 fetch로 읽어갈 구조)
    print("\n[Step 4] Creating data.json for web player...")
    timezone_kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(timezone_kst)
    today_str = now_kst.strftime("%Y년 %m월 %d일")
    archive_id = now_kst.strftime("%Y%m%d-%H%M%S")
    
    # 카카오톡 메시지에 실제 배포될 웹 플레이어 링크 결합
    pages_url = get_github_pages_url()
    final_kakao_message = kakao_base_msg
    if "[이동하기]" in final_kakao_message:
        final_kakao_message = final_kakao_message.replace("[이동하기]", pages_url)
    else:
        final_kakao_message += f"\n\n🎧 음성 브리핑 바로 듣기:\n{pages_url}"

    web_data = {
        "archive_id": archive_id,
        "date": today_str,
        "kakao_message": final_kakao_message,  # 카카오톡 전송 시 바로 활용할 수 있도록 최종 메시지 저장
        "player_url": pages_url,
        "audio_src": output_mp3 if tts_success else None,
        "audio_duration_seconds": audio_duration_seconds,
        "tts_script": tts_script,
        "news_list": news_items,
        "updated_at": now_kst.strftime("%Y-%m-%d %H:%M:%S KST"),
    }

    try:
        existing_history = load_existing_history(pages_url)
        existing_history_ids = {entry.get("id") for entry in existing_history if isinstance(entry, dict)}
        previous_entry = fetch_previous_live_snapshot(pages_url, existing_history_ids, archive_id)
        current_entry = write_archive_snapshot(web_data, archive_id, audio_source_path=output_mp3 if tts_success else None)
        history = merge_history_entries([current_entry], [previous_entry] if previous_entry else [], existing_history)

        write_json_file("data.json", web_data)
        write_json_file(HISTORY_FILE, history)
        print("[INFO] data.json 저장 완료.")
        print("[INFO] history.json 및 브리핑 아카이브 저장 완료.")
    except Exception as e:
        print(f"[ERROR] data.json 파일 생성 실패: {e}", file=sys.stderr)

    print("\n==================================================")
    print("SUCCESS: Pipeline build and data generation completed!")
    print("==================================================")

if __name__ == "__main__":
    main()
