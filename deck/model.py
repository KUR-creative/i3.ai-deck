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
        self.focused = {}
        self.focus_sequence = 0
        self.last_focus = None
        self.current_slot = None
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
            session.update(workspace=window['workspace'] if window else '',
                           number=window['number'] if window else -1)
            pair = i3.pair_for(session['number'], self.pairs)
            session['slot'] = pair['slot'] if pair else None
            session['located'] = window is not None
            if window and window['focused']:
                session['seen'] = state.completion
            session['unread'] = (state.state == 'done' and state.completion is not None
                                 and state.completion != session['seen'])
        for sid, session in self.sessions.items():
            if sid not in live:
                session.update(alive=False, state='exited', unread=False, located=False)
                self.rollouts.pop(sid, None)

    def remember_focus(self, con_id):
        """Retain brief focus visits even if the next snapshot is already on the TUI."""
        self.focus_sequence += 1
        self.focused[con_id] = self.focus_sequence
        self.last_focus = con_id
        for session in self.sessions.values():
            if session.get('alive') and session['con_id'] == con_id and session['state'] == 'done':
                session['seen'] = session['completion']
                session['unread'] = False

    def snapshot(self):
        rows = []
        active = [s for s in self.sessions.values() if s.get('alive')]
        agents = []
        for pair in self.pairs:
            members = sorted((s for s in active if s['slot'] == pair['slot']),
                             key=lambda s: s['order'])
            if members:
                agents.extend(dict(s, pair=pair['label']) for s in members)
                representative = max(members, key=lambda s: self.focused.get(s['con_id'], 0))
                rows.append(dict(representative, id=f'pair:{pair["slot"]}', kind='pair',
                                 target=representative['id'], pair=pair['label'],
                                 member_ids=[s['id'] for s in members], count=len(members),
                                 attention_count=sum(needs_attention(s) for s in members),
                                 unread=any(s['unread'] for s in members)))
            else:
                possible = [s for s in active if not s['located']
                            and pair['slot'] in s.get('candidate_slots', [])]
                rows.append(dict(id=f'pair:{pair["slot"]}', kind='empty',
                                 slot=pair['slot'], pair=pair['label'],
                                 name=possible[0]['name'] if possible else '에이전트 없음',
                                 state='unmapped' if possible else 'empty',
                                 unread=False, located=True, target=None))
        unplaced = [dict(s, pair='?', kind='agent', target=s['id'])
                    for s in active if s['slot'] is None]
        rows.extend(unplaced)
        agents.extend(unplaced)
        rows.extend(dict(s, pair='종료', kind='agent') for s in self.sessions.values()
                    if not s.get('alive'))
        return dict(rows=rows, agents=agents, error=self.error,
                    current_slot=self.current_slot, visible_slots=self.visible_slots)

    def navigate(self, sid):
        # Read the latest location before constructing a command, even if re-sorted.
        self.refresh()

        if sid.startswith('pair:'):
            slot = int(sid.split(':')[1])
            pair = next(pair for pair in self.pairs if pair['slot'] == slot)
            row = next(row for row in self.snapshot()['rows'] if row['id'] == sid)
            sid = row['target']
            if sid is None:
                i3.focus(pair)
        if sid is not None:
            session = self.sessions.get(sid)
            if not session or not session['alive'] or not session['located']:
                raise ValueError('이 세션의 i3 창을 확인할 수 없습니다.')
            i3.focus(i3.pair_for(session['number'], self.pairs), session['con_id'])
        self.refresh()

    def navigate_next(self, after=None):
        self.refresh()
        target = next_attention(self.snapshot()['agents'], after)
        if target:
            self.navigate(target)
        return dict(target=target, snapshot=self.snapshot())


def needs_attention(session):
    return bool(session.get('alive') and (
        session['state'] == 'waiting' or session.get('unread')))


def next_attention(rows, selected):
    if not rows:
        return None
    start = next((i for i, row in enumerate(rows) if row['id'] == selected), -1)
    for step in range(1, len(rows) + 1):
        row = rows[(start + step) % len(rows)]
        if row.get('located') and needs_attention(row):
            return row['id']
    return None
