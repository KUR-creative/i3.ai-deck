#!/usr/bin/env python3
"""i3의 Codex 세션을 나열하고 해당 워크스페이스 쌍과 창으로 이동합니다."""
import argparse
import curses
import json
import locale
from pathlib import Path
import sys

from deck.client import connect, default_socket
from deck.server import serve
from deck.connection import ReconnectingClient
from deck.tui import run


def main():
    parser = argparse.ArgumentParser(
        prog='ais', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''예시:
  ais                 서버 자동 시작 + 현재 터미널에 TUI 열기
  ais --start-server  TUI 없이 서버만 시작 (이미 실행 중이면 재사용)
  ais --stop-server   서버 종료
  ais --list          현재 상태를 JSON으로 출력 (필요하면 서버 시작)

TUI: j/k 선택 · g/G 처음/끝 · n 확인 대상 선택 · N 모든 에이전트 선택
     Enter/클릭 이동 · 마우스 휠 스크롤 · q/Esc 닫기
q는 TUI만 닫습니다. 서버와 Codex는 계속 실행됩니다.

의존성: Python 3, i3-msg, ~/.local/bin/ws, dunst/dunstify.
알림 클릭 이동은 dunst의 왼쪽 클릭 기본 액션 설정이 필요합니다.
소켓·로그: $XDG_RUNTIME_DIR/i3-ai-deck/ (없으면 ~/.cache/i3-ai-deck/).
''')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--server', action='store_true', help='공유 서버 실행 (포그라운드)')
    mode.add_argument('--start-server', action='store_true', help='TUI 없이 백그라운드 서버만 시작')
    mode.add_argument('--list', action='store_true', help='현재 목록을 JSON으로 출력')
    mode.add_argument('--stop-server', action='store_true', help='공유 서버 종료')
    parser.add_argument('--socket', type=Path, default=default_socket(),
                        help='공유 소켓 경로 (별도 테스트 서버 분리에 사용)')
    args = parser.parse_args()
    if args.server:
        serve(args.socket)
        return
    if args.list or args.stop_server or args.start_server:
        client = connect(args.socket, start=not args.stop_server)
    else:
        try:
            initial = connect(args.socket)
        except (OSError, RuntimeError):
            initial = None
        client = ReconnectingClient(args.socket, initial)
    try:
        if args.start_server:
            client.request()  # Confirm the server can answer before reporting success.
            print(f'서버 실행 중: {args.socket}')
        elif args.stop_server:
            client.request('stop')
        elif args.list:
            print(json.dumps(client.request(), indent=2, ensure_ascii=False))
        else:
            locale.setlocale(locale.LC_ALL, '')
            curses.wrapper(run, client)
    finally:
        client.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError, curses.error) as error:
        print(f'ais: {error}', file=sys.stderr)
        sys.exit(1)
