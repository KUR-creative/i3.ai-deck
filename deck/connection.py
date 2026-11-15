"""Keep a TUI alive across server restarts; never replay navigation requests."""
import json
import time

from .server import Client


class ReconnectingClient:
    def __init__(self, path, client=None):
        self.path = path
        self.client = client
        if client:
            client.socket.settimeout(0.2)
        self.retry_at = 0
        self.snapshot = dict(rows=[], agents=[], error='')

    def close(self):
        if self.client:
            try:
                self.client.close()
            except OSError:
                pass
            self.client = None

    def waiting(self):
        return dict(self.snapshot,
                    rows=[dict(row, focused=False) for row in self.snapshot['rows']],
                    current_slot=None, current_number=None, connected=False,
                    error='서버 연결 대기 중 · 마지막 목록')

    def request(self, action='snapshot', **params):
        if self.client is None:
            if action != 'snapshot':
                raise ValueError('서버 연결 대기 중입니다. 이동 요청은 저장하지 않습니다.')
            if time.monotonic() >= self.retry_at:
                self.retry_at = time.monotonic() + 1
                try:
                    self.client = Client(self.path, timeout=0.2)
                except OSError:
                    pass
            if self.client is None:
                return self.waiting()
        try:
            result = self.client.request(action, **params)
        except (OSError, json.JSONDecodeError):
            self.close()
            self.retry_at = time.monotonic() + 1
            if action == 'snapshot':
                return self.waiting()
            raise ValueError('서버 연결이 끊겼습니다. 요청을 자동 재전송하지 않습니다.') from None
        if action == 'snapshot':
            self.snapshot = result
            return dict(result, connected=True)
        if action == 'next':
            self.snapshot = result['snapshot']
        elif action == 'focus':
            self.snapshot = result
        return result
