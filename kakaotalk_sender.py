import time
import win32api
import win32con
import win32gui
import pyperclip

class KakaoTalkSender:
    def __init__(self):
        self.main_class_name = "EVA_Window_Light"
        self.chat_class_name = "EVA_Window_Dark"  # 일부 개별 채팅방의 윈도우 클래스명

    def _find_kakaotalk_main(self):
        """
        카카오톡 메인 윈도우 핸들을 찾습니다.
        """
        hwnd = win32gui.FindWindow(self.main_class_name, None)
        if hwnd == 0:
            # 보조 클래스명이나 타이틀 명시 검색 시도
            hwnd = win32gui.FindWindow(None, "카카오톡")
        return hwnd

    def _force_foreground(self, hwnd):
        """
        윈도우 핸들을 포커싱하고 최상단으로 끌어올립니다.
        """
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        
        # 포커스 활성화 (안정성 증대)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.5)

    def _press_key_combination(self, key1, key2=None):
        """
        단축키 또는 입력을 가상 키 코드로 에뮬레이션합니다.
        """
        if key2:
            win32api.keybd_event(key1, 0, 0, 0)
            win32api.keybd_event(key2, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(key2, 0, win32con.KEYEVENTF_KEYUP, 0)
            win32api.keybd_event(key1, 0, win32con.KEYEVENTF_KEYUP, 0)
        else:
            win32api.keybd_event(key1, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(key1, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.1)

    def _send_text_via_clipboard(self, text):
        """
        pyperclip을 사용해 클립보드에 한글 텍스트를 복사한 뒤, Ctrl+V 단축키로 안전하게 붙여넣습니다.
        """
        pyperclip.copy(text)
        # Ctrl + V 전송
        self._press_key_combination(win32con.VK_CONTROL, ord('V'))

    def send_message_to_room(self, room_name, message):
        """
        지정한 카카오톡 대화방 이름을 검색하여 메시지를 전송합니다.
        """
        main_hwnd = self._find_kakaotalk_main()
        if not main_hwnd:
            print("[오류] 카카오톡 PC 버전이 켜져 있지 않거나 로그인되지 않았습니다.")
            return False

        print(f"[정보] 카카오톡 메인 윈도우 발견 (HWND: {main_hwnd})")
        
        try:
            # 1. 카카오톡 메인 창 활성화
            self._force_foreground(main_hwnd)

            # 2. 친구/채팅방 검색창 단축키 (Ctrl + F) 누르기
            print("[정보] 검색창을 활성화합니다 (Ctrl + F)")
            self._press_key_combination(win32con.VK_CONTROL, ord('F'))
            time.sleep(0.3)

            # 3. 대화방 이름 입력 후 열기
            print(f"[정보] 대화방 '{room_name}' 검색 중...")
            self._send_text_via_clipboard(room_name)
            time.sleep(0.3)
            
            # 검색창에서 첫 번째 검색 결과인 대화방을 실행하기 위해 Enter 입력
            self._press_key_combination(win32con.VK_RETURN)
            time.sleep(0.8)  # 대화방 창이 뜨는 시간 대기

            # 4. 활성화된 대화방 창 찾기
            # 방금 연 채팅방이 활성화되어 있으므로 GetForegroundWindow()로 가져옴
            chat_hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(chat_hwnd)
            
            # 연 윈도우가 카카오톡 메인 창이 아닌 대화방인지 검증 (안전장치)
            if chat_hwnd == main_hwnd:
                print(f"[경고] 대화방 '{room_name}'을 여는 데 실패했거나 검색 결과가 없습니다.")
                return False

            print(f"[정보] 대상 대화방 창 확보 완료 (제목: {title}, HWND: {chat_hwnd})")

            # 5. 메시지 복사 후 붙여넣기로 대화방에 입력
            print("[정보] 브리핑 메시지 내용을 붙여넣는 중...")
            self._send_text_via_clipboard(message)
            time.sleep(0.3)

            # 6. 전송 엔터키 시뮬레이션
            print("[정보] 메시지를 전송합니다 (Enter)")
            self._press_key_combination(win32con.VK_RETURN)
            time.sleep(0.5)

            # 7. 대화방 창 닫기 (ESC 또는 Alt+F4) - 세션 정리
            print("[정보] 대화방 세션을 닫고 정리합니다.")
            self._press_key_combination(win32con.VK_ESCAPE)
            
            print(f"🎉 성공적으로 '{room_name}' 대화방에 브리핑 메시지를 전송하였습니다! 🎉")
            return True

        except Exception as e:
            print(f"[오류] 카카오톡 제어 중 예외 발생: {e}")
            return False

if __name__ == "__main__":
    # 로컬 수동 테스트용 코드
    # 실제 존재하는 친구 혹은 대화방(예: '나와의 채팅')으로 테스트할 수 있습니다.
    import sys
    test_room = "나와의 채팅"
    test_msg = "[테스트 브리핑]\n\n이것은 Antigravity 로컬 윈도우 카카오톡 제어 모듈 테스트입니다.\n본 메시지가 보인다면 성공입니다!"
    
    print(f"'{test_room}' 방으로 테스트 전송을 시작합니다...")
    sender = KakaoTalkSender()
    success = sender.send_message_to_room(test_room, test_msg)
    if not success:
        sys.exit(1)
