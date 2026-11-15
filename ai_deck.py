#!/usr/bin/env python3
"""Run the TUI here; every terminal connects to the same local server."""
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
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--server', action='store_true', help='공유 서버 실행')
    mode.add_argument('--list', action='store_true', help='현재 목록을 JSON으로 출력')
    mode.add_argument('--stop-server', action='store_true', help='공유 서버 종료')
    parser.add_argument('--socket', type=Path, default=default_socket())
    args = parser.parse_args()
    if args.server:
        serve(args.socket)
        return
    if args.list or args.stop_server:
        client = connect(args.socket, start=not args.stop_server)
    else:
        try:
            initial = connect(args.socket)
        except (OSError, RuntimeError):
            initial = None
        client = ReconnectingClient(args.socket, initial)
    try:
        if args.stop_server:
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
        print(f'i3.ai-deck: {error}', file=sys.stderr)
        sys.exit(1)
