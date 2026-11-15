import json
from pathlib import Path
import tempfile
import unittest

from deck.observe import Rollout, Titles, match_title


def question(call_id='q', count=2):
    return {'type': 'response_item', 'payload': {
        'type': 'function_call', 'name': 'functions.request_user_input_async',
        'call_id': call_id, 'arguments': json.dumps({'questions': [{}] * count})}}


def answer(call_id, *indices):
    replies = [dict(answer='yes', questionItemId=json.dumps(
        ['request_user_input_async', call_id, index])) for index in indices]
    return {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
        'content': [{'type': 'input_text', 'text': '<send_user_message_question_reply>\n'
                    + json.dumps(replies) + '\n</send_user_message_question_reply>'}]}}


def output(call_id, **result):
    return {'type': 'response_item', 'payload': {'type': 'function_call_output',
            'call_id': call_id, 'output': json.dumps(result)}}


def event(kind, **fields):
    return {'type': 'event_msg', 'payload': dict(type=kind, **fields)}


class ObserveTests(unittest.TestCase):
    def test_async_receipt_and_partial_answers_preserve_wait_until_answered(self):
        state = Rollout()
        state.apply(event('task_started'))
        state.apply(question())
        state.apply(output('q', accepted=True))
        self.assertEqual(state.state, 'waiting')
        state.apply(answer('other', 0, 1))
        state.apply(answer('q', 0))
        self.assertEqual(state.state, 'waiting')
        state.apply(answer('q', 1))
        self.assertEqual(state.state, 'working')
        self.assertEqual(state.questions, {})

    def test_unanswered_question_ui_closes_at_turn_end_without_a_user_reply(self):
        state = Rollout()
        state.apply(event('task_started'))
        state.apply(question())
        state.apply(output('q', accepted=True))
        self.assertEqual(state.state, 'waiting')
        state.apply(event('task_complete', turn_id='turn-1'))
        self.assertEqual((state.state, state.completion, state.questions), ('done', 'turn-1', {}))
        state.apply(answer('q', 0, 1))  # A late reply must not resurrect waiting/run.
        self.assertEqual(state.state, 'done')
        state.apply(event('task_started'))
        self.assertEqual(state.state, 'working')

    def test_new_turn_discards_old_pending_question(self):
        state = Rollout()
        state.apply(question())
        state.apply(event('task_started'))
        self.assertEqual((state.state, state.questions), ('working', {}))

    def test_concurrent_questions_rejection_and_abort(self):
        state = Rollout()
        state.apply(event('task_started'))
        state.apply(question('a', 1))
        state.apply(question('b', 1))
        state.apply(output('other', accepted=False))
        state.apply(answer('a', 0))
        self.assertEqual(state.state, 'waiting')
        state.apply(output('b', accepted=False))
        self.assertEqual(state.state, 'working')
        state.apply(question('c'))
        state.apply(event('turn_aborted'))
        state.apply(answer('c', 0, 1))
        self.assertEqual(state.state, 'idle')
        self.assertEqual(state.questions, {})

    def test_answered_async_question_is_not_resurrected_by_log_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'rollout.jsonl'
            items = [event('task_started'), question(), output('q', accepted=True),
                     answer('q', 0), answer('q', 1)]
            path.write_text(''.join(json.dumps(item) + '\n' for item in items[:-1]))
            state = Rollout()
            state.update(path)
            self.assertEqual(state.state, 'waiting')
            with path.open('a') as stream:
                stream.write(json.dumps(items[-1]) + '\n')
            state.update(path)
            fresh = Rollout()
            fresh.update(path)
            self.assertEqual(fresh.state, 'working')
            self.assertEqual((state.state, state.questions), (fresh.state, fresh.questions))

    def test_restart_does_not_restore_question_from_a_completed_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'rollout.jsonl'
            items = [event('task_started'), question(), output('q', accepted=True),
                     event('task_complete', turn_id='finished'), event('task_started')]
            path.write_text(''.join(json.dumps(item) + '\n' for item in items))
            state = Rollout()
            state.update(path)
            self.assertEqual((state.state, state.completion, state.questions),
                             ('working', 'finished', {}))

    def test_malformed_or_unrelated_replies_cannot_clear_questions(self):
        state = Rollout()
        state.apply(question())
        invalid = [answer('q', 99), answer('q', '0'), output('q', accepted=True)]
        for text in ['?', '<send_user_message_question_reply>{bad}</send_user_message_question_reply>',
                     '<send_user_message_question_reply>[]</send_user_message_question_reply>']:
            invalid.append({'type': 'response_item', 'payload': {'type': 'message',
                'role': 'user', 'content': [{'text': text}]}})
        for item in invalid:
            state.apply(item)
            self.assertEqual(state.state, 'waiting')
        self.assertEqual(state.questions, {'q': {0, 1}})
        state.apply(answer('q', 0, 1))
        state.apply(question('empty', 0))
        bad = question('bad')
        bad['payload']['arguments'] = '{'
        state.apply(bad)
        self.assertEqual(state.questions, {})

    def test_partial_write_and_incremental_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'rollout.jsonl'
            start = json.dumps({'type': 'event_msg', 'payload': {'type': 'task_started'}})
            done = json.dumps({'type': 'event_msg', 'payload': {
                'type': 'task_complete', 'turn_id': 'turn-1'}})
            path.write_text(start + '\n' + done[:20])
            state = Rollout()
            state.update(path)
            self.assertEqual(state.state, 'working')
            with path.open('a') as stream:
                stream.write(done[20:] + '\n')
            state.update(path)
            self.assertEqual((state.state, state.completion), ('done', 'turn-1'))
            state.update(path)
            self.assertEqual(state.completion, 'turn-1')

    def test_explicit_question_and_resolution(self):
        state = Rollout()
        state.apply({'type': 'response_item', 'payload': {
            'type': 'function_call', 'name': 'request_user_input', 'call_id': 'q'}})
        self.assertEqual(state.state, 'waiting')
        state.apply({'type': 'response_item', 'payload': {
            'type': 'function_call_output', 'call_id': 'q'}})
        self.assertEqual(state.state, 'working')

    def test_rename_and_index_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session_index.jsonl'
            path.write_text('{"id":"s","thread_name":"first"}\n')
            titles = Titles(Path(tmp))
            titles.update()
            with path.open('a') as stream:
                stream.write('{"id":"s","thread_name":"renamed"}\n')
            titles.update()
            self.assertEqual(titles.names['s'], 'renamed')
            other = Path(tmp) / 'replacement'
            other.write_text('{"id":"s","thread_name":"new"}\n')
            other.replace(path)
            titles.update()
            self.assertEqual(titles.names['s'], 'new')

    def test_title_is_not_a_substring_or_project_guess(self):
        self.assertTrue(match_title('한글 작업', '⠸ 한글 작업 | kur — codex '))
        self.assertTrue(match_title('한글 작업', '한글 작업 | kur — codex '))
        self.assertFalse(match_title('작업', '한글 작업 | kur — codex '))
        self.assertFalse(match_title('kur', '한글 작업 | kur — codex '))


if __name__ == '__main__':
    unittest.main()
