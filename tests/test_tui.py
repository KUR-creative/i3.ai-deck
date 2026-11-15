from contextlib import ExitStack
import curses
import unittest
from unittest.mock import patch

from deck.tui import run


class Screen:
    def __init__(self, keys):
        self.keys = iter(keys)
        self.drawn = []

    def keypad(self, value): pass
    def timeout(self, value): pass
    def erase(self): pass
    def refresh(self): pass
    def getmaxyx(self): return 24, 100
    def getch(self): return next(self.keys)
    def addstr(self, *args): self.drawn.append(args)


class Client:
    def __init__(self):
        self.calls = []

    def request(self, action='snapshot', **params):
        if action == 'focus':
            self.calls.append(params['id'])
        rows = [dict(id=sid, kind='agent', slot=10, pair='[0]', number=20,
                     workspace_label='F0', state=state, name=name, located=True,
                     alive=True, focused=sid == 'a', target=sid)
                for sid, state, name in [('a', 'working', 'agent A'), ('b', 'done', 'agent B')]]
        rows.append(dict(id='workspace:10', kind='empty', slot=10, pair='[0]', number=10,
                         workspace_label='0', state='empty', name='에이전트 없음', located=True,
                         focused=False, target=None))
        return dict(error='', agents=rows[:2], current_slot=10, current_number=20, rows=rows)


class MouseTests(unittest.TestCase):
    def run_keys(self, keys, client=None):
        client = client or Client()
        with ExitStack() as stack:
            for name in ('curs_set', 'set_escdelay', 'mouseinterval', 'mousemask'):
                stack.enter_context(patch('deck.tui.curses.' + name))
            stack.enter_context(patch('deck.tui.curses.has_colors', return_value=False))
            run(Screen(keys), client)
        return client.calls

    def test_g_and_G_select_extremes_without_navigating(self):
        self.assertEqual(self.run_keys([ord('G'), ord('g'), ord('q')]), [])
        self.assertEqual(self.run_keys([ord('G'), 10, ord('g'), 10, ord('q')]),
                         ['workspace:10', 'a'])

    def test_n_selects_the_exact_agent_row_from_server_result(self):
        class NextClient(Client):
            def request(self, action='snapshot', **params):
                snapshot = super().request('snapshot')
                if action == 'next':
                    self.calls.append(('next', params['after']))
                    return dict(target='a', snapshot=snapshot)
                if action == 'focus':
                    self.calls.append(params['id'])
                return snapshot

        client = NextClient()
        self.assertEqual(self.run_keys([ord('j'), ord('n'), ord('n'), ord('q')], client),
                         [('next', 'b'), ('next', 'a')])
        client = NextClient()
        self.assertEqual(self.run_keys([ord('j'), ord('n'), 10, ord('q')], client),
                         [('next', 'b'), 'a'])

    def exercise(self, buttons):
        screen = Screen([curses.KEY_MOUSE] * len(buttons) + [ord('q')])
        client = Client()
        with ExitStack() as stack:
            for name in ('curs_set', 'set_escdelay', 'mouseinterval', 'mousemask'):
                stack.enter_context(patch('deck.tui.curses.' + name))
            stack.enter_context(patch('deck.tui.curses.has_colors', return_value=False))
            stack.enter_context(patch('deck.tui.curses.getmouse',
                                      side_effect=[(0, 4, 1, 0, b) for b in buttons]))
            run(screen, client)
        return client.calls

    def test_N_selects_previous_without_navigation(self):
        class PreviousClient(Client):
            def request(self, action='snapshot', **params):
                snapshot = super().request('snapshot')
                if action == 'next':
                    self.calls.append((params['after'], params.get('reverse')))
                    return dict(target='b', snapshot=snapshot)
                return super().request(action, **params)

        self.assertEqual(self.run_keys([ord('N'), 10, ord('q')], PreviousClient()),
                         [('a', True), 'b'])

    def test_waiting_screen_keeps_navigation_keys_but_blocks_server_actions(self):
        class OfflineClient(Client):
            def request(self, action='snapshot', **params):
                if action != 'snapshot':
                    raise AssertionError('Offline actions must not be sent')
                result = super().request()
                result.update(connected=False, error='서버 연결 대기 중')
                return result

        self.assertEqual(self.run_keys([ord('j'), ord('G'), ord('g'), 10,
                                        ord('n'), ord('N'), ord('q')], OfflineClient()), [])

    def test_first_click_release_without_press(self):
        self.assertEqual(self.exercise([curses.BUTTON1_RELEASED]), ['b'])

    def test_press_release_is_one_navigation(self):
        self.assertEqual(self.exercise([curses.BUTTON1_PRESSED, curses.BUTTON1_RELEASED]),
                         ['b'])

    def test_terminal_click_event_also_works(self):
        self.assertEqual(self.exercise([curses.BUTTON1_CLICKED]), ['b'])

    def test_only_current_pair_label_gets_cyan_background(self):
        screen = Screen([ord('q')])
        with ExitStack() as stack:
            for name in ('curs_set', 'set_escdelay', 'mouseinterval', 'mousemask',
                         'start_color', 'use_default_colors', 'init_pair'):
                stack.enter_context(patch('deck.tui.curses.' + name))
            stack.enter_context(patch('deck.tui.curses.has_colors', return_value=True))
            stack.enter_context(patch('deck.tui.curses.color_pair', side_effect=lambda n: n << 8))
            run(screen, Client())
        highlight = (5 << 8) | curses.A_BOLD
        self.assertIn((0, 0, '[0]', highlight), screen.drawn)
        self.assertIn((0, 4, 'F0', highlight), screen.drawn)
        self.assertIn((0, 7, '>', highlight), screen.drawn)
        self.assertTrue(any(y == 1 and x == 9 and '완료' in text and attr == 3 << 8
                            for y, x, text, attr in screen.drawn))
        self.assertFalse(any(y == 1 and attr & (5 << 8) == 5 << 8
                             for y, x, text, attr in screen.drawn))
        self.assertIn((0, 23, 'agent A', curses.A_REVERSE), screen.drawn)
        self.assertIn((1, 23, 'agent B', 0), screen.drawn)
        self.assertFalse(any('현재' in text or '(+2)' in text for _, _, text, _ in screen.drawn))
        self.assertIn((0, 0, '[0] F0', curses.A_REVERSE), screen.drawn)
        self.assertIn((2, 0, '     0', curses.A_DIM), screen.drawn)
        self.assertIn((2, 9, ' etc', curses.A_DIM), screen.drawn)
        self.assertIn((2, 23, '에이전트 없음', curses.A_DIM), screen.drawn)


if __name__ == '__main__':
    unittest.main()
