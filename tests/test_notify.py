import unittest
import sys
import threading
from unittest.mock import Mock, patch

from deck.notify import Actions, Completions, command


class NotificationTests(unittest.TestCase):
    def session(self, **changes):
        return dict(dict(id='s', name='i3 알림 설정하기', slot=3,
                         alive=True, completion=None), **changes)

    def test_one_notification_per_new_turn_not_per_snapshot_or_client(self):
        tracker = Completions()
        self.assertEqual(tracker.collect([self.session(completion='old')]), [])
        self.assertEqual(tracker.collect([self.session(completion='old')]), [])
        self.assertEqual(len(tracker.collect([self.session(completion='new')])), 1)
        self.assertEqual(tracker.collect([self.session(completion='new')]), [])
        self.assertEqual(len(tracker.collect([self.session(completion='next')])), 1)
        self.assertEqual(tracker.collect([self.session(alive=False, completion='exit')]), [])

    def test_focused_completion_is_suppressed_without_replaying_after_leaving(self):
        tracker = Completions()
        tracker.collect([self.session(completion='old')])
        self.assertEqual(tracker.collect([self.session(completion='new', focused=True)]), [])
        self.assertEqual(tracker.collect([self.session(completion='new', focused=False)]), [])
        self.assertEqual(len(tracker.collect([self.session(completion='next', focused=False)])), 1)

    def test_other_agent_in_same_pair_still_notifies(self):
        tracker = Completions()
        tracker.collect([self.session(completion='old'), self.session(id='other', completion='old')])
        sent = tracker.collect([self.session(completion='new', focused=True),
                                self.session(id='other', completion='new', focused=False)])
        self.assertEqual([sid for sid, _ in sent], ['other'])

    def test_pair_and_title_use_requested_style(self):
        args = command(self.session())
        self.assertEqual(args[:7], ['dunstify', '-a', 'Codex', '-u', 'normal', '-t', '0'])
        self.assertIn('string:bgcolor:#86EFAC', args)
        self.assertIn('string:fgcolor:#052E16', args)
        self.assertEqual(args[-1], '3: i3 알림 설정하기')
        self.assertEqual(len(args), 12)  # Summary only, no separate body.
        self.assertEqual(command(self.session(slot=10))[-1], '0: i3 알림 설정하기')

    def test_plain_summary_truncates_and_normalizes_whitespace(self):
        body = command(self.session(name='<b> &\n' + '가' * 100))[-1]
        self.assertTrue(body.startswith('3: <b> & '))
        self.assertTrue(body.endswith('…'))
        self.assertNotIn('\n', body)
        self.assertNotIn('가' * 21, body)
        self.assertTrue(command(self.session(slot=None))[-1].startswith('?: '))

    def test_notification_uses_arguments_without_shell(self):
        args = command(self.session(name='$(touch unwanted)'))
        process = Mock(returncode=0)
        process.stdout.readline.return_value = '101\n'
        process.stdout.read.return_value = 'default\n'
        process.stderr.read.return_value = ''
        process.poll.return_value = 0
        actions = Actions(Mock())
        with patch('deck.notify.subprocess.Popen', return_value=process) as run:
            actions.send('s', args).join(1)
        self.assertIn('--action=default,이동', run.call_args.args[0])
        self.assertIn('--printid', run.call_args.args[0])
        self.assertNotIn('shell', run.call_args.kwargs)
        self.assertEqual(list(actions.clicked()), ['s'])
        self.assertEqual(list(actions.clicked()), [])
        actions.close()

    def test_dismissal_replaced_clicks_and_exited_sessions_do_not_navigate(self):
        first, second = Mock(returncode=0), Mock(returncode=0)
        first.stdout.readline.return_value = '101\n'
        second.stdout.readline.return_value = '102\n'
        first.stdout.read.return_value = 'default\n'
        first.stderr.read.return_value = ''
        second.stdout.read.return_value = ''
        second.stderr.read.return_value = ''
        first.poll.return_value = second.poll.return_value = 0
        actions = Actions(Mock())
        with patch('deck.notify.subprocess.Popen', side_effect=[first, second]):
            actions.send('s', command(self.session())).join(1)
            actions.send('s', command(self.session())).join(1)
        self.assertEqual(list(actions.clicked()), [])
        actions.events.put(('s', actions.pending['s']))
        actions.prune(set())
        self.assertEqual(list(actions.clicked()), [])
        actions.close()

    def test_shutdown_stops_pending_waiters(self):
        process = Mock()
        process.poll.return_value = None
        actions = Actions(Mock())
        actions.pending['s'] = dict(process=process, id=None, dismissed=False)
        actions.close()
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=.5)
        self.assertIsNone(actions.send('s', command(self.session())))

    def test_failed_sender_is_logged_without_navigation(self):
        process = Mock(returncode=1)
        process.stdout.readline.return_value = ''
        process.stdout.read.return_value = ''
        process.stderr.read.return_value = '액션 수신 실패\n'
        process.poll.return_value = 1
        actions = Actions(Mock())
        with patch('deck.notify.subprocess.Popen', return_value=process), \
                patch('deck.notify.sys.stderr') as log:
            actions.send('s', command(self.session())).join(1)
            self.assertIn('액션 수신 실패', ''.join(c.args[0] for c in log.write.call_args_list))
        self.assertEqual(list(actions.clicked()), [])
        actions.close()

    def test_real_child_action_and_shutdown(self):
        wake = threading.Event()
        actions = Actions(wake.set)
        # Python 자식 프로세스로 알림 ID와 액션의 파이프 수신만 검증한다.
        args = [sys.executable, '-c', "print('101', flush=True); print('default', flush=True)"]
        def launch(argv, **kwargs):
            return original([argv[0], *argv[3:]], **kwargs)
        import subprocess
        original = subprocess.Popen
        try:
            with patch('deck.notify.subprocess.Popen', side_effect=launch):
                worker = actions.send('original-session', args)
                self.assertTrue(wake.wait(3))
                worker.join(1)
                self.assertEqual(list(actions.clicked()), ['original-session'])
                worker = actions.send('pending', [sys.executable, '-c',
                                                   'import time; time.sleep(60)'])
                process = actions.pending['pending']['process']
                actions.close()
                worker.join(1)
                self.assertIsNotNone(process.poll())
                self.assertFalse(worker.is_alive())
                self.assertEqual(list(actions.clicked()), [])
        finally:
            actions.close()

    def test_focus_closes_only_that_sessions_notification(self):
        actions = Actions(Mock())
        ready, closed = {}, {}
        def sender(notification_id):
            process = Mock(returncode=0)
            process.stdout.readline.return_value = notification_id + '\n'
            process.poll.return_value = 0
            ready[notification_id], closed[notification_id] = threading.Event(), threading.Event()
            def finish():
                ready[notification_id].set()
                self.assertTrue(closed[notification_id].wait(3))
                return ''
            process.stdout.read.side_effect = finish
            process.stderr.read.return_value = ''
            return process
        first, other = sender('101'), sender('102')
        with patch('deck.notify.subprocess.Popen', side_effect=[first, other]), \
                patch.object(actions, 'close_notification', side_effect=lambda n: closed[n].set()) as close:
            a = actions.send('s', command(self.session()))
            b = actions.send('other', command(self.session(id='other')))
            try:
                self.assertTrue(ready['101'].wait(1) and ready['102'].wait(1))
                actions.dismiss('s')
                a.join(1)
                close.assert_called_once_with('101')
                self.assertIn('other', actions.pending)
                self.assertEqual(list(actions.clicked()), [])
            finally:
                actions.close()
                a.join(1); b.join(1)

    def test_close_uses_only_the_given_notification_id(self):
        with patch('deck.notify.subprocess.run') as close:
            Actions.close_notification('101')
        self.assertEqual(close.call_args.args[0], ['dunstify', '--close', '101'])
        self.assertTrue(close.call_args.kwargs['check'])
        self.assertNotIn('shell', close.call_args.kwargs)

    def test_focus_before_id_arrives_does_not_close_a_new_notification(self):
        actions = Actions(Mock())
        release = threading.Event()
        first, second = Mock(returncode=0), Mock(returncode=0)
        def delayed_id():
            self.assertTrue(release.wait(3))
            return '101\n'
        first.stdout.readline.side_effect = delayed_id
        second.stdout.readline.return_value = '102\n'
        first.stdout.read.return_value = 'default\n'
        first.stderr.read.return_value = ''
        second.stdout.read.return_value = 'default\n'
        second.stderr.read.return_value = ''
        first.poll.return_value = second.poll.return_value = 0
        with patch('deck.notify.subprocess.Popen', side_effect=[first, second]), \
                patch.object(actions, 'close_notification') as close:
            a = actions.send('s', command(self.session()))
            actions.dismiss('s')
            b = actions.send('s', command(self.session()))
            b.join(1)
            release.set()
            a.join(1)
            close.assert_called_once_with('101')
            self.assertEqual(list(actions.clicked()), ['s'])
            actions.close()


if __name__ == '__main__':
    unittest.main()
