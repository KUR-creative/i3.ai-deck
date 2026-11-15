"""Shared in-memory session state. No terminal output or prompts are saved."""
import os
from pathlib import Path

from . import i3
from .observe import Rollout, Titles, discover, match_title, working_title


class Model:
    def __init__(self, home=None, config=None):
        home = home or Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
        config = config or Path.home() / '.config/i3/config.d/workspaces.conf'
        self.pairs = i3.pairs_from_config(config)
        self.titles = Titles(home)
        self.sessions = {}
        self.rollouts = {}
        self.last_focus = None
        self.current_slot = None
        self.current_number = None
        self.visible_slots = []
        self.error = ''

    def refresh(self):
        self.titles.update()
        live = discover()
        try:
            window_list = i3.windows(i3.ipc('get_tree'))
            workspaces = i3.ipc('get_workspaces')
            self.visible_slots = sorted({pair['slot'] for ws in workspaces
                                         if ws['visible']
                                         and (pair := i3.pair_for(ws['num'], self.pairs))})
            current = next((ws for ws in workspaces if ws['focused']), None)
            self.current_number = current['num'] if current else None
            pair = i3.pair_for(current['num'], self.pairs) if current else None
            self.current_slot = pair['slot'] if pair else None
            self.error = ''
        except (OSError, ValueError, RuntimeError) as error:
            self.error = str(error)
            window_list = []
        self.reconcile(live, window_list)

    def reconcile(self, live, window_list):
        by_id = {window['con_id']: window for window in window_list}
        current = next((w for w in window_list if w['focused']), None)
        if current and current['con_id'] != self.last_focus:
            self.remember_focus(current['con_id'])
        names = self.titles.names
        for sid, process in live.items():
            session = self.sessions.setdefault(sid, dict(
                id=sid, order=len(self.sessions), seen=None, con_id=None))
            session.update(pid=process['pid'], alive=True, cwd=process['cwd'],
                           name=names.get(sid) or Path(process['cwd']).name or sid[:8])
            state = self.rollouts.setdefault(sid, Rollout())
            try:
                state.update(process['path'])
            except (OSError, ValueError):
                state.state = 'unknown'
            session['state'] = state.state
            session['completion'] = state.completion
            # No project/cwd heuristics. Reject duplicate names and window matches.
            unique_name = sum(names.get(other) == names.get(sid) for other in live) == 1
            matching = [window for window in window_list
                        if names.get(sid) and match_title(names[sid], window['title'])]
            candidates = matching if unique_name else []
            if len(candidates) == 1:
                session['con_id'] = candidates[0]['con_id']
            elif (session['con_id'] not in {w['con_id'] for w in candidates}
                  and state.state == 'working'):
                # A dormant terminal can retain the same session title. Only use
                # the unique live working title, never the currently focused window.
                working = [w for w in candidates if working_title(w['title'])]
                if len(working) == 1:
                    session['con_id'] = working[0]['con_id']
            window = by_id.get(session['con_id'])
            session['candidate_slots'] = sorted({pair['slot'] for w in matching
                                                if (pair := i3.pair_for(w['number'], self.pairs))})
            session['candidate_numbers'] = sorted({w['number'] for w in matching})
            session.update(workspace=window['workspace'] if window else '',
                           number=window['number'] if window else -1)
            pair = i3.pair_for(session['number'], self.pairs)
            session['slot'] = pair['slot'] if pair else None
            session['located'] = window is not None
            session['focused'] = bool(window and window['focused'])
            if window and window['focused']:
                session['seen'] = state.completion
            session['unread'] = (state.state == 'done' and state.completion is not None
                                 and state.completion != session['seen'])
        for sid, session in self.sessions.items():
            if sid not in live:
                session.update(alive=False, state='exited', unread=False, located=False)
                self.rollouts.pop(sid, None)

    def remember_focus(self, con_id):
        """Acknowledge brief visits even if the next snapshot is already on the TUI."""
        self.last_focus = con_id
        for session in self.sessions.values():
            if session.get('alive') and session['con_id'] == con_id and session['state'] == 'done':
                session['seen'] = session['completion']
                session['unread'] = False

    def snapshot(self):
        rows = []
        active = [s for s in self.sessions.values() if s.get('alive')]
        agents = []
        for pair in sorted(self.pairs, key=lambda p: p['slot'] % 10):
            label = f'[{pair["slot"] % 10}]'
            for side in ('left', 'right'):
                number = pair[side]
                workspace_label = ('F' if side == 'left' else '') + str(pair['slot'] % 10)
                members = sorted((s for s in active if s['number'] == number),
                                 key=lambda s: s['order'])
                if members:
                    entries = [dict(s, pair=label, workspace_label=workspace_label,
                                    kind='agent', target=s['id']) for s in members]
                    rows.extend(entries)
                    agents.extend(entries)
                else:
                    possible = any(not s['located'] and number in s.get('candidate_numbers', [])
                                   for s in active)
                    rows.append(dict(id=f'workspace:{number}', kind='empty', number=number,
                                     slot=pair['slot'], pair=label, workspace_label=workspace_label,
                                     name='연결 확인 필요' if possible else '에이전트 없음',
                                     state='unmapped' if possible else 'empty',
                                     unread=False, focused=False, located=True, target=None))
        unplaced = [dict(s, pair='[?]', workspace_label='?', kind='agent', target=s['id'])
                    for s in active if s['slot'] is None]
        rows.extend(unplaced)
        agents.extend(unplaced)
        return dict(rows=rows, agents=agents, error=self.error,
                    current_slot=self.current_slot, current_number=self.current_number,
                    visible_slots=self.visible_slots)

    def navigate(self, sid):
        # Read the latest location before constructing a command, even if re-sorted.
        self.refresh()

        if sid.startswith('workspace:'):
            number = int(sid.split(':')[1])
            pair = i3.pair_for(number, self.pairs)
            if pair is None:
                raise ValueError('알 수 없는 워크스페이스입니다.')
            i3.focus(pair, workspace_number=number)
        else:
            session = self.sessions.get(sid)
            if not session or not session['alive'] or not session['located']:
                raise ValueError('이 세션의 i3 창을 확인할 수 없습니다.')
            i3.focus(i3.pair_for(session['number'], self.pairs), session['con_id'])
        self.refresh()

    def select_next(self, after=None, reverse=False):
        self.refresh()
        target = next_attention(self.snapshot()['rows'], after, reverse)
        return dict(target=target, snapshot=self.snapshot())


def needs_attention(session):
    return bool(session.get('alive') and (
        session['state'] == 'waiting' or session.get('unread')))


def next_attention(rows, selected, reverse=False):
    if not rows:
        return None
    start = next((i for i, row in enumerate(rows) if row['id'] == selected), 0 if reverse else -1)
    for step in range(1, len(rows) + 1):
        row = rows[(start + (-step if reverse else step)) % len(rows)]
        if row.get('located') and needs_attention(row):
            return row['id']
    return None
