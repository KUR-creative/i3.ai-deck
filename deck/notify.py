"""One completion notification per observed turn, owned by the server."""
from html import escape
import queue
import subprocess
import threading

from .text import fit


def command(session):
    title = ' '.join(''.join(c for c in session['name'] if c.isprintable() or c.isspace()).split())
    short = fit(title, 40)
    if short != title:
        short = fit(title, 39) + '…'
    slot = session.get('slot')
    destination = f'{slot}번 쌍' if slot else '위치 미확인'
    body = f'<span size="xx-large"><b>{destination} 완료\n{escape(short)}</b></span>'
    return ['notify-send', '-a', 'Codex', '-u', 'normal', '-t', '0',
            '-h', 'string:bgcolor:#86EFAC', '-h', 'string:fgcolor:#052E16', 'Codex', body]


class Completions:
    def __init__(self):
        self.observed = {}

    def collect(self, sessions):
        commands = []
        for session in sessions:
            if not session.get('alive'):
                continue
            sid, token = session['id'], session.get('completion')
            if sid in self.observed and token and token != self.observed[sid]:
                commands.append((sid, command(session)))
            # Initial discovery establishes a baseline, without replaying old completions.
            self.observed[sid] = token
        return commands


class Actions:
    """At most one waiting notify-send per session; clicks retain the session ID."""
    def __init__(self, wake):
        self.wake = wake
        self.pending = {}
        self.events = queue.Queue()
        self.lock = threading.Lock()
        self.closed = False

    @staticmethod
    def stop(process):
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            except ProcessLookupError:
                pass

    def send(self, sid, args):
        action_args = [args[0], '--action=default=이동', '-h',
                       f'string:x-dunst-stack-tag:i3-ai-deck:{sid}', *args[1:]]
        with self.lock:
            if self.closed:
                return
            previous = self.pending.get(sid)
            process = subprocess.Popen(action_args, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            self.pending[sid] = process
        if previous:
            self.stop(previous)

        def wait():
            output, _ = process.communicate()
            if process.returncode == 0 and output.strip() == 'default':
                self.events.put((sid, process))
                self.wake()

        worker = threading.Thread(target=wait, daemon=True)
        worker.start()
        return worker

    def clicked(self):
        while True:
            try:
                sid, process = self.events.get_nowait()
            except queue.Empty:
                return
            with self.lock:
                valid = self.pending.get(sid) is process
            if valid:
                yield sid

    def prune(self, alive):
        with self.lock:
            removed = [self.pending.pop(sid) for sid in list(self.pending) if sid not in alive]
        for process in removed:
            self.stop(process)

    def close(self):
        with self.lock:
            self.closed = True
            pending = list(self.pending.values())
            self.pending.clear()
        for process in pending:
            self.stop(process)
