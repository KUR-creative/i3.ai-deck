import unittest
from unittest.mock import patch

from deck.notify import Completions, command, send


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

    def test_pair_and_title_use_requested_style(self):
        args = command(self.session())
        self.assertEqual(args[:7], ['notify-send', '-a', 'Codex', '-u', 'normal', '-t', '0'])
        self.assertIn('string:bgcolor:#86EFAC', args)
        self.assertIn('string:fgcolor:#052E16', args)
        self.assertIn('3번 쌍 완료\ni3 알림 설정하기', args[-1])

    def test_truncation_escapes_markup_and_normalizes_whitespace(self):
        body = command(self.session(name='<b> &\n' + '가' * 100))[-1]
        self.assertIn('&lt;b&gt; &amp; ', body)
        self.assertIn('…</b></span>', body)
        self.assertNotIn('가' * 21, body)
        self.assertIn('위치 미확인', command(self.session(slot=None))[-1])

    def test_notification_uses_arguments_without_shell(self):
        args = command(self.session(name='$(touch unwanted)'))
        with patch('deck.notify.subprocess.run') as run:
            send(args)
        self.assertEqual(run.call_args.args, (args,))
        self.assertNotIn('shell', run.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
