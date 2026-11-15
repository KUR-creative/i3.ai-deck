from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from deck.i3 import focus, focus_command, pairs_from_config


class PairNavigationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        config = Path(self.tmp.name) / 'workspaces.conf'
        config.write_text('\n'.join(
            f'set ${side}{n} {n + offset}:{"F" if offset else ""}{n if offset else n % 10}'
            for n in range(1, 11) for side, offset in [('left', 10), ('right', 0)]))
        self.pairs = pairs_from_config(config)

    def test_all_ten_pairs_use_ws_once_with_display_number(self):
        for n, pair in enumerate(self.pairs, 1):
            with self.subTest(slot=n), patch('deck.i3.subprocess.run') as run, \
                    patch('deck.i3.ipc', return_value=[dict(num=n+10, visible=True),
                                                     dict(num=n, visible=True)]) as ipc:
                focus(pair)
                run.assert_called_once_with([str(Path.home() / '.local/bin/ws'), str(n % 10)],
                                           check=True, capture_output=True, text=True, timeout=10)
                ipc.assert_called_once_with('get_workspaces')

    def test_ws_precedes_exact_agent_focus(self):
        with patch('deck.i3.subprocess.run') as run, patch('deck.i3.ipc') as ipc:
            sequence = Mock()
            sequence.attach_mock(run, 'ws')
            sequence.attach_mock(ipc, 'i3')
            ipc.side_effect = [[dict(success=True)],
                               [dict(num=13, visible=True), dict(num=3, visible=True)]]
            focus(self.pairs[2], con_id=456)
            self.assertEqual(sequence.mock_calls, [
                call.ws([str(Path.home() / '.local/bin/ws'), '3'], check=True,
                        capture_output=True, text=True, timeout=10),
                call.i3('command', '[con_id=456] focus'), call.i3('get_workspaces')])

    def test_report_incomplete_pair_switch(self):
        with patch('deck.i3.subprocess.run'), patch('deck.i3.ipc') as ipc:
            ipc.return_value = [{'num': 13, 'visible': True}, {'num': 2, 'visible': True}]
            with self.assertRaisesRegex(RuntimeError, '쌍 전환 확인 실패'):
                focus(self.pairs[1])

    def test_empty_workspaces_use_ws_then_full_name_of_selected_side(self):
        for pair in self.pairs:
            for side in ('left', 'right'):
                with self.subTest(slot=pair['slot'], side=side), \
                        patch('deck.i3.subprocess.run') as run, patch('deck.i3.ipc') as ipc:
                    ipc.side_effect = [[dict(success=True)],
                                       [dict(num=pair['left'], visible=True),
                                        dict(num=pair['right'], visible=True)]]
                    focus(pair, workspace_number=pair[side])
                    self.assertEqual(run.call_args.args[0][-1], str(pair['slot'] % 10))
                    self.assertEqual(ipc.call_args_list[0], call('command',
                        f'workspace --no-auto-back-and-forth number "{pair[side + "_name"]}"'))

    def test_ws_failure_stops_before_any_direct_i3_command(self):
        errors = [FileNotFoundError('ws missing'),
                  subprocess.CalledProcessError(1, ['ws'], stderr='switch failed'),
                  subprocess.TimeoutExpired(['ws'], 10)]
        for error in errors:
            with self.subTest(error=type(error).__name__), \
                    patch('deck.i3.subprocess.run', side_effect=error), patch('deck.i3.ipc') as ipc:
                with self.assertRaisesRegex(RuntimeError, 'ws 이동 실패'):
                    focus(self.pairs[0], con_id=456)
                ipc.assert_not_called()

    def test_target_focus_failure_is_reported_after_ws(self):
        with patch('deck.i3.subprocess.run') as run, \
                patch('deck.i3.ipc', return_value=[dict(success=False)]) as ipc:
            with self.assertRaisesRegex(RuntimeError, 'i3 이동 실패'):
                focus(self.pairs[0], con_id=456)
            run.assert_called_once()
            ipc.assert_called_once_with('command', '[con_id=456] focus')

    def test_unpaired_window_focus_does_not_invent_a_ws_destination(self):
        with patch('deck.i3.subprocess.run') as run, \
                patch('deck.i3.ipc', return_value=[dict(success=True)]) as ipc:
            focus(con_id=456)
            run.assert_not_called()
            ipc.assert_called_once_with('command', '[con_id=456] focus')

    def test_invalid_destination_is_rejected_before_ws(self):
        with patch('deck.i3.subprocess.run') as run:
            with self.assertRaises(ValueError):
                focus(self.pairs[0], workspace_number=20)
            with self.assertRaises(ValueError):
                focus()
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
