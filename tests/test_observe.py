import json
from pathlib import Path
import tempfile
import unittest

from deck.observe import Rollout, Titles, match_title


class ObserveTests(unittest.TestCase):
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
