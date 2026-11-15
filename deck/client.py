"""Client-side RPC and optional background server startup."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from .protocol import LIMIT


def default_socket():
    base = Path(os.environ.get('XDG_RUNTIME_DIR', Path.home() / '.cache'))
    return base / 'i3-ai-deck' / 'deck.sock'


class Client:
    def __init__(self, path, timeout=8):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(timeout)
        try:
            self.socket.connect(str(path))
        except OSError:
            self.socket.close()
            raise
        self.stream = self.socket.makefile('rwb')

    def request(self, action='snapshot', **params):
        self.stream.write(json.dumps(dict(action=action, **params)).encode() + b'\n')
        self.stream.flush()
        data = self.stream.readline(LIMIT)
        if not data or not data.endswith(b'\n'):
            raise ConnectionError('서버 연결이 끊겼습니다.')
        reply = json.loads(data)
        if not reply.get('ok'):
            raise ValueError(reply.get('error', '서버 오류'))
        return reply.get('data')

    def close(self):
        try:
            self.stream.close()
        finally:
            self.socket.close()


def connect(path, start=True):
    try:
        return Client(path)
    except OSError:
        if not start:
            raise
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    log = os.open(path.parent / 'server.log', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / 'ai_deck.py'),
                          '--server', '--socket', str(path)],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True, close_fds=True)
    finally:
        os.close(log)
    for _ in range(50):
        try:
            return Client(path)
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f'서버를 시작할 수 없습니다. 로그: {path.parent / "server.log"}')


