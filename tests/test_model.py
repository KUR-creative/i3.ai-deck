from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deck.i3 import focus_command, pair_for
from deck.model import Model, next_attention


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        config = root / 'workspaces.conf'
        config.write_text('\n'.join(f'set ${side}{n} {n + offset}:label'
                                   for n in range(1, 11)
                                   for side, offset in [('left', 10), ('right', 0)]))
        self.model = Model(root, config)
        self.log = root / 'rollout.jsonl'
        self.log.write_text('{"type":"event_msg","payload":'
                            '{"type":"task_complete","turn_id":"t"}}\n')

    def process(self):
        return {'s': dict(pid=100, cwd='/tmp/project', path=self.log)}

    def window(self, number=3, focused=False):
        return dict(con_id=123, title='⠸ agent | project', number=number,
                    workspace=str(number), focused=focused)

    def test_pairs_and_move_follow_current_location(self):
        model = self.model
        model.titles.names['s'] = 'agent'
        model.reconcile(self.process(), [self.window()])
        row = next(r for r in model.snapshot()['rows'] if r['id'] == 's')
        self.assertEqual(row['pair'], 'F3/3')
        self.assertTrue(row['unread'])
        model.reconcile(self.process(), [self.window(18)])
        row = next(r for r in model.snapshot()['rows'] if r['id'] == 's')
        self.assertEqual(row['pair'], 'F8/8')
        self.assertEqual(focus_command(pair_for(18, model.pairs), 123),
                         'workspace --no-auto-back-and-forth number 18; '
                         'workspace --no-auto-back-and-forth number 8; [con_id=123] focus')
        with patch.object(model, 'refresh'), patch('deck.i3.focus') as focus:
            model.navigate('s')
            focus.assert_called_once_with(model.pairs[7], 123)

    def test_only_actual_focus_clears_completion_and_exit_goes_last(self):
        model = self.model
        model.titles.names['s'] = 'agent'
        model.reconcile(self.process(), [self.window()])
        self.assertTrue(model.sessions['s']['unread'])
        model.reconcile(self.process(), [self.window(focused=True)])
        self.assertFalse(model.sessions['s']['unread'])
        model.reconcile({}, [])
        rows = model.snapshot()['rows']
        self.assertEqual(len([r for r in rows if r['kind'] == 'empty']), 10)
        self.assertEqual(rows[-1]['state'], 'exited')

    def test_duplicate_title_does_not_guess(self):
        model = self.model
        model.titles.names.update(s='agent', other='agent')
        live = self.process()
        live['other'] = live['s']
        model.reconcile(live, [self.window()])
        self.assertFalse(model.sessions['s']['located'])

    def test_next_attention_skips_empty_working_exited_and_wraps(self):
        rows = [dict(id='empty', state='empty'),
                dict(id='done', state='done', unread=True, located=True, alive=True),
                dict(id='work', state='working', located=True, alive=True),
                dict(id='wait', state='waiting', located=True, alive=True)]
        self.assertEqual(next_attention(rows, 'done'), 'wait')
        self.assertEqual(next_attention(rows, 'wait'), 'done')
        self.assertIsNone(next_attention(rows[:1], 'empty'))


if __name__ == '__main__':
    unittest.main()
