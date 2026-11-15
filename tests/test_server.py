from pathlib import Path
import tempfile
import threading
import unittest

from deck.server import Client, Handler, Server


class FakeModel:
    def __init__(self):
        self.selected = None

    def snapshot(self):
        return dict(rows=[dict(id='agent', seen=self.selected == 'agent')], error='')

    def navigate(self, sid):
        if sid != 'agent':
            raise ValueError('missing agent')
        self.selected = sid

    def select_next(self, after=None):
        target = 'agent' if self.selected is None else None
        return dict(target=target, snapshot=self.snapshot())


class ServerTests(unittest.TestCase):
    def test_clients_share_state_and_error_does_not_disconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'deck.sock'
            with Server(str(path), Handler) as server:
                server.model = FakeModel()
                server.model_lock = threading.Lock()
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                a, b = Client(path), Client(path)
                try:
                    self.assertEqual(a.request(), b.request())
                    with self.assertRaisesRegex(ValueError, 'missing agent'):
                        a.request('focus', id='missing')
                    self.assertEqual(a.request('next')['target'], 'agent')
                    self.assertFalse(b.request()['rows'][0]['seen'])
                    a.request('focus', id='agent')
                    self.assertTrue(b.request()['rows'][0]['seen'])
                    self.assertIsNone(b.request('next', after='agent')['target'])
                    a.close()
                    self.assertTrue(b.request()['rows'][0]['seen'])
                    b.request('stop')
                    thread.join(timeout=3)
                    self.assertFalse(thread.is_alive())
                finally:
                    # Closing a twice is harmless and keeps failure cleanup simple.
                    a.close()
                    b.close()
                    server.shutdown()


if __name__ == '__main__':
    unittest.main()
