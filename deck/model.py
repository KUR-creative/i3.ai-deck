"""Shared in-memory session state. No terminal output or prompts are saved."""
import os
from pathlib import Path

from . import i3
from .observe import Rollout, Titles, discover, match_title


class Model:
    def __init__(self, home=None, config=None):
        home = home or Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
        config = config or Path.home() / '.config/i3/config.d/workspaces.conf'
        self.pairs = i3.pairs_from_config(config)
        self.titles = Titles(home)
        self.sessions = {}
        self.rollouts = {}
        self.focused = {}
        self.error = ''

    def refresh(self):
        self.titles.update()
        live = discover()
        try:
            window_list = i3.windows(i3.ipc('get_tree'))
            self.error = ''
        except (OSError, ValueError, RuntimeError) as error:
            self.error = str(error)
            window_list = []
        self.reconcile(live, window_list)

    def reconcile(self, live, window_list):
        by_id = {window['con_id']: window for window in window_list}
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
            candidates = [window for window in window_list
                          if names.get(sid) and unique_name
                          and match_title(names[sid], window['title'])]
            if len(candidates) == 1:
                session['con_id'] = candidates[0]['con_id']
            window = by_id.get(session['con_id'])
            session.update(workspace=window['workspace'] if window else '',
                           number=window['number'] if window else -1)
            pair = i3.pair_for(session['number'], self.pairs)
            session['slot'] = pair['slot'] if pair else None
            session['located'] = window is not None
            if window and window['focused']:
                session['seen'] = state.completion
                if pair and match_title(session['name'], window['title']):
                    self.focused[pair['slot']] = sid
            session['unread'] = (state.state == 'done' and state.completion is not None
                                 and state.completion != session['seen'])
        for sid, session in self.sessions.items():
            if sid not in live:
                session.update(alive=False, state='exited', unread=False, located=False)
                self.rollouts.pop(sid, None)

    def snapshot(self):
        rows = []
        active = [s for s in self.sessions.values() if s.get('alive')]
        agents = []
        for pair in self.pairs:
            members = sorted((s for s in active if s['slot'] == pair['slot']),
                             key=lambda s: s['order'])
            if members:
                agents.extend(dict(s, pair=pair['label']) for s in members)
                representative = next((s for s in members
                                       if s['id'] == self.focused.get(pair['slot'])), members[0])
                rows.append(dict(representative, id=f'pair:{pair["slot"]}', kind='pair',
                                 target=representative['id'], pair=pair['label'],
                                 member_ids=[s['id'] for s in members], count=len(members),
                                 attention_count=sum(needs_attention(s) for s in members),
                                 unread=any(s['unread'] for s in members)))
            else:
                rows.append(dict(id=f'pair:{pair["slot"]}', kind='empty',
                                 slot=pair['slot'], pair=pair['label'], name='에이전트 없음',
                                 state='empty', unread=False, located=True, target=None))
        unplaced = [dict(s, pair='?', kind='agent', target=s['id'])
                    for s in active if s['slot'] is None]
        rows.extend(unplaced)
        agents.extend(unplaced)
        rows.extend(dict(s, pair='종료', kind='agent') for s in self.sessions.values()
                    if not s.get('alive'))
        return dict(rows=rows, agents=agents, error=self.error)

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
