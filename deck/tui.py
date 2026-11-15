"""A compact curses list. Selection belongs to this client, state to the server."""
import curses
import time

from .model import next_attention
from .text import fit


LABELS = dict(working='● 작업 중', waiting='? 질문', done='✓ 완료', idle='· 유휴',
              exited='× 종료', unknown='? 확인 불가', empty='· 빈 쌍', unmapped='? 연결 불명')


def run(screen, client):
    curses.curs_set(0)
    screen.keypad(True)
    screen.timeout(100)
    curses.set_escdelay(25)
    curses.mouseinterval(0)  # Handle press/release explicitly, without double-click delay.
    curses.mousemask(curses.ALL_MOUSE_EVENTS)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        for number, color in enumerate((curses.COLOR_GREEN, curses.COLOR_YELLOW,
                                        curses.COLOR_GREEN, curses.COLOR_WHITE), 1):
            curses.init_pair(number, color, -1)
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)
    selected, top, message = None, 0, ''
    rows, agents, error, last_poll = [], [], '', 0
    current_slot = None
    attention_cursor = None

    def navigate(sid):
        nonlocal message, last_poll
        try:
            client.request('focus', id=sid)
            message = ''
        except ValueError as problem:
            message = str(problem)
        last_poll = 0

    while True:
        if time.monotonic() - last_poll >= 0.3:
            snapshot = client.request()
            rows, error = snapshot['rows'], snapshot['error']
            agents = snapshot['agents']
            current_slot = snapshot.get('current_slot')
            if selected not in {row['id'] for row in rows}:
                selected = rows[0]['id'] if rows else None
            last_poll = time.monotonic()
        height, width = screen.getmaxyx()
        visible = max(1, height - 3)
        index = next((i for i, row in enumerate(rows) if row['id'] == selected), 0)
        top = min(top, max(0, len(rows) - visible))
        if index < top:
            top = index
        elif index >= top + visible:
            top = index - visible + 1
        screen.erase()

        def put(y, text, attr=0, x=0):
            if 0 <= y < height and width - x > 1:
                try:
                    screen.addstr(y, x, fit(text, width - x - 1), attr)
                except curses.error:
                    pass

        current = f'현재 F{current_slot}/{current_slot % 10}' if current_slot else '현재 쌍 확인 중'
        put(0, f'i3.ai-deck  {current}', curses.A_BOLD)
        for line, row in enumerate(rows[top:top + visible], 1):
            empty = row['state'] in ('empty', 'exited')
            color = {'working': 1, 'waiting': 2, 'done': 3}.get(row['state'], 4)
            status_attr = curses.color_pair(color) if curses.has_colors() else 0
            attr = 0
            if empty:
                attr = curses.A_DIM
            if row['id'] == selected:
                attr |= curses.A_REVERSE
            badge = '!' if row.get('unread') else ' '
            location = ' [위치 불명]' if row['kind'] == 'agent' and not row['located'] \
                and row.get('alive') else ''
            extra = f' (+{row["count"] - 1})' if row.get('count', 1) > 1 else ''
            if row.get('attention_count'):
                extra += f' [확인 {row["attention_count"]}]'
            put(line, f'{row["pair"]:6} {badge}{LABELS[row["state"]]}  '
                      f'{row["name"]}{extra}{location}', attr)
            if not empty:
                put(line, f'{badge}{LABELS[row["state"]]}',
                    status_attr | (curses.A_REVERSE if row['id'] == selected else 0), x=7)
            if row.get('slot') == current_slot and row['id'].startswith('pair:'):
                highlight = curses.A_BOLD | (curses.color_pair(5) if curses.has_colors()
                                             else curses.A_STANDOUT)
                put(line, f'{row["pair"]:6}', highlight)
        put(height - 2, message or error, curses.A_BOLD)
        put(height - 1, 'j/k 이동 · g/G 처음/끝 · Enter 열기 · n 다음 확인 · 클릭 열기 · q 닫기')
        screen.refresh()
        key = screen.getch()
        if key in (ord('q'), 27):
            return
        if key in (ord('j'), curses.KEY_DOWN, ord('k'), curses.KEY_UP) and rows:
            delta = 1 if key in (ord('j'), curses.KEY_DOWN) else -1
            selected = rows[min(max(0, index + delta), len(rows) - 1)]['id']
            attention_cursor = None
        elif key in (ord('g'), ord('G')) and rows:
            selected = rows[0 if key == ord('g') else -1]['id']
            attention_cursor = None
        elif key in (10, 13, curses.KEY_ENTER) and selected:
            attention_cursor = next((r.get('target') for r in rows if r['id'] == selected), None)
            navigate(selected)
        elif key == ord('n'):
            current = attention_cursor or next(
                (r.get('target') for r in rows if r['id'] == selected), None)
            target = next_attention(agents, current)
            if target:
                attention_cursor = target
                selected = next((r['id'] for r in rows if target in r.get('member_ids', [])
                                 or r['id'] == target), selected)
                navigate(target)
            else:
                message = '다음 확인 대상이 없습니다.'
        elif key == curses.KEY_MOUSE:
            try:
                _, _, y, _, buttons = curses.getmouse()
            except curses.error:
                continue
            if buttons & curses.BUTTON4_PRESSED and rows:
                selected = rows[max(0, index - 3)]['id']
                attention_cursor = None
            elif buttons & getattr(curses, 'BUTTON5_PRESSED', 0) and rows:
                selected = rows[min(len(rows) - 1, index + 3)]['id']
                attention_cursor = None
            elif buttons & (curses.BUTTON1_PRESSED | curses.BUTTON1_RELEASED |
                            curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED):
                target = top + y - 1
                if 1 <= y <= visible and 0 <= target < len(rows):
                    selected = rows[target]['id']
                    attention_cursor = rows[target].get('target')
                    # VTE may consume the first press to focus an inactive terminal.
                    # A release alone must work; press+release must navigate once.
                    if not buttons & curses.BUTTON1_PRESSED:
                        navigate(selected)
