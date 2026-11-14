from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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

    def test_all_ten_pairs_preserve_output_assignment_names(self):
        for n, pair in enumerate(self.pairs, 1):
            with self.subTest(slot=n):
                command = focus_command(pair)
                self.assertIn(f'number "{10 + n}:F{n}"', command)
                self.assertIn(f'number "{n}:{n % 10}"', command)
                self.assertLess(command.index(f'{10+n}:F{n}'),
                                command.index(f'{n}:{n % 10}'))

    def test_report_incomplete_pair_switch(self):
        with patch('deck.i3.ipc') as ipc:
            ipc.side_effect = [[{'success': True}, {'success': True}],
                               [{'num': 13, 'visible': True}, {'num': 2, 'visible': True}]]
            with self.assertRaisesRegex(RuntimeError, '쌍 전환 확인 실패'):
                focus(self.pairs[1])


if __name__ == '__main__':
    unittest.main()
