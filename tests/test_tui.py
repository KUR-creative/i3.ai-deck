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
        return dict(error='', agents=[], current_slot=3, rows=[
            dict(id=f'pair:{n}', kind='empty', slot=n, pair=f'F{n}/{n}',
                 state='empty', name='에이전트 없음', located=True, target=None)
            for n in range(1, 4)])


class MouseTests(unittest.TestCase):
    def exercise(self, buttons):
        screen = Screen([curses.KEY_MOUSE] * len(buttons) + [ord('q')])
        client = Client()
        with ExitStack() as stack:
            for name in ('curs_set', 'set_escdelay', 'mouseinterval', 'mousemask'):
                stack.enter_context(patch('deck.tui.curses.' + name))
            stack.enter_context(patch('deck.tui.curses.has_colors', return_value=False))
            stack.enter_context(patch('deck.tui.curses.getmouse',
                                      side_effect=[(0, 4, 2, 0, b) for b in buttons]))
            run(screen, client)
        return client.calls

    def test_first_click_release_without_press(self):
        self.assertEqual(self.exercise([curses.BUTTON1_RELEASED]), ['pair:2'])

    def test_press_release_is_one_navigation(self):
        self.assertEqual(self.exercise([curses.BUTTON1_PRESSED, curses.BUTTON1_RELEASED]),
                         ['pair:2'])

    def test_terminal_click_event_also_works(self):
        self.assertEqual(self.exercise([curses.BUTTON1_CLICKED]), ['pair:2'])


if __name__ == '__main__':
    unittest.main()
