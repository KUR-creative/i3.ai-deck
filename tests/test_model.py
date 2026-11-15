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
        self.assertEqual(row['pair'], '[3]')
        self.assertTrue(row['unread'])
        model.reconcile(self.process(), [self.window(18)])
        row = next(r for r in model.snapshot()['rows'] if r.get('target') == 's')
        self.assertEqual(row['pair'], '[8]')
        self.assertEqual(focus_command(pair_for(18, model.pairs), 123),
                         'workspace --no-auto-back-and-forth number "18:label"; '
                         'workspace --no-auto-back-and-forth number "8:label"; [con_id=123] focus')
        with patch.object(model, 'refresh'), patch('deck.i3.focus') as focus:
            model.navigate('s')
            focus.assert_called_once_with(model.pairs[7], 123)

    def test_each_agent_has_a_stable_row_and_empty_workspaces_remain(self):
        model = self.model
        model.titles.names.update(s='agent', other='second')
        live = self.process()
        live['other'] = dict(live['s'], pid=200)
        other = dict(self.window(focused=True), con_id=456, title='second | project')
        model.reconcile(live, [self.window(), other])
        rows = model.snapshot()['rows']
        self.assertEqual(len(rows), 21)
        agents = [r for r in rows if r['slot'] == 3 and r['kind'] == 'agent']
        self.assertEqual([r['name'] for r in agents], ['agent', 'second'])
        self.assertEqual([r['id'] for r in agents if r['focused']], ['other'])
        self.assertEqual(next_attention(model.snapshot()['agents'], 'other'), 's')
        model.reconcile(live, [self.window(), dict(other, focused=False)])
        agents = [r for r in model.snapshot()['rows'] if r['kind'] == 'agent']
        self.assertEqual([r['name'] for r in agents], ['agent', 'second'])
        self.assertFalse(any(r['focused'] for r in agents))
        with patch.object(model, 'refresh'), patch('deck.i3.focus') as focus:
            model.navigate('other')
            focus.assert_called_once_with(model.pairs[2], 456)

    def test_only_actual_focus_clears_completion_and_exit_hides_the_row(self):
        model = self.model
        model.titles.names['s'] = 'agent'
        model.reconcile(self.process(), [self.window()])
        self.assertTrue(model.sessions['s']['unread'])
        model.reconcile(self.process(), [self.window(focused=True)])
        self.assertFalse(model.sessions['s']['unread'])
        model.reconcile({}, [])
        rows = model.snapshot()['rows']
        self.assertEqual(len([r for r in rows if r['kind'] == 'empty']), 20)
        self.assertEqual(len(rows), 20)
        self.assertFalse(any(r['id'] == 's' for r in rows))
        self.assertFalse(model.sessions['s']['alive'])

    def test_brief_focus_acknowledges_without_reordering_or_replacing_titles(self):
        model = self.model
        model.titles.names.update(s='agent', other='second')
        live = self.process()
        live['other'] = dict(live['s'], pid=200)
        other = dict(self.window(), con_id=456, title='second | project')
        model.reconcile(live, [self.window(), other])
        model.remember_focus(456)
        model.remember_focus(999)  # TUI regains focus before the next snapshot.
        model.reconcile(live, [self.window(), other])
        rows = [r for r in model.snapshot()['rows'] if r['kind'] == 'agent']
        self.assertEqual([r['name'] for r in rows], ['agent', 'second'])
        self.assertFalse(model.sessions['other']['unread'])
        # Moving a window preserves the session identity in the destination pair.
        model.reconcile(live, [self.window(4), dict(other, number=4)])
        row = next(r for r in model.snapshot()['rows'] if r['id'] == 'other')
        self.assertEqual(row['name'], 'second')
        self.assertEqual(row['pair'], '[4]')

    def test_next_only_selects_until_explicit_navigation_acknowledges(self):
        model = self.model
        model.titles.names.update(s='agent', other='second')
        live = self.process()
        live['other'] = dict(live['s'], pid=200)
        other = dict(self.window(focused=True), con_id=456, title='second | project')
        model.reconcile(live, [self.window(), other])
        model.remember_focus(456)
        with patch.object(model, 'refresh') as refresh, patch('deck.i3.focus') as focus:
            focus.side_effect = lambda pair, con_id: model.remember_focus(con_id)
            result = model.select_next('other')
            self.assertEqual(result['target'], 's')
            self.assertTrue(refresh.called)
            focus.assert_not_called()
            self.assertTrue(model.sessions['s']['unread'])
            model.navigate(result['target'])
            self.assertFalse(model.sessions['s']['unread'])
            self.assertIsNone(model.select_next('s')['target'])

    def test_next_from_empty_workspace_respects_current_list_position(self):
        model = self.model
        model.titles.names['s'] = 'agent'
        model.reconcile(self.process(), [self.window(3)])
        with patch.object(model, 'refresh'), patch('deck.i3.focus') as focus:
            self.assertEqual(model.select_next('workspace:12')['target'], 's')
            focus.assert_not_called()

    def test_duplicate_title_does_not_guess(self):
        model = self.model
        model.titles.names.update(s='agent', other='agent')
        live = self.process()
        live['other'] = live['s']
        model.reconcile(live, [self.window()])
        self.assertFalse(model.sessions['s']['located'])
        row = next(r for r in model.snapshot()['rows'] if r['id'] == 'workspace:3')
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
            if row.get('number') in (2, 3):
                self.assertEqual(row['state'], 'unmapped')

    def test_current_pair_comes_from_actual_focused_workspace(self):
        model = self.model
        visible = [dict(num=13, visible=True, focused=False),
                   dict(num=3, visible=True, focused=True)]
        with patch('deck.model.discover', return_value={}), patch('deck.i3.ipc') as ipc:
            ipc.side_effect = [dict(nodes=[]), visible]
            model.refresh()
        self.assertEqual(model.snapshot()['current_slot'], 3)
        self.assertEqual(model.snapshot()['current_number'], 3)
        self.assertEqual(model.snapshot()['visible_slots'], [3])

    def test_next_attention_skips_empty_working_exited_and_wraps(self):
        rows = [dict(id='empty', state='empty'),
                dict(id='done', state='done', unread=True, located=True, alive=True),
                dict(id='work', state='working', located=True, alive=True),
                dict(id='wait', state='waiting', located=True, alive=True)]
        self.assertEqual(next_attention(rows, 'done'), 'wait')
        self.assertEqual(next_attention(rows, 'wait'), 'done')
        self.assertEqual(next_attention(rows, 'wait', reverse=True), 'done')
        self.assertEqual(next_attention(rows, 'done', reverse=True), 'wait')
        self.assertEqual(next_attention(rows, None, reverse=True), 'wait')
        self.assertIsNone(next_attention(rows[:1], 'empty'))

    def test_zero_pair_first_left_before_right_and_empty_side_navigation(self):
        model = self.model
        rows = model.snapshot()['rows']
        self.assertEqual([(r['pair'], r['workspace_label']) for r in rows[:4]],
                         [('[0]', 'F0'), ('[0]', '0'), ('[1]', 'F1'), ('[1]', '1')])
        with patch.object(model, 'refresh'), patch('deck.i3.focus') as focus:
            model.navigate('workspace:20')
            focus.assert_called_once_with(model.pairs[9], workspace_number=20)


if __name__ == '__main__':
    unittest.main()
