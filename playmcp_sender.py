import os
import shutil
import subprocess
import sys


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def normalize_kakao_line(message):
    return " ".join((message or "").replace("\r", " ").replace("\n", " ").split()).strip()


def resolve_mcporter_command():
    configured = os.environ.get("MCPORTER_COMMAND")
    if configured:
        return configured

    for candidate in ("mcporter", "mcporter.cmd"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    raise FileNotFoundError("mcporter 실행 파일을 찾을 수 없습니다.")


def send_playmcp_memo(message, timeout_sec=60):
    text = normalize_kakao_line(message)
    if not text:
        raise ValueError("보낼 카카오톡 메시지가 비어 있습니다.")

    command = [
        resolve_mcporter_command(),
        "call",
        "mcp-gateway.KakaotalkChat-MemoChat",
        f"message={text}",
    ]
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=timeout_sec,
        check=False,
    )

    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    if completed.returncode != 0:
        raise RuntimeError(f"PlayMCP 카카오톡 전송 실패: {error or output}")

    return output or "메시지를 성공적으로 보냈습니다."


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python playmcp_sender.py 메시지", file=sys.stderr)
        sys.exit(2)
    print(send_playmcp_memo(" ".join(sys.argv[1:])))
