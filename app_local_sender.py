import os
import sys
import json

from kakaotalk_sender import KakaoTalkSender

def load_dotenv():
    """
    로컬 환경의 .env 파일을 파싱하여 환경 변수에 직접 주입합니다.
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

# 로컬 설정 로드
load_dotenv()

def main():
    print("==================================================")
    print("[SYSTEM] Start KakaoTalk Local Auto Sender (V4)")
    print("==================================================")

    data_file = "data.json"
    if not os.path.exists(data_file):
        print(f"[오류] 요약본 데이터 파일({data_file})이 존재하지 않습니다.", file=sys.stderr)
        print("GitHub Actions 빌드가 아직 완료되지 않았거나 파일이 저장소에서 풀(pull)되지 않았습니다.", file=sys.stderr)
        sys.exit(1)

    try:
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[오류] 데이터 파일 로드 실패: {e}", file=sys.stderr)
        sys.exit(1)

    # data.json에서 최종 정제된 카카오톡 메시지 추출
    message = data.get("kakao_message")
    if not message:
        print("[오류] 요약된 카카오톡 메시지 내용이 data.json에 존재하지 않습니다.", file=sys.stderr)
        sys.exit(1)

    # 전송할 대화방 이름 로드
    room_name = os.environ.get("KAKAOTALK_ROOM_NAME", "나와의 채팅")
    print(f"[정보] 대상 대화방 이름: '{room_name}'")
    print("====== 전송할 메시지 내용 ======")
    print(message)
    print("================================\n")

    # 카카오톡 전송 라이브러리 가동
    sender = KakaoTalkSender()
    success = sender.send_message_to_room(room_name, message)

    print("==================================================")
    if success:
        print("SUCCESS: 카카오톡 브리핑 메시지가 안전하게 전송되었습니다!")
    else:
        print("ERROR: 카카오톡 전송 중 오류가 발생했습니다.")
        sys.exit(1)
    print("==================================================")

if __name__ == "__main__":
    main()
