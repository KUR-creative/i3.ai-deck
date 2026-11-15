from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, call, patch

from deck.connection import ReconnectingClient


def snapshot(name='first'):
    return dict(rows=[dict(id='s', name=name, focused=True)], agents=[], error='',
                current_slot=3, current_number=3)


class ConnectionTests(unittest.TestCase):
    def test_disconnect_keeps_snapshot_and_reconnect_never_replays_actions(self):
        old, new = Mock(), Mock()
        original = snapshot()
        old.request.side_effect = [original, ConnectionResetError()]
        new.request.return_value = snapshot('second')
        link = ReconnectingClient(Path('/unused'), old)
        self.assertTrue(link.request()['connected'])
        with patch('deck.connection.time.monotonic', return_value=10), \
                patch('deck.connection.Client', return_value=new) as connect:
            waiting = link.request()
            self.assertFalse(waiting['connected'])
            self.assertEqual(waiting['rows'][0]['name'], 'first')
            self.assertFalse(waiting['rows'][0]['focused'])
            self.assertIsNone(waiting['current_slot'])
            self.assertTrue(original['rows'][0]['focused'])
            with self.assertRaisesRegex(ValueError, '저장하지 않습니다'):
                link.request('focus', id='s')
            link.request()
            connect.assert_not_called()
        with patch('deck.connection.time.monotonic', return_value=12), \
                patch('deck.connection.Client', return_value=new):
            fresh = link.request()
        self.assertTrue(fresh['connected'])
        self.assertEqual(fresh['rows'][0]['name'], 'second')
        self.assertEqual(new.request.call_args_list, [call('snapshot')])
        link.close()

    def test_inflight_failed_focus_is_not_retried(self):
        old, new = Mock(), Mock()
        old.request.side_effect = BrokenPipeError()
        new.request.return_value = snapshot()
        link = ReconnectingClient(Path('/unused'), old)
        with self.assertRaisesRegex(ValueError, '자동 재전송하지 않습니다'):
            link.request('focus', id='s')
        with patch('deck.connection.time.monotonic', return_value=time.monotonic() + 2), \
                patch('deck.connection.Client', return_value=new):
            link.request()
        self.assertEqual(new.request.call_args_list, [call('snapshot')])
        link.close()

    def test_initial_missing_server_returns_waiting_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            link = ReconnectingClient(Path(tmp) / 'missing.sock')
            self.assertFalse(link.request()['connected'])
            self.assertEqual(link.request()['rows'], [])
            link.close()
