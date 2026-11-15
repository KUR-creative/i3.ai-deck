import json
from pathlib import Path
import tempfile
import unittest

from deck.model import Model
from deck.notify import Completions
from deck.observe import discover


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.proc = self.root / 'proc'
        self.proc.mkdir()
        self.exe = self.root / 'bin/codex'
        self.exe.parent.mkdir()
        self.exe.touch()

    def rollout(self, pid, sid, source='cli', thread_source='user', cwd='/home/user'):
        process = self.proc / str(pid)
        if not process.exists():
            (process / 'fd').mkdir(parents=True)
            (process / 'exe').symlink_to(self.exe)
        log = self.root / f'rollout-{sid}.jsonl'
        log.write_text(json.dumps(dict(type='session_meta', payload=dict(
            id=sid, source=source, thread_source=thread_source, cwd=cwd))) + '\n'
            + '{"type":"event_msg","payload":{"type":"task_started"}}\n')
        (process / 'fd' / str(len(list((process / 'fd').iterdir())))).symlink_to(log)
        return log

    def test_resumed_user_session_preserves_vscode_origin_and_non_home_cwd(self):
        self.rollout(100, 'resumed', source='vscode', cwd='/home/user/.config/i3')
        found = discover(self.proc)
        self.assertIn('resumed', found)
        self.assertEqual(found['resumed']['cwd'], '/home/user/.config/i3')

    def test_shared_backend_keeps_all_user_sessions_but_not_guardians(self):
        self.rollout(100, 'a')
        self.rollout(100, 'b', source='vscode')
        self.rollout(100, 'guardian', source={'subagent': {'other': 'guardian'}},
                     thread_source='guardian_review')
        self.rollout(100, 'review', thread_source='guardian_review')
        self.assertEqual(set(discover(self.proc)), {'a', 'b'})

    def test_three_sessions_in_pair_are_located_and_notify_independently(self):
        paths = [self.rollout(100, 'a', source='vscode', cwd='/projects/i3'),
                 self.rollout(100, 'b'), self.rollout(101, 'c')]
        names = dict(a='i3 설정', b='다른 에이전트', c='i3.ai-deck')
        (self.root / 'session_index.jsonl').write_text(''.join(
            json.dumps(dict(id=sid, thread_name=name)) + '\n' for sid, name in names.items()))
        config = self.root / 'workspaces.conf'
        config.write_text('\n'.join(f'set ${side}{n} {n + offset}:name'
                                   for n in range(1, 11)
                                   for side, offset in [('left', 10), ('right', 0)]))
        model = Model(self.root, config)
        model.titles.update()
        windows = [dict(con_id=n, title=name + ' | project', focused=False,
                        number=20 if n < 3 else 10, workspace='20:F10' if n < 3 else '10:0')
                   for n, name in enumerate(names.values(), 1)]
        live = discover(self.proc)
        model.reconcile(live, windows)
        agents = model.snapshot()['agents']
        self.assertEqual({s['name'] for s in agents}, set(names.values()))
        self.assertTrue(all(s['slot'] == 10 and s['located'] for s in agents))
        notifications = Completions()
        self.assertEqual(notifications.collect(model.sessions.values()), [])
        for n, path in enumerate(paths):
            with path.open('a') as stream:
                stream.write(json.dumps(dict(type='event_msg', payload=dict(
                    type='task_complete', turn_id=f'turn-{n}'))) + '\n')
        model.reconcile(live, windows)
        sent = notifications.collect(model.sessions.values())
        self.assertEqual(len(sent), 3)
        for name in names.values():
            self.assertTrue(any(name in args[-1] for args in sent))
        self.assertEqual(notifications.collect(model.sessions.values()), [])


if __name__ == '__main__':
    unittest.main()
