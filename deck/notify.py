"""One completion notification per observed turn, owned by the server."""
from html import escape
import subprocess

from .text import fit


def command(session):
    title = ' '.join(''.join(c for c in session['name'] if c.isprintable() or c.isspace()).split())
    short = fit(title, 40)
    if short != title:
        short = fit(title, 39) + '…'
    slot = session.get('slot')
    destination = f'{slot}번 쌍' if slot else '위치 미확인'
    body = f'<span size="xx-large"><b>{destination} 완료\n{escape(short)}</b></span>'
    return ['notify-send', '-a', 'Codex', '-u', 'normal', '-t', '0',
            '-h', 'string:bgcolor:#86EFAC', '-h', 'string:fgcolor:#052E16', 'Codex', body]


class Completions:
    def __init__(self):
        self.observed = {}

    def collect(self, sessions):
        commands = []
        for session in sessions:
            if not session.get('alive'):
                continue
            sid, token = session['id'], session.get('completion')
            if sid in self.observed and token and token != self.observed[sid]:
                commands.append(command(session))
            # Initial discovery establishes a baseline, without replaying old completions.
            self.observed[sid] = token
        return commands


def send(args):
    subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=3, check=True)
