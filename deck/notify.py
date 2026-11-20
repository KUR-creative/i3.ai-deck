"""One completion notification per observed turn, owned by the server."""
import queue
import subprocess
import sys
import threading

from .text import fit


def command(session):
    title = ' '.join(''.join(c for c in session['name'] if c.isprintable() or c.isspace()).split())
    short = fit(title, 40)
    if short != title:
        short = fit(title, 39) + '…'
    slot = session.get('slot')
    destination = str(slot % 10) if slot is not None else '?'
    # Notification summaries are plain text; no body or font-size markup.
    summary = f'{destination}: {short}'
    return ['dunstify', '-a', 'Codex', '-u', 'normal', '-t', '0',
            '-h', 'string:bgcolor:#86EFAC', '-h', 'string:fgcolor:#052E16', summary]


class Completions:
    def __init__(self):
        self.observed = {}

    def collect(self, sessions):
        commands = []
        for session in sessions:
            if not session.get('alive') or not session.get('initialized', True):
                continue
            sid, token = session['id'], session.get('completion')
            if (sid in self.observed and token and token != self.observed[sid]
                    and not session.get('focused')):
                commands.append((sid, command(session)))
            # Initial discovery establishes a baseline, without replaying old completions.
            self.observed[sid] = token
        return commands


class Actions:
    """At most one waiting dunstify per session; clicks retain the session ID."""
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
        self.dismiss(sid)
        # 개별 ID를 써서 이전 알림의 늦은 닫기 요청이 새 알림을 닫지 않게 한다.
        action_args = [args[0], '--printid', '--action=default,이동', *args[1:]]
        with self.lock:
            if self.closed:
                return
            process = subprocess.Popen(action_args, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            notice = dict(process=process, id=None, dismissed=False)
            self.pending[sid] = notice

        def wait():
            first = process.stdout.readline().strip()
            if first.isdecimal():
                with self.lock:
                    notice['id'] = first
                    dismissed = notice['dismissed']
                if dismissed:
                    self.close_notification(first)
            # ID를 읽은 같은 스트림에서 나머지 결과도 읽어 버퍼의 액션을 놓치지 않는다.
            output = process.stdout.read()
            error = process.stderr.read()
            process.wait()
            process.stdout.close()
            process.stderr.close()
            with self.lock:
                notice['id'] = None
            if process.returncode == 0 and output.strip() == 'default':
                self.events.put((sid, notice))
                self.wake()
            elif process.returncode > 0:
                print(f'완료 알림 실패: {error.strip() or process.returncode}',
                      file=sys.stderr, flush=True)

        worker = threading.Thread(target=wait, daemon=True)
        worker.start()
        return worker

    def clicked(self):
        while True:
            try:
                sid, notice = self.events.get_nowait()
            except queue.Empty:
                return
            with self.lock:
                valid = self.pending.get(sid) is notice
            if valid:
                yield sid

    def prune(self, alive):
        with self.lock:
            removed = [sid for sid in self.pending if sid not in alive]
        for sid in removed:
            self.dismiss(sid)

    @staticmethod
    def close_notification(notification_id):
        try:
            subprocess.run(['dunstify', '--close', notification_id], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError) as error:
            print(f'알림 닫기 실패: {error}', file=sys.stderr, flush=True)

    def dismiss(self, sid):
        with self.lock:
            notice = self.pending.pop(sid, None)
            if notice is None:
                return
            notice['dismissed'] = True
            notification_id = notice['id']
        if notification_id:
            self.close_notification(notification_id)

    def close(self):
        with self.lock:
            self.closed = True
            pending = list(self.pending.items())
        for sid, notice in pending:
            self.dismiss(sid)
            self.stop(notice['process'])
