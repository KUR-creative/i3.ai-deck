"""Discover live Codex processes and incrementally read their local rollouts."""
import json
import os
from pathlib import Path
import re


def records(path, offset=0):
    """Consume only complete JSONL lines; leave partial writes for next time."""
    with path.open('rb') as stream:
        stream.seek(offset)
        while line := stream.readline():
            if not line.endswith(b'\n'):
                break
            offset = stream.tell()
            try:
                yield offset, json.loads(line)
            except (ValueError, UnicodeDecodeError):
                yield offset, {}


def discover(proc=Path('/proc')):
    """Open rollout FDs identify sessions without scanning historical logs."""
    found = {}
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            if (process / 'exe').resolve().name != 'codex':
                continue
            paths = set()
            for fd in (process / 'fd').iterdir():
                try:
                    target = os.readlink(fd)
                    if '/rollout-' in target and target.endswith('.jsonl'):
                        paths.add(Path(target))
                except OSError:
                    pass
            primary = []
            for path in paths:
                try:
                    with path.open('rb') as stream:
                        meta = json.loads(stream.readline()).get('payload', {})
                    if meta.get('source') == 'cli' and meta.get('id'):
                        primary.append((path.stat().st_mtime_ns, path, meta))
                except (OSError, ValueError):
                    continue
            if primary:
                # A resumed CLI can retain an old FD; use its latest user rollout.
                _, path, meta = max(primary, key=lambda item: item[0])
                found[meta['id']] = dict(path=path, pid=int(process.name),
                                         cwd=meta.get('cwd', ''))
        except OSError:
            continue
    return found


class Titles:
    def __init__(self, home):
        self.path = home / 'session_index.jsonl'
        self.offset = 0
        self.names = {}
        self.identity = None

    def update(self):
        try:
            stat = self.path.stat()
            if self.identity != stat.st_ino or stat.st_size < self.offset:
                self.offset = 0
                self.names.clear()
            self.identity = stat.st_ino
            for self.offset, item in records(self.path, self.offset):
                if item.get('id') and item.get('thread_name'):
                    self.names[item['id']] = item['thread_name']
        except OSError:
            pass


class Rollout:
    def __init__(self):
        self.offset = 0
        self.identity = None
        self.state = 'unknown'
        self.completion = None
        self.pending_question = None

    def update(self, path):
        stat = path.stat()
        if self.identity != (str(path), stat.st_ino) or stat.st_size < self.offset:
            self.__init__()
        self.identity = (str(path), stat.st_ino)
        for self.offset, item in records(path, self.offset):
            self.apply(item)

    def apply(self, item):
        payload = item.get('payload', {})
        kind = payload.get('type')
        if item.get('type') == 'event_msg':
            if kind == 'task_started':
                self.state = 'working'
                self.pending_question = None
            elif kind == 'task_complete':
                self.state = 'done'
                self.completion = payload.get('turn_id') or item.get('timestamp')
                self.pending_question = None
            elif kind in ('turn_aborted', 'task_aborted'):
                self.state = 'idle'
                self.pending_question = None
        elif item.get('type') == 'response_item':
            # Only an explicit pending request_user_input is evidence of a question.
            name = payload.get('name', '').split('.')[-1]
            if kind == 'function_call' and name == 'request_user_input':
                self.pending_question = payload.get('call_id')
                self.state = 'waiting'
            elif (kind == 'function_call_output' and self.pending_question
                  and payload.get('call_id') == self.pending_question):
                self.pending_question = None
                self.state = 'working'


def match_title(name, window_title):
    """Codex's title is '<optional activity glyph> thread name | directory'."""
    # Match a whole title component, never a substring or just a project folder.
    first = window_title.split(' | ', 1)[0].strip()
    if first == name:
        return True
    return bool(re.fullmatch(r'[^\w\s]+\s+' + re.escape(name), first))
