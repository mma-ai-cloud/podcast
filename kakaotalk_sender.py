import ctypes
import time

import win32api
import win32clipboard
import win32con
import win32gui
import win32process

user32 = ctypes.windll.user32


class KakaoTalkSender:
    def __init__(self):
        self.main_class_name = "EVA_Window_Dblclk"
        self.main_title = "카카오톡"
        self.chat_class_name = "EVA_Window_Dblclk"
        self.edit_class_names = ("RICHEDIT50W", "Edit")

    # ──────────────────────────────────────────────
    # 내부 유틸리티
    # ──────────────────────────────────────────────

    def _force_foreground(self, hwnd):
        """카카오톡 창을 포그라운드로 올립니다."""
        vk_menu = 0x12
        hwnd_topmost = -1
        hwnd_notopmost = -2
        swp_nomove = 0x0002
        swp_nosize = 0x0001
        swp_showwindow = 0x0040

        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

        # Windows foreground restriction 완화용 Alt key press.
        user32.keybd_event(vk_menu, 0, 0, 0)
        user32.keybd_event(vk_menu, 0, win32con.KEYEVENTF_KEYUP, 0)

        current_tid = win32api.GetCurrentThreadId()
        target_tid, _ = win32process.GetWindowThreadProcessId(hwnd)
        user32.AttachThreadInput(current_tid, target_tid, True)
        try:
            win32gui.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetWindowPos(
                hwnd,
                hwnd_topmost,
                0,
                0,
                0,
                0,
                swp_nomove | swp_nosize | swp_showwindow,
            )
            user32.SetWindowPos(
                hwnd,
                hwnd_notopmost,
                0,
                0,
                0,
                0,
                swp_nomove | swp_nosize | swp_showwindow,
            )
        finally:
            user32.AttachThreadInput(current_tid, target_tid, False)
        time.sleep(0.2)

    def _press_key(self, vk, modifier=None):
        """단일 키 또는 단축키를 시뮬레이션합니다."""
        if modifier:
            user32.keybd_event(modifier, 0, 0, 0)
            time.sleep(0.02)
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.03)
        user32.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        if modifier:
            time.sleep(0.02)
            user32.keybd_event(modifier, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.1)

    def _set_clipboard_text(self, text, attempts=5):
        """유니코드 텍스트를 Win32 클립보드에 복사합니다."""
        last_error = None
        for _ in range(attempts):
            try:
                win32clipboard.OpenClipboard()
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
                    return
                finally:
                    win32clipboard.CloseClipboard()
            except Exception as exc:
                last_error = exc
                time.sleep(0.1)
        raise RuntimeError(f"클립보드 접근 실패: {last_error}")

    def _click_window_center(self, hwnd):
        rect = win32gui.GetWindowRect(hwnd)
        cx = (rect[0] + rect[2]) // 2
        cy = (rect[1] + rect[3]) // 2
        user32.SetCursorPos(cx, cy)
        time.sleep(0.05)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.1)

    def _focus_and_send(self, chat_hwnd, edit_hwnd, message):
        """
        RICHEDIT50W 입력창을 우선 타겟팅하고 클립보드 붙여넣기 방식으로 전송합니다.
        kronenz/kakaotalk-mcp의 Win32 제어 방식과 같은 방향으로 맞춘 구현입니다.
        """
        wm_setfocus = 0x0007
        em_setsel = 0x00B1
        wm_clear = 0x0303

        self._force_foreground(chat_hwnd)
        win32gui.SendMessage(edit_hwnd, wm_setfocus, 0, 0)
        self._click_window_center(edit_hwnd)

        # 입력창에 이전 임시 텍스트가 남아 있으면 지웁니다.
        win32api.SendMessage(edit_hwnd, em_setsel, 0, -1)
        win32api.SendMessage(edit_hwnd, wm_clear, 0, 0)
        time.sleep(0.1)

        self._set_clipboard_text(message)
        time.sleep(0.1)
        self._press_key(ord("V"), win32con.VK_CONTROL)
        time.sleep(0.2)
        self._press_key(win32con.VK_RETURN)
        time.sleep(0.2)

    # ──────────────────────────────────────────────
    # 창 탐색
    # ──────────────────────────────────────────────

    def _find_kakaotalk_main(self):
        """카카오톡 메인 윈도우 핸들을 반환합니다."""
        hwnd = win32gui.FindWindow(self.main_class_name, self.main_title)
        if not hwnd:
            hwnd = win32gui.FindWindow(None, self.main_title)
        if not hwnd:
            hwnd = win32gui.FindWindow("EVA_Window_Light", None)
        return hwnd

    def _find_chat_window(self, room_name):
        """제목이 정확히 일치하는 채팅창을 우선 찾고, 없으면 포함 매칭합니다."""
        candidates = []

        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                cls = win32gui.GetClassName(hwnd)
                if cls == self.chat_class_name and title:
                    candidates.append((hwnd, title))
            return True  # 항상 True 반환 (return False 시 pywin32 내부 에러 발생)

        win32gui.EnumWindows(cb, None)

        # 1순위: 정확히 일치
        for hwnd, title in candidates:
            if title == room_name:
                return hwnd
        # 2순위: 포함 매칭
        for hwnd, title in candidates:
            if room_name in title:
                return hwnd
        return None


    def _find_child_by_class(self, parent_hwnd, class_name):
        if not parent_hwnd:
            return None
        found = []

        def cb(hwnd, _):
            if win32gui.GetClassName(hwnd) == class_name:
                found.append(hwnd)
                return False
            return True

        win32gui.EnumChildWindows(parent_hwnd, cb, None)
        return found[0] if found else None

    def _find_input_edit(self, chat_hwnd):
        """채팅창 내부의 입력 컨트롤 핸들을 반환합니다."""
        for class_name in self.edit_class_names:
            hwnd = self._find_child_by_class(chat_hwnd, class_name)
            if hwnd and win32gui.IsWindowVisible(hwnd):
                return hwnd
        return None

    def _find_chat_list_view(self, main_hwnd):
        found = []

        def cb(hwnd, _):
            cls = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd)
            if cls == "EVA_Window" and "ChatRoomListView" in title:
                found.append(hwnd)
                return False
            return True

        win32gui.EnumChildWindows(main_hwnd, cb, None)
        return found[0] if found else None

    def _open_chat_room_via_search(self, main_hwnd, room_name):
        """메인 창에서 Ctrl+F 검색으로 대화방을 엽니다."""
        self._force_foreground(main_hwnd)
        self._press_key(ord("F"), win32con.VK_CONTROL)
        time.sleep(0.3)

        chat_list = self._find_chat_list_view(main_hwnd)
        search_edit = self._find_child_by_class(chat_list, "Edit") if chat_list else None
        if search_edit:
            em_setsel = 0x00B1
            wm_clear = 0x0303
            wm_char = 0x0102
            win32api.SendMessage(search_edit, em_setsel, 0, -1)
            win32api.SendMessage(search_edit, wm_clear, 0, 0)
            for ch in room_name:
                win32api.SendMessage(search_edit, wm_char, ord(ch), 0)
                time.sleep(0.02)
        else:
            self._set_clipboard_text(room_name)
            self._press_key(ord("V"), win32con.VK_CONTROL)

        time.sleep(0.8)
        self._press_key(win32con.VK_RETURN)
        time.sleep(1.2)

    # ──────────────────────────────────────────────
    # 공개 API
    # ──────────────────────────────────────────────

    def list_open_rooms(self):
        """현재 열려 있는 카카오톡 채팅방 목록을 반환합니다."""
        main_hwnd = self._find_kakaotalk_main()
        windows = []

        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                cls = win32gui.GetClassName(hwnd)
                if cls == self.chat_class_name and hwnd != main_hwnd and title and title != self.main_title:
                    windows.append({"hwnd": hwnd, "title": title})
            return True

        win32gui.EnumWindows(cb, None)
        return windows

    def send_message_to_room(self, room_name, message):
        """
        지정한 카카오톡 대화방에 메시지를 전송합니다.
        1) 이미 열린 채팅창이 있으면 직접 타겟
        2) 없으면 메인창 Ctrl+F 검색으로 열기
        3) RICHEDIT50W 입력창에 Ctrl+V → Enter 전송
        """
        chat_hwnd = self._find_chat_window(room_name)

        if chat_hwnd:
            print(f"[정보] 이미 열린 채팅창 발견 (HWND: {chat_hwnd}) → 직접 타겟")
        else:
            main_hwnd = self._find_kakaotalk_main()
            if not main_hwnd:
                print("[오류] 카카오톡이 실행되지 않거나 로그인되지 않았습니다.")
                return False

            print(f"[정보] 메인창 (HWND: {main_hwnd}) → Ctrl+F 검색으로 채팅방 열기")
            self._open_chat_room_via_search(main_hwnd, room_name)
            chat_hwnd = self._find_chat_window(room_name)

        if not chat_hwnd:
            print(f"[오류] '{room_name}' 채팅창을 찾을 수 없습니다.")
            print(f"[정보] 현재 열린 채팅방: {self.list_open_rooms()}")
            return False

        try:
            edit_hwnd = self._find_input_edit(chat_hwnd)
            if edit_hwnd:
                edit_class = win32gui.GetClassName(edit_hwnd)
                print(f"[정보] {edit_class} 입력창 발견 (HWND: {edit_hwnd}) → Win32 클립보드 전송 방식")
                self._focus_and_send(chat_hwnd, edit_hwnd, message)
            else:
                print("[경고] 입력 컨트롤 없음 → 창 포커스 후 Ctrl+V fallback")
                self._force_foreground(chat_hwnd)
                self._set_clipboard_text(message)
                time.sleep(0.2)
                self._press_key(ord("V"), win32con.VK_CONTROL)
                time.sleep(0.2)
                self._press_key(win32con.VK_RETURN)

            print(f"[성공] '{room_name}' 방에 메시지 전송 완료!")
            return True

        except Exception as e:
            print(f"[오류] 카카오톡 제어 중 예외 발생: {e}")
            return False


if __name__ == "__main__":
    import sys

    test_room = "대화반"
    test_msg = "[Antigravity 테스트]\n\n자동 전송 테스트 메시지입니다.\n이 메시지가 보이면 성공입니다."
    sender = KakaoTalkSender()
    success = sender.send_message_to_room(test_room, test_msg)
    sys.exit(0 if success else 1)
