"""A compact curses list. Selection belongs to this client, state to the server."""
import curses
import time

from .text import fit


LABELS = dict(working='● 작업 중', waiting='? 질문', done='○ 완료', idle='· 유휴',
              exited='× 종료', unknown='? 확인 불가', empty='etc', unmapped='? 연결 불명')


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
    rows, error, last_poll = [], '', 0
    current_slot = None
    current_number = None
    connected = True

    def navigate(sid):
        nonlocal message, last_poll
        if not connected:
            message = '서버 연결 대기 중입니다.'
            return
        try:
            client.request('focus', id=sid)
            message = ''
        except ValueError as problem:
            message = str(problem)
        last_poll = 0

    while True:
        if time.monotonic() - last_poll >= 0.3:
            snapshot = client.request()
            was_connected = connected
            connected = snapshot.get('connected', True)
            if connected and not was_connected:
                message = ''
            rows, error = snapshot['rows'], snapshot['error']
            current_slot = snapshot.get('current_slot')
            current_number = snapshot.get('current_number')
            if selected not in {row['id'] for row in rows}:
                selected = rows[0]['id'] if rows else None
            last_poll = time.monotonic()
        height, width = screen.getmaxyx()
        visible = max(1, height - 2)
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

        previous_pair, previous_number = None, None
        highlight = curses.A_BOLD | (curses.color_pair(5) if curses.has_colors()
                                     else curses.A_STANDOUT)
        for line, row in enumerate(rows[top:top + visible]):
            empty = row['state'] in ('empty', 'exited')
            color = {'working': 1, 'waiting': 2, 'done': 3}.get(row['state'], 4)
            status_attr = curses.color_pair(color) if curses.has_colors() else 0
            attr = 0
            if empty or not connected:
                attr = curses.A_DIM
            if row['id'] == selected:
                attr |= curses.A_REVERSE
            label = LABELS[row['state']]
            if row['state'] == 'done' and row.get('unread'):
                label = '● 완료'
            location = ' [위치 불명]' if row['kind'] == 'agent' and not row['located'] \
                and row.get('alive') else ''
            pair = row['pair'] if row['pair'] != previous_pair else ''
            workspace = row['workspace_label'] if row.get('number') != previous_number or pair else ''
            put(line, ' ' * (width - 1), attr)
            put(line, f'{pair:3} {workspace:>2}', attr)
            put(line, f' {label}', attr, x=9)
            put(line, row['name'] + location, attr, x=23)
            if not empty and connected:
                put(line, f' {label}',
                    status_attr | (curses.A_REVERSE if row['id'] == selected else 0), x=9)
            in_workspace = row['kind'] == 'empty' or (row.get('alive') and row.get('located'))
            if connected and in_workspace and pair and row.get('slot') == current_slot:
                put(line, pair, highlight)
            if connected and in_workspace and workspace and row.get('number') == current_number:
                put(line, f'{workspace:>2}', highlight, x=4)
            if connected and row.get('focused'):
                put(line, '>', highlight, x=7)
            previous_pair, previous_number = row['pair'], row.get('number')
        put(height - 2, (message or error) if connected else error, curses.A_BOLD)
        put(height - 1, 'j/k 선택 · g/G 처음/끝 · n 확인 대상 선택 · N 다음 에이전트 이동 · Enter/클릭 열기 · q 닫기')
        screen.refresh()
        key = screen.getch()
        if key in (ord('q'), 27):
            return
        if key in (ord('j'), curses.KEY_DOWN, ord('k'), curses.KEY_UP) and rows:
            delta = 1 if key in (ord('j'), curses.KEY_DOWN) else -1
            selected = rows[min(max(0, index + delta), len(rows) - 1)]['id']
        elif key in (ord('g'), ord('G')) and rows:
            selected = rows[0 if key == ord('g') else -1]['id']
        elif key in (10, 13, curses.KEY_ENTER) and selected:
            navigate(selected)
        elif key in (ord('n'), ord('N')):
            if not connected:
                message = '서버 연결 대기 중입니다.'
                continue
            try:
                params = dict(after=selected)
                if key == ord('N'):
                    params['all_states'] = True
                result = client.request('next', **params)
            except ValueError as problem:
                message = str(problem)
                continue
            target = result['target']
            snapshot = result['snapshot']
            rows = snapshot['rows']
            current_slot = snapshot.get('current_slot')
            current_number = snapshot.get('current_number')
            last_poll = 0
            if target:
                selected = target
                message = ''
                if key == ord('N'):
                    navigate(target)
            else:
                message = '이동할 에이전트가 없습니다.' if key == ord('N') else '다음 확인 대상이 없습니다.'
        elif key == curses.KEY_MOUSE:
            try:
                _, _, y, _, buttons = curses.getmouse()
            except curses.error:
                continue
            if buttons & curses.BUTTON4_PRESSED and rows:
                selected = rows[max(0, index - 3)]['id']
            elif buttons & getattr(curses, 'BUTTON5_PRESSED', 0) and rows:
                selected = rows[min(len(rows) - 1, index + 3)]['id']
            elif buttons & (curses.BUTTON1_PRESSED | curses.BUTTON1_RELEASED |
                            curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED):
                target = top + y
                if 0 <= y < visible and 0 <= target < len(rows):
                    selected = rows[target]['id']
                    # VTE may consume the first press to focus an inactive terminal.
                    # A release alone must work; press+release must navigate once.
                    if not buttons & curses.BUTTON1_PRESSED:
                        navigate(selected)
