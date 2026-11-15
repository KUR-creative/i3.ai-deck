"""Check deck -> ws -> Mod+Tab using the user's isolated Xvfb/i3 harness.

Run from the repository: python3 -B tests/ws_navigation_check.py
Requires ~/.config/i3/tests/workspace_regression.py (or --harness PATH).
The harness reads i3 config and writes only to its temporary runtime/display.
"""
import argparse
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deck.model import Model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harness', type=Path, default=
                        Path.home() / '.config/i3/tests/workspace_regression.py')
    parser.add_argument('--xvfb', default='Xvfb')
    args = parser.parse_args()
    harness = runpy.run_path(str(args.harness))
    workspace = harness['workspace']
    count = 0
    with harness['Desktop'](harness['CONFIG'], args.xvfb, 5) as desktop, \
            patch.dict('os.environ', desktop.env, clear=True):
        log = desktop.root / 'rollout.jsonl'
        log.write_text('{"type":"event_msg","payload":{"type":"task_started"}}\n')
        model = Model(desktop.root, desktop.root / 'config')
        model.titles.names = {side: f'{side}-source' for side in ('left', 'right')}
        live = {side: dict(pid=1, cwd='/', path=log) for side in ('left', 'right')}

        def prepare(number, side, empty=False):
            origin = 2 if number == 1 else 1
            for name in desktop.ids:
                own_side = name.split('-')[0]
                destination = origin if empty or name.endswith('existing') else number
                desktop.move(name, workspace(own_side, destination))
            for own_side in ('left', 'right'):
                desktop.show(workspace(own_side, origin))
            departure = side + '-existing'
            desktop.focus(departure)
            desktop.park_pointer(departure)
            desktop.history_path.write_text('')
            return origin, departure, {t: v[0] for t, v in desktop.locations().items()}

        def back_to(origin, departure, expected):
            desktop.keys.press('Tab')
            desktop.check(expected, departure, {workspace(s, origin) for s in ('left', 'right')})

        with patch('deck.model.discover', return_value=live):
            for number in range(1, 11):
                for side in ('left', 'right'):
                    origin, departure, expected = prepare(number, side)
                    visible = {workspace(s, number) for s in ('left', 'right')}
                    model.navigate(side)
                    desktop.check(expected, side + '-source', visible)
                    assert desktop.previous() == workspace(side, origin).split(':')[1]
                    back_to(origin, departure, expected)
                    desktop.keys.press('Tab')
                    desktop.check(expected, side + '-source', visible)
                    # Same pair: selecting the other agent must preserve previous.
                    previous = desktop.previous()
                    other = 'right' if side == 'left' else 'left'
                    model.navigate(other)
                    desktop.check(expected, other + '-source', visible)
                    assert desktop.previous() == previous
                    back_to(origin, departure, expected)
                    desktop.keys.press('Tab')
                    desktop.check(expected, other + '-source', visible)
                    count += 1

            for number in range(1, 11):
                for side in ('left', 'right'):
                    origin, departure, expected = prepare(number, side, empty=True)
                    visible = {workspace(s, number) for s in ('left', 'right')}
                    model.navigate('workspace:' + str(number + (10 if side == 'left' else 0)))

                    def on_empty():
                        return desktop.visible() == visible and any(
                            ws['focused'] and ws['name'] == workspace(side, number)
                            for ws in desktop.ipc('get_workspaces'))

                    desktop.wait(on_empty, 'empty selected side')
                    back_to(origin, departure, expected)
                    desktop.keys.press('Tab')
                    desktop.wait(on_empty, 'empty selected side restored')
                    count += 1
    print(f'ws integration: {count} scenarios passed (isolated display/runtime)')


if __name__ == '__main__':
    main()
