import asyncio
import os
import sys
import edge_tts

class TTSGenerator:
    def __init__(self, voice="ko-KR-SunHiNeural"):
        """
        voice: 
          - "ko-KR-SunHiNeural" (여성, 깔끔한 아나운서 목소리 - 기본값)
          - "ko-KR-InJoonNeural" (남성, 부드럽고 차분한 목소리)
        """
        self.voice = voice

    async def generate_speech_async(self, text, output_path):
        """
        텍스트를 읽어서 지정된 경로에 MP3 파일로 저장합니다. (비동기 처리)
        """
        if not text:
            print("[경고] 음성으로 변환할 텍스트가 비어 있습니다.", file=sys.stderr)
            return False

        print(f"[정보] TTS 변환을 시작합니다. 목소리: {self.voice}")
        communicate = edge_tts.Communicate(text, self.voice)
        
        try:
            await communicate.save(output_path)
            print(f"[정보] TTS 오디오 파일이 성공적으로 생성되었습니다: {output_path}")
            return True
        except Exception as e:
            print(f"[오류] TTS 생성 중 예외 발생: {e}", file=sys.stderr)
            return False

    def generate_speech(self, text, output_path):
        """
        비동기 함수를 동기식으로 간편하게 호출할 수 있는 래퍼 함수입니다.
        """
        try:
            # 현재 실행 루프가 있으면 그것을 사용하고, 없으면 새로 만듭니다.
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        if loop.is_running():
            # 이미 비동기 루프가 돌고 있는 환경(예: FastAPI 내부)에서는 task를 통해 수행해야 함
            import nest_asyncio
            nest_asyncio.apply()
            
        return loop.run_until_complete(self.generate_speech_async(text, output_path))

if __name__ == "__main__":
    # 로컬 개발 및 테스트용 코드
    test_text = "안녕하십니까. 오월 이십일일 아침 병무청 주요 뉴스 브리핑입니다. 오늘 날씨는 맑고 쾌청하겠습니다. 즐거운 하루 되십시오."
    output = "test_briefing.mp3"
    
    print("Edge-TTS 테스트 음성 파일 생성을 시작합니다...")
    generator = TTSGenerator()
    success = generator.generate_speech(test_text, output)
    if success:
        print(f"테스트 파일 생성 완료! {os.path.abspath(output)} 파일을 확인해 보세요.")
    else:
        print("테스트 파일 생성에 실패했습니다.")
