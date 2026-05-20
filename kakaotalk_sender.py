import time
import ctypes
import win32api
import win32con
import win32gui
import win32process
import pyperclip

user32 = ctypes.windll.user32


class KakaoTalkSender:
    def __init__(self):
        self.main_class_name = "EVA_Window_Light"
        self.chat_class_name = "EVA_Window_Dblclk"

    # ──────────────────────────────────────────────
    # 내부 유틸리티
    # ──────────────────────────────────────────────

    def _force_foreground(self, hwnd):
        """AttachThreadInput 트릭으로 백그라운드에서도 창을 최전면으로 끌어올립니다."""
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

        current_tid = win32api.GetCurrentThreadId()
        target_tid, _ = win32process.GetWindowThreadProcessId(hwnd)
        user32.AttachThreadInput(current_tid, target_tid, True)
        try:
            win32gui.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            user32.AttachThreadInput(current_tid, target_tid, False)
        time.sleep(0.5)

    def _press_key(self, vk, modifier=None):
        """단일 키 또는 단축키를 시뮬레이션합니다."""
        if modifier:
            win32api.keybd_event(modifier, 0, 0, 0)
        win32api.keybd_event(vk, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        if modifier:
            win32api.keybd_event(modifier, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.1)

    def _focus_and_send(self, chat_hwnd, edit_hwnd, message):
        """
        Edit 컨트롤에 직접 포커스를 부여하고 클립보드 방식으로 텍스트를 전송합니다.
        마우스 좌표와 무관하게 동작하므로 백그라운드에서도 안정적입니다.
        """
        WM_SETFOCUS  = 0x0007
        EM_SETSEL    = 0x00B1
        WM_KEYDOWN   = 0x0100
        WM_KEYUP     = 0x0101

        # 1) 채팅창 자체를 최전면으로
        self._force_foreground(chat_hwnd)

        # 2) Edit 컨트롤에 직접 SetFocus 메시지 전송
        win32gui.SendMessage(edit_hwnd, WM_SETFOCUS, 0, 0)
        time.sleep(0.2)

        # 3) 커서를 맨 끝으로 이동 (EM_SETSEL -1,-1 = 끝으로)
        win32gui.SendMessage(edit_hwnd, EM_SETSEL, -1, -1)
        time.sleep(0.1)

        # 4) 클립보드에 메시지 복사 후 키보드 Ctrl+V
        pyperclip.copy(message)
        time.sleep(0.2)
        self._press_key(ord('V'), win32con.VK_CONTROL)
        time.sleep(0.5)

        # 5) Enter 전송
        self._press_key(win32con.VK_RETURN)
        time.sleep(0.5)


    # ──────────────────────────────────────────────
    # 창 탐색
    # ──────────────────────────────────────────────

    def _find_kakaotalk_main(self):
        """카카오톡 메인 윈도우 핸들을 반환합니다."""
        hwnd = win32gui.FindWindow(self.main_class_name, None)
        if not hwnd:
            hwnd = win32gui.FindWindow(None, "카카오톡")
        return hwnd

    def _find_chat_window(self, room_name):
        """제목에 room_name이 포함된 EVA_Window_Dblclk 창을 찾습니다."""
        found = []
        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                cls = win32gui.GetClassName(hwnd)
                if cls == self.chat_class_name and room_name in title:
                    found.append(hwnd)
        win32gui.EnumWindows(cb, None)
        return found[0] if found else None

    def _find_input_edit(self, chat_hwnd):
        """채팅창 내부의 Edit(입력창) 컨트롤 핸들을 반환합니다."""
        found = []
        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                cls = win32gui.GetClassName(hwnd)
                if cls == "Edit":
                    found.append(hwnd)
        win32gui.EnumChildWindows(chat_hwnd, cb, None)
        return found[0] if found else None

    def _open_chat_room_via_search(self, main_hwnd, room_name):
        """메인 창에서 Ctrl+F 검색으로 대화방을 엽니다."""
        self._force_foreground(main_hwnd)
        self._press_key(ord('F'), win32con.VK_CONTROL)
        time.sleep(0.5)
        self._paste_clipboard(room_name)
        time.sleep(0.5)
        self._press_key(win32con.VK_RETURN)
        time.sleep(1.2)

    # ──────────────────────────────────────────────
    # 공개 API
    # ──────────────────────────────────────────────

    def send_message_to_room(self, room_name, message):
        """
        지정한 카카오톡 대화방에 메시지를 전송합니다.
        1) 이미 열린 채팅창이 있으면 직접 타겟
        2) 없으면 메인창 Ctrl+F 검색으로 열기
        3) Edit 컨트롤에 직접 마우스 클릭 후 Ctrl+V → Enter 전송
        """
        # 1. 채팅창 직접 탐색
        chat_hwnd = self._find_chat_window(room_name)

        if chat_hwnd:
            print(f"[정보] 이미 열린 채팅창 발견 (HWND: {chat_hwnd}) → 직접 타겟")
        else:
            # 2. 메인창에서 검색으로 열기
            main_hwnd = self._find_kakaotalk_main()
            if not main_hwnd:
                print("[오류] 카카오톡이 실행되지 않거나 로그인되지 않았습니다.")
                return False

            print(f"[정보] 메인창 (HWND: {main_hwnd}) → Ctrl+F 검색으로 채팅방 열기")
            self._open_chat_room_via_search(main_hwnd, room_name)
            chat_hwnd = self._find_chat_window(room_name)

        if not chat_hwnd:
            print(f"[오류] '{room_name}' 채팅창을 찾을 수 없습니다.")
            return False

        try:
            # 3. 채팅창 활성화
            self._force_foreground(chat_hwnd)

            # 4. Edit 입력창 직접 포커스 후 메시지 전송
            edit_hwnd = self._find_input_edit(chat_hwnd)
            if edit_hwnd:
                print(f"[정보] Edit 입력창 발견 (HWND: {edit_hwnd}) → SendMessage 포커스 방식")
                self._focus_and_send(chat_hwnd, edit_hwnd, message)
            else:
                # fallback: Edit 컨트롤 못 찾으면 창 강제 활성화 후 Ctrl+V
                print("[경고] Edit 컨트롤 없음 → 창 포커스 후 Ctrl+V fallback")
                self._force_foreground(chat_hwnd)
                time.sleep(0.3)
                pyperclip.copy(message)
                time.sleep(0.2)
                self._press_key(ord('V'), win32con.VK_CONTROL)
                time.sleep(0.5)
                self._press_key(win32con.VK_RETURN)
                time.sleep(0.5)

            print(f"[성공] '{room_name}' 방에 메시지 전송 완료!")
            return True

        except Exception as e:
            print(f"[오류] 카카오톡 제어 중 예외 발생: {e}")
            return False



if __name__ == "__main__":
    import sys
    test_room = "대화반"
    test_msg = "[Antigravity 테스트]\n\n자동 전송 테스트 메시지입니다. ✅\n이 메시지가 보이면 성공입니다!"
    sender = KakaoTalkSender()
    success = sender.send_message_to_room(test_room, test_msg)
    sys.exit(0 if success else 1)
