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


def decode_json(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


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
            for path in paths:
                try:
                    with path.open('rb') as stream:
                        meta = json.loads(stream.readline()).get('payload', {})
                    source = meta.get('source')
                    user_thread = meta.get('thread_source') == 'user'
                    legacy_user = 'thread_source' not in meta and source in ('cli', 'vscode')
                    if (user_thread or legacy_user) and isinstance(source, str) and meta.get('id'):
                        # Resuming keeps the original source (including 'vscode').
                        # A shared backend may hold several live user rollouts.
                        found[meta['id']] = dict(path=path, pid=int(process.name),
                                                 cwd=meta.get('cwd', ''))
                except (OSError, ValueError):
                    continue
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
        self.activity = 'unknown'
        self.completion = None
        self.questions = {}  # call_id -> None (synchronous) or unanswered async indices

    def update(self, path):
        stat = path.stat()
        if self.identity != (str(path), stat.st_ino) or stat.st_size < self.offset:
            self.__init__()
        self.identity = (str(path), stat.st_ino)
        for self.offset, item in records(path, self.offset):
            self.apply(item)

    def apply(self, item):
        payload = item.get('payload', {})
        if not isinstance(payload, dict):
            return
        kind = payload.get('type')
        if item.get('type') == 'event_msg':
            if kind == 'task_started':
                self.activity = 'working'
                self.questions.clear()
            elif kind == 'task_complete':
                self.activity = 'done'
                self.completion = payload.get('turn_id') or item.get('timestamp')
                # Codex TUI closes even unanswered async prompts at live turn end.
                # Clearing the UI's wait does not imply that the user answered.
                self.questions.clear()
            elif kind in ('turn_aborted', 'task_aborted'):
                self.activity = 'idle'
                self.questions.clear()
        elif item.get('type') == 'response_item':
            name = payload.get('name', '').split('.')[-1]
            call_id = payload.get('call_id')
            if kind == 'function_call' and isinstance(call_id, str) and call_id:
                if name == 'request_user_input':
                    self.questions[call_id] = None
                elif name == 'request_user_input_async':
                    args = decode_json(payload.get('arguments'))
                    questions = args.get('questions') if isinstance(args, dict) else None
                    if isinstance(questions, list) and questions:
                        self.questions[call_id] = set(range(len(questions)))
            elif kind == 'function_call_output' and isinstance(call_id, str) \
                    and call_id in self.questions:
                if self.questions[call_id] is None:
                    del self.questions[call_id]
                    self.activity = 'working'
                else:
                    result = decode_json(payload.get('output'))
                    if isinstance(result, dict) and result.get('accepted') is False:
                        del self.questions[call_id]
            elif kind == 'message' and payload.get('role') == 'user':
                self.answer_questions(payload.get('content', []))
        self.state = 'waiting' if self.questions else self.activity

    def answer_questions(self, content):
        for part in content if isinstance(content, list) else []:
            text = part.get('text') if isinstance(part, dict) else None
            if not isinstance(text, str):
                continue
            start, end = '<send_user_message_question_reply>', '</send_user_message_question_reply>'
            text = text.strip()
            if not (text.startswith(start) and text.endswith(end)):
                continue
            replies = decode_json(text[len(start):-len(end)])
            for reply in replies if isinstance(replies, list) else []:
                if not isinstance(reply, dict) or 'answer' not in reply:
                    continue
                key = decode_json(reply.get('questionItemId'))
                if not (isinstance(key, list) and len(key) == 3
                        and key[0] == 'request_user_input_async'
                        and isinstance(key[1], str) and type(key[2]) is int):
                    continue
                pending = self.questions.get(key[1])
                if pending is not None:
                    pending.discard(key[2])
                    if not pending:
                        del self.questions[key[1]]


def match_title(name, window_title):
    """Codex's title is '<optional activity glyph> thread name | directory'."""
    # Match a whole title component, never a substring or just a project folder.
    first = window_title.split(' | ', 1)[0].strip()
    if first == name:
        return True
    return bool(re.fullmatch(r'[^\w\s]+\s+' + re.escape(name), first))


def working_title(title):
    """Codex's live working title starts with an animated braille spinner."""
    return bool(re.match(r'^[\u2800-\u28ff]\s', title))
