"""One local observer, shared by any number of terminal clients."""
import fcntl
import json
import os
import socketserver
import subprocess
import sys
import threading

from .model import Model
from .notify import Actions, Completions
from .protocol import LIMIT


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
                    elif action == 'next':
                        result = self.server.model.select_next(request.get('after'),
                                                               reverse=bool(request.get('reverse')),
                                                               all_states=bool(request.get('all_states')))
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
        completions = Completions()
        alerts = Actions(changed.set)

        def observe():
            while not stopped.is_set():
                try:
                    for sid in alerts.clicked():
                        try:
                            with server.model_lock:
                                model.navigate(sid)
                        except (OSError, RuntimeError, ValueError) as error:
                            print(f'알림 이동 실패: {error}', file=sys.stderr, flush=True)
                    with server.model_lock:
                        model.refresh()
                        commands = completions.collect(model.sessions.values())
                        alive = {sid for sid, s in model.sessions.items() if s.get('alive')}
                    # Desktop I/O must not block clients holding the model lock.
                    alerts.prune(alive)
                    for sid, command in commands:
                        try:
                            alerts.send(sid, command)
                        except (OSError, subprocess.SubprocessError) as error:
                            print(f'완료 알림 실패: {error}', file=sys.stderr, flush=True)
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
                for line in watcher.stdout:
                    if stopped.is_set():
                        break
                    try:
                        event = json.loads(line)
                        if event.get('change') == 'focus' and event.get('container', {}).get('id'):
                            with server.model_lock:
                                model.remember_focus(event['container']['id'])
                    except (ValueError, AttributeError):
                        pass
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
            alerts.close()
            if watcher and watcher.poll() is None:
                watcher.terminate()
                watcher.wait(timeout=3)
            server.server_close()
            path.unlink(missing_ok=True)
