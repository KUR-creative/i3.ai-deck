#!/usr/bin/env python3
"""Preview by default; --apply backs up and enables left-click notification actions."""
import argparse
from datetime import datetime
import difflib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    target = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'dunst/dunstrc'
    source = target if target.exists() else Path('/etc/xdg/dunst/dunstrc')
    if target.is_symlink():
        raise ValueError('심볼릭 링크 설정은 자동으로 수정하지 않습니다.')
    before = source.read_text()
    lines = before.splitlines(keepends=True)
    sections = [(n, m[1]) for n, line in enumerate(lines)
                if (m := re.match(r'^\s*\[([^]]+)\]', line))]
    start = next(n for n, name in sections if name == 'global')
    end = next((n for n, _ in sections if n > start), len(lines))
    options = [n for n in range(start + 1, end)
               if re.match(r'^\s*mouse_left_click\s*=', lines[n])]
    if len(options) > 1:
        raise ValueError('중복 mouse_left_click 설정을 먼저 정리해야 합니다.')
    setting = '    mouse_left_click = do_action, close_current\n'
    if options:
        lines[options[0]] = setting
    else:
        lines.insert(end, setting)
    after = ''.join(lines)
    print(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                     fromfile=str(source), tofile=str(target))), end='')
    if not args.apply:
        print('미리보기입니다. 실제 적용은 --apply를 사용합니다.')
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_name('dunstrc.before-ai-deck.' + datetime.now().strftime('%Y%m%dT%H%M%S%f'))
    shutil.copy2(source, backup)
    with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(after)
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f'백업: {backup}')
    subprocess.run(['dunstctl', 'reload', str(target)], check=True)
    print(f'적용 및 dunst 재로드 완료: {target}')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, StopIteration, subprocess.CalledProcessError) as error:
        raise SystemExit(f'dunst 설정: {error}')
