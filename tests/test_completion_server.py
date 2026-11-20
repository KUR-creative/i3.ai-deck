from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from deck.client import Client
from deck.server import serve


class CompletionServerTests(unittest.TestCase):
    def test_background_observer_sends_once_with_two_clients(self):
        class Model:
            def __init__(self):
                self.sessions = {'s': dict(id='s', alive=True, slot=3,
                                          name='완료 알림 테스트', completion='old')}
                self.sessions['other'] = dict(id='other', alive=True, slot=3,
                                             name='같은 쌍 다른 세션', completion='old')
                self.refreshed = threading.Event()
                self.refresh_count = 0

            def refresh(self):
                self.observed_completion = self.sessions['s']['completion']
                self.refresh_count += 1
                self.refreshed.set()

            def snapshot(self):
                return dict(rows=list(self.sessions.values()), error='')

            def navigate(self, sid):
                self.moved = sid

        model, sent = Model(), []
        watcher = Mock(stdout=iter([]))
        watcher.poll.return_value = 0
        alerts = Mock()
        clicks = []
        alerts.clicked.side_effect = lambda: [clicks.pop(0)] if clicks else []
        alerts.send.side_effect = lambda sid, args: sent.append((sid, args))
        with tempfile.TemporaryDirectory() as tmp, \
                patch('deck.server.Model', return_value=model), \
                patch('deck.server.subprocess.Popen', return_value=watcher), \
                patch('deck.server.Actions', return_value=alerts):
            path = Path(tmp) / 'deck.sock'
            thread = threading.Thread(target=serve, args=(path,), daemon=True)
            thread.start()
            self.assertTrue(model.refreshed.wait(3))
            a, b = Client(path), Client(path)
            try:
                a.request(); b.request()
                self.assertEqual(sent, [])  # No replay of the old completion.
                model.sessions['s']['completion'] = 'new'
                deadline = time.monotonic() + 3
                while not sent and time.monotonic() < deadline:
                    a.request(); b.request()
                    time.sleep(0.02)
                self.assertEqual(len(sent), 1)
                self.assertEqual(sent[0][0], 's')
                self.assertEqual(sent[0][1][-1], '3: 완료 알림 테스트')
                for _ in range(3):
                    a.request(); b.request()
                self.assertEqual(len(sent), 1)
                model.sessions['s']['slot'] = 8  # Agent moved after its notification.
                clicks.append('s')
                deadline = time.monotonic() + 3
                while not hasattr(model, 'moved') and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertEqual(model.moved, 's')
                model.sessions['s'].update(focused=True, seen='new', completion='focused-new')
                deadline = time.monotonic() + 3
                while model.observed_completion != 'focused-new' and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertEqual(model.observed_completion, 'focused-new')
                a.request()  # The model lock confirms collection finished after refresh.
                self.assertEqual(len(sent), 1)
                model.sessions['s']['focused'] = False
                previous_count = model.refresh_count
                deadline = time.monotonic() + 3
                while model.refresh_count == previous_count and time.monotonic() < deadline:
                    time.sleep(.02)
                a.request()
                self.assertEqual(len(sent), 1)  # Leaving must not replay the suppressed alert.
                model.sessions['s']['completion'] = 'after-focus'
                deadline = time.monotonic() + 3
                while len(sent) < 2 and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertEqual(len(sent), 2)
                alerts.dismiss.reset_mock()
                # A brief visit already ended before polling; remember_focus retained seen.
                model.sessions['s']['seen'] = 'after-focus'
                deadline = time.monotonic() + 3
                while not alerts.dismiss.called and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(alerts.dismiss.called)
                self.assertTrue(all(call.args == ('s',) for call in alerts.dismiss.call_args_list))
                a.request('stop')
                thread.join(3)
                self.assertFalse(thread.is_alive())
                alerts.close.assert_called_once_with()
            finally:
                if thread.is_alive():
                    a.request('stop')
                    thread.join(3)
                a.close(); b.close()


if __name__ == '__main__':
    unittest.main()
