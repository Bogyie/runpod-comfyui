"""PID 1: readiness, bounded shutdown, orphan reaping; no automatic restart."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.request

STATE = Path('/workspace/state/runtime-status.json')


def status(phase, **details):
    value = {'phase': phase, 'updated_at': time.time(), 'uid': os.getuid(), 'runtime_id': os.environ['COMFYCTL_RUNTIME_ID'], **details}
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(STATE)


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--port', type=int, default=8188)
    port = parser.parse_known_args()[0].port
    status('starting')
    log = logging.getLogger('comfyui')
    log.setLevel(logging.INFO)
    handler = RotatingFileHandler('/workspace/state/logs/comfyui.log', maxBytes=16 * 1024 * 1024, backupCount=2)
    handler.setFormatter(logging.Formatter('%(message)s'))
    log.addHandler(handler)
    child = subprocess.Popen(['/opt/runtime/venv/bin/python', '/opt/runtime/control/run_comfy.py', *sys.argv[1:]],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    stopping = False
    signal_at = None

    def forward(signum, _frame):
        nonlocal stopping, signal_at
        if not stopping:
            stopping = True
            signal_at = time.monotonic()
            status('stopping', child_pid=child.pid, signal=signum)
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass

    for signum in [signal.SIGTERM, signal.SIGINT]:
        signal.signal(signum, forward)

    def output():
        for line in child.stdout:
            log.info(line.rstrip('\n'))
            print(line, end='', flush=True)

    reader = threading.Thread(target=output, daemon=True)
    reader.start()
    deadline = time.monotonic() + int(os.environ.get('COMFYCTL_STARTUP_TIMEOUT', '300'))
    ready = False
    last_ready = 0.0
    while child.poll() is None:
        if stopping:
            if time.monotonic() - signal_at > 15:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        else:
            try:
                endpoint = '/system_stats' if ready else '/object_info'
                with urllib.request.urlopen(f'http://127.0.0.1:{port}{endpoint}', timeout=3) as response:
                    payload = json.load(response)
                if ready:
                    if 'system' not in payload or 'devices' not in payload:
                        raise RuntimeError('Invalid ComfyUI health response')
                else:
                    required = {'SaveImage', 'SAM3PointCollector', 'DepthAnything_V3', 'iToolsCheckerBoard', 'ColorMatchV2', 'VHS_VideoCombine'}
                    if not required.issubset(payload):
                        raise RuntimeError('Required nodes unavailable: ' + ','.join(sorted(required - payload.keys())))
                if not ready or time.monotonic() - last_ready >= 15:
                    status('ready', child_pid=child.pid)
                    last_ready = time.monotonic()
                ready = True
            except Exception as exc:
                if ready:
                    status('recovery-required', child_pid=child.pid, error=str(exc))
                    ready = False
                elif time.monotonic() > deadline:
                    status('recovery-required', child_pid=child.pid, error=str(exc))
        time.sleep(2)
    # Native workers inherit the child's process group. Terminate remaining
    # children even if the host failed before its atexit cleanup.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    cleanup_deadline = time.monotonic() + 5
    while time.monotonic() < cleanup_deadline:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                time.sleep(0.05)
        except ChildProcessError:
            break
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    reader.join(timeout=2)
    status('stopped' if stopping or child.returncode == 0 else 'recovery-required', exit_code=child.returncode)
    return 0 if stopping else child.returncode


if __name__ == '__main__':
    raise SystemExit(main())
