"""Exercise a real TUI against disposable RPC servers, without i3 or notifications."""
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tempfile
import time
import unittest


SERVER = r'''
import json,sys,threading
from pathlib import Path
from deck.server import Server,Handler
path,label,log=sys.argv[1:]
class Model:
 def snapshot(self):
  order=['b','a'] if label=='AFTER_RESTART' else ['a','b']
  rows=[dict(id=s,kind='agent',slot=10,number=20,pair='[0]',workspace_label='F0',
             state='working',name=label+'_'+s.upper(),alive=True,located=True,
             focused=False,target=s) for s in order]
  return dict(rows=rows,agents=rows,error='',current_slot=10,current_number=20)
 def navigate(self,sid):
  with open(log,'a') as f:f.write(json.dumps(sid)+'\n')
Path(path).unlink(missing_ok=True)
with Server(path,Handler) as server:
 server.model=Model();server.model_lock=threading.Lock();server.serve_forever(poll_interval=.05)
'''


class ReconnectPtyTests(unittest.TestCase):
    def test_tui_survives_restart_retains_selection_and_drops_offline_actions(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            path, log = Path(tmp) / 'deck.sock', Path(tmp) / 'moves'
            processes = []
            master = None

            def start_server(label):
                path.unlink(missing_ok=True)
                process = subprocess.Popen([sys.executable, '-c', SERVER, str(path), label, str(log)],
                                           cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                processes.append(process)
                deadline = time.monotonic() + 3
                while not path.exists() and time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(process.stderr.read().decode())
                    time.sleep(.01)
                self.assertTrue(path.exists())
                return process

            def read_until(needle, timeout=4):
                output = b''
                deadline = time.monotonic() + timeout
                while needle not in output and time.monotonic() < deadline:
                    if select.select([master], [], [], .05)[0]:
                        try:
                            output += os.read(master, 65536)
                        except OSError:
                            break
                self.assertIn(needle, output, output[-1200:])

            try:
                first = start_server('BEFORE')
                master, slave = pty.openpty()
                tui = subprocess.Popen([sys.executable, 'ai_deck.py', '--socket', str(path)],
                                       cwd=root, stdin=slave, stdout=slave, stderr=slave,
                                       env=dict(os.environ, TERM='xterm-256color'))
                processes.append(tui)
                os.close(slave)
                read_until(b'BEFORE_A')
                os.write(master, b'j')
                time.sleep(.15)
                subprocess.run([sys.executable, 'ai_deck.py', '--socket', str(path), '--stop-server'],
                               cwd=root, check=True, capture_output=True, timeout=3)
                first.wait(3)
                read_until('서버 연결 대기'.encode())
                self.assertIsNone(tui.poll())
                os.write(master, b'gGnN\r')
                time.sleep(.15)
                second = start_server('AFTER_RESTART')
                read_until(b'AFTER_RESTART')
                self.assertFalse(log.exists())  # Offline Enter was never replayed.
                os.write(master, b'\r')
                deadline = time.monotonic() + 2
                while not log.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertEqual(json.loads(log.read_text().strip()), 'b')
                second.terminate(); second.wait(3)
                read_until('서버 연결 대기'.encode())
                started = time.monotonic()
                os.write(master, b'q')
                self.assertEqual(tui.wait(1), 0)
                self.assertLess(time.monotonic() - started, 1)
            finally:
                for process in reversed(processes):
                    if process.poll() is None:
                        process.terminate()
                        process.wait(3)
                    if process.stderr:
                        process.stderr.close()
                if master is not None:
                    os.close(master)


if __name__ == '__main__':
    unittest.main()
