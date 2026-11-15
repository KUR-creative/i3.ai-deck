import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import ai_deck


class StartServerTests(unittest.TestCase):
    def test_symlink_help_from_another_directory_without_starting_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            link = root / 'ais'
            link.symlink_to(Path(ai_deck.__file__).resolve())
            env = dict(os.environ, XDG_RUNTIME_DIR=str(root / 'runtime'))
            env.pop('PYTHONPATH', None)
            result = subprocess.run([str(link), '-h'], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('usage: ais', result.stdout)
            self.assertIn('ais --start-server', result.stdout)
            self.assertIn('q는 TUI만 닫습니다.', result.stdout)
            self.assertFalse((root / 'runtime').exists())

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
