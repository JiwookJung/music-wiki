#!/usr/bin/env python3
"""호스트에서 `claude -p` 를 대신 실행해 주는 최소 프록시 (B2).

웹앱은 컨테이너 안에서 도는데 Claude Code CLI 는 호스트에만 있다(구독 로그인이
호스트 ~/.claude 에 묶여 있어 이미지에 넣을 수 없다). 그래서 호스트에 이 프록시를
두고 컨테이너가 유닉스 소켓으로 부른다.

**TCP 가 아니라 유닉스 소켓인 이유**: 이 엔드포인트는 임의 프롬프트로 구독 계정을
쓰게 해준다. 포트로 열면 같은 LAN 의 누구나 호출할 수 있다. 소켓 파일은 컨테이너에
바인드 마운트한 쪽만 닿는다.

    python scripts/claude_proxy.py [--socket /var/lib/mw-llm/claude.sock]

프로토콜: POST(경로 무관) {"prompt": "...", "timeout": 120} → {"answer": "..."}
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import socketserver
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler

DEFAULT_SOCKET = os.environ.get("MW_LLM_SOCK", "/var/lib/mw-llm/claude.sock")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))
MAX_PROMPT = 8000
MAX_TIMEOUT = 300


def run_claude(prompt: str, timeout: int) -> str:
    """전용 임시 디렉토리에서 최소 권한으로 실행 — 레포 컨텍스트 오염 방지."""
    with tempfile.TemporaryDirectory(prefix="mw-llm-") as wd:
        try:
            r = subprocess.run([CLAUDE_BIN, "-p", prompt], cwd=wd,
                               capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return f"(Claude Code 미설치 — {CLAUDE_BIN} 없음)"
        except subprocess.TimeoutExpired:
            return "(시간 초과)"
    return (r.stdout or r.stderr or "").strip()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"        # 응답 후 닫음 → 클라이언트는 EOF 까지 읽으면 됨
    server_version = "mw-claude-proxy"

    def do_POST(self):                                   # noqa: N802
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "invalid json"})
        prompt = str(data.get("prompt") or "")[:MAX_PROMPT]
        if not prompt.strip():
            return self._json(400, {"error": "empty prompt"})
        timeout = min(int(data.get("timeout") or 120), MAX_TIMEOUT)
        self._json(200, {"answer": run_claude(prompt, timeout)})

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("mw-claude-proxy: " + fmt % args + "\n")


class UnixHTTPServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def get_request(self):
        # BaseHTTPRequestHandler 는 (host, port) 형태의 주소를 기대한다.
        return super().get_request()[0], ("localhost", 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default=DEFAULT_SOCKET)
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.socket), exist_ok=True)
    if os.path.exists(args.socket):
        os.unlink(args.socket)                       # 이전 실행의 잔여 소켓
    server = UnixHTTPServer(args.socket, Handler)
    os.chmod(args.socket, 0o660)                     # 소유자·그룹만 (컨테이너는 root)
    print(f"mw-claude-proxy: listening on {args.socket} (claude={CLAUDE_BIN})",
          file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if os.path.exists(args.socket):
            os.unlink(args.socket)


if __name__ == "__main__":
    main()
