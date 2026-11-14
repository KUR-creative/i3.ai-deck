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
                                   for side, offset in [('left', 10), ('right', 0)])
                          + '\nbindcode $mod+Shift+87 ' + chr(92) + '\n')
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
        row = next(r for r in model.snapshot()['rows'] if r.get('target') == 's')
        self.assertEqual(row['pair'], 'F3/3')
        self.assertTrue(row['unread'])
        model.reconcile(self.process(), [self.window(18)])
        row = next(r for r in model.snapshot()['rows'] if r.get('target') == 's')
        self.assertEqual(row['pair'], 'F8/8')
        self.assertEqual(focus_command(pair_for(18, model.pairs), 123),
                         'workspace --no-auto-back-and-forth number "18:label"; '
                         'workspace --no-auto-back-and-forth number "8:label"; [con_id=123] focus')
        with patch.object(model, 'refresh'), patch('deck.i3.focus') as focus:
            model.navigate('s')
            focus.assert_called_once_with(model.pairs[7], 123)

    def test_one_row_per_pair_tracks_focused_agent_and_hidden_attention(self):
        model = self.model
        model.titles.names.update(s='agent', other='second')
        live = self.process()
        live['other'] = dict(live['s'], pid=200)
        other = dict(self.window(focused=True), con_id=456, title='second | project')
        model.reconcile(live, [self.window(), other])
        rows = model.snapshot()['rows']
        self.assertEqual(len(rows), 10)
        row = next(r for r in rows if r['id'] == 'pair:3')
        self.assertEqual((row['name'], row['count']), ('second', 2))
        self.assertEqual(row['attention_count'], 1)
        self.assertEqual(next_attention(model.snapshot()['agents'], 'other'), 's')
        model.reconcile(live, [self.window(), dict(other, focused=False)])
        row = next(r for r in model.snapshot()['rows'] if r['id'] == 'pair:3')
        self.assertEqual(row['name'], 'second')  # Retain when the TUI gains focus.
        with patch.object(model, 'refresh'), patch('deck.i3.focus') as focus:
            model.navigate('pair:3')
            focus.assert_called_once_with(model.pairs[2], 456)

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
        row = next(r for r in model.snapshot()['rows'] if r['id'] == 'pair:3')
        self.assertEqual(row['state'], 'unmapped')

    def test_working_title_distinguishes_a_dormant_duplicate(self):
        model = self.model
        model.titles.names['s'] = 'agent'
        self.log.write_text('{"type":"event_msg","payload":{"type":"task_started"}}\n')
        dormant = dict(self.window(2), con_id=456, title='agent | project')
        model.reconcile(self.process(), [self.window(), dormant])
        self.assertEqual(model.sessions['s']['con_id'], 123)
        self.assertEqual(model.sessions['s']['slot'], 3)
        # Finishing removes the spinner; the observed window identity survives.
        model.reconcile(self.process(), [dict(self.window(), title='agent | project'), dormant])
        self.assertEqual(model.sessions['s']['con_id'], 123)

    def test_ambiguous_static_titles_are_not_called_empty(self):
        model = self.model
        model.titles.names['s'] = 'agent'
        a = dict(self.window(3), title='agent | project')
        b = dict(a, con_id=456, number=2)
        model.reconcile(self.process(), [a, b])
        self.assertFalse(model.sessions['s']['located'])
        for row in model.snapshot()['rows']:
            if row['slot'] in (2, 3):
                self.assertEqual(row['state'], 'unmapped')

    def test_current_pair_comes_from_actual_focused_workspace(self):
        model = self.model
        visible = [dict(num=13, visible=True, focused=False),
                   dict(num=3, visible=True, focused=True)]
        with patch('deck.model.discover', return_value={}), patch('deck.i3.ipc') as ipc:
            ipc.side_effect = [dict(nodes=[]), visible]
            model.refresh()
        self.assertEqual(model.snapshot()['current_slot'], 3)
        self.assertEqual(model.snapshot()['visible_slots'], [3])

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
