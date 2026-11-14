"""Read i3 state and reuse the user's workspace pairs without editing config."""
import json
from pathlib import Path
import re
import shlex
import subprocess


def ipc(kind, command=None):
    args = ['i3-msg', '-t', kind]
    if command is not None:
        args.append(command)
    result = subprocess.run(args, capture_output=True, text=True, timeout=3)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'i3 IPC failed')
    return json.loads(result.stdout)


def pairs_from_config(path):
    variables = {}
    for line in path.read_text().splitlines():
        if not re.match(r'^\s*set\s+\$(left|right)\d+\s', line):
            continue
        parts = shlex.split(line, comments=True)
        if len(parts) == 3 and parts[0] == 'set':
            variables[parts[1]] = parts[2]
    pairs = []
    for slot in range(1, 11):
        left, right = variables[f'$left{slot}'], variables[f'$right{slot}']
        pairs.append(dict(slot=slot, label=f'F{slot}/{slot % 10}',
                          left=int(left.split(':')[0]), right=int(right.split(':')[0]),
                          left_name=left, right_name=right))
    return pairs


def windows(tree):
    result = []

    def walk(node, workspace='', number=-1):
        if node.get('type') == 'workspace':
            workspace = node.get('name', '')
            number = node.get('num', -1)
        if node.get('window'):
            result.append(dict(con_id=node['id'], window=node['window'],
                               title=node.get('name') or '', focused=node.get('focused', False),
                               workspace=workspace, number=number,
                               klass=node.get('window_properties', {}).get('class', '')))
        for child in node.get('nodes', []) + node.get('floating_nodes', []):
            walk(child, workspace, number)

    walk(tree)
    return result


def pair_for(number, pairs):
    return next((pair for pair in pairs if number in (pair['left'], pair['right'])), None)


def focus_command(pair=None, con_id=None):
    commands = []
    if pair:
        commands.extend('workspace --no-auto-back-and-forth number '
                        + json.dumps(pair[key + '_name'])
                        for key in ('left', 'right'))
    if con_id is not None:
        commands.append(f'[con_id={int(con_id)}] focus')
    if not commands:
        raise ValueError('No destination')
    return '; '.join(commands)


def focus(pair=None, con_id=None):
    result = ipc('command', focus_command(pair, con_id))
    if not result or not all(reply.get('success') for reply in result):
        raise RuntimeError('i3 이동 실패: ' + json.dumps(result, ensure_ascii=False))
    if pair:
        visible = {ws['num'] for ws in ipc('get_workspaces') if ws['visible']}
        expected = {pair['left'], pair['right']}
        if not expected.issubset(visible):
            raise RuntimeError(f'쌍 전환 확인 실패: 예상 {sorted(expected)}, 현재 {sorted(visible)}')
