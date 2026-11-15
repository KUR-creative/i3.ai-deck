import sys
import unittest
from unittest.mock import Mock, patch

import ai_deck


class StartServerTests(unittest.TestCase):
    def test_start_server_connects_or_starts_without_entering_tui(self):
        client = Mock()
        with patch.object(sys, 'argv', ['ai_deck.py', '--start-server', '--socket', '/tmp/example']), \
                patch('ai_deck.connect', return_value=client) as connect, \
                patch('ai_deck.curses.wrapper') as tui, patch('builtins.print') as output:
            ai_deck.main()
        self.assertEqual(str(connect.call_args.args[0]), '/tmp/example')
        self.assertTrue(connect.call_args.kwargs['start'])
        client.request.assert_called_once_with()
        client.close.assert_called_once_with()
        tui.assert_not_called()
        output.assert_called_once_with('서버 실행 중: /tmp/example')

    def test_regular_launch_still_starts_server_and_tui(self):
        client, reconnect = Mock(), Mock()
        with patch.object(sys, 'argv', ['ai_deck.py']), \
                patch('ai_deck.connect', return_value=client), \
                patch('ai_deck.ReconnectingClient', return_value=reconnect) as adapter, \
                patch('ai_deck.curses.wrapper') as tui:
            ai_deck.main()
        self.assertEqual(adapter.call_args.args[1], client)
        tui.assert_called_once_with(ai_deck.run, reconnect)
        reconnect.close.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
