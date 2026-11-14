"""One local observer, shared by any number of terminal clients."""
import fcntl
import json
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import threading
import time

from .model import Model


LIMIT = 1024 * 1024


def default_socket():
    base = Path(os.environ.get('XDG_RUNTIME_DIR', Path.home() / '.cache'))
    return base / 'i3-ai-deck' / 'deck.sock'


class Client:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(8)
        self.socket.connect(str(path))
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
        self.stream.close()
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


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(30)
        while data := self.rfile.readline(LIMIT):
            if not data.endswith(b'\n'):
                return
            stop = False
            try:
                request = json.loads(data)
                action = request.get('action')
                with self.server.model_lock:
                    if action == 'snapshot':
                        result = self.server.model.snapshot()
                    elif action == 'focus':
                        self.server.model.navigate(request['id'])
                        result = self.server.model.snapshot()
                    elif action == 'stop':
                        stop, result = True, None
                    else:
                        raise ValueError('알 수 없는 요청')
                reply = dict(ok=True, data=result)
            except Exception as error:
                reply = dict(ok=False, error=str(error))
            try:
                self.wfile.write(json.dumps(reply, ensure_ascii=False).encode() + b'\n')
                self.wfile.flush()
            except (OSError, ValueError):
                return
            if stop:
                self.server.shutdown()
                return


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def serve(path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (path.parent / (path.name + '.lock')).open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # A concurrent client already started the observer.
        model = Model()
        path.unlink(missing_ok=True)
        old_mask = os.umask(0o077)
        try:
            server = Server(str(path), Handler)
        finally:
            os.umask(old_mask)
        server.model = model
        server.model_lock = threading.Lock()
        stopped = threading.Event()
        changed = threading.Event()
        watcher = None

        def observe():
            while not stopped.is_set():
                try:
                    with server.model_lock:
                        model.refresh()
                except Exception as error:
                    with server.model_lock:
                        model.error = str(error)
                changed.wait(1)
                changed.clear()

        def events():
            nonlocal watcher
            try:
                watcher = subprocess.Popen(
                    ['i3-msg', '-m', '-t', 'subscribe', '["window","workspace"]'],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                for _ in watcher.stdout:
                    if stopped.is_set():
                        break
                    changed.set()
            except OSError:
                pass  # Periodic refresh still tracks location if subscription fails.

        threading.Thread(target=observe, daemon=True).start()
        threading.Thread(target=events, daemon=True).start()
        try:
            server.serve_forever(poll_interval=0.2)
        finally:
            stopped.set()
            changed.set()
            if watcher and watcher.poll() is None:
                watcher.terminate()
                watcher.wait(timeout=3)
            server.server_close()
            path.unlink(missing_ok=True)
