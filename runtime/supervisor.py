"""PID 1: health, bounded process cleanup and explicit root-requested reloads."""
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
MAINTENANCE = Path('/workspace/runtime/control/maintenance.json')
PORT = 8188


def status(phase, **details):
    value = {'phase': phase, 'updated_at': time.time(), 'uid': os.getuid(),
             'runtime_id': os.environ['COMFYCTL_RUNTIME_ID'], 'generation_id': os.environ.get('COMFYCTL_GENERATION_ID'),
             'pid_namespace': os.readlink('/proc/self/ns/pid'), 'port': PORT,
             'maintenance': MAINTENANCE.exists(), **details}
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(STATE)


def get(path):
    with urllib.request.urlopen(f'http://127.0.0.1:{PORT}{path}', timeout=3) as response:
        return json.load(response)


def kill_group(child, sig):
    try:
        os.killpg(child.pid, sig)
    except ProcessLookupError:
        pass


def cleanup(child):
    kill_group(child, signal.SIGTERM)
    try:
        child.wait(timeout=15)
    except subprocess.TimeoutExpired:
        kill_group(child, signal.SIGKILL)
        child.wait()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if not pid:
                time.sleep(0.05)
        except ChildProcessError:
            break
    kill_group(child, signal.SIGKILL)


def _desired_id():
    try:
        from selection import Store
        return Store().state()['desired']
    except Exception:
        return None


def main():
    global PORT
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--port', type=int, default=8188)
    PORT = parser.parse_known_args()[0].port
    sys.path.insert(0, str(Path(__file__).parent))
    from selection import selected_environment
    flags = {'stop': False, 'reload': False}
    child = None

    def forward(signum, _frame):
        flags['stop'] = True
        if child is not None:
            kill_group(child, signum)

    def reload_request(_signum, _frame):
        # No unauthenticated mutation route: only a root-owned maintenance file
        # permits a signal to become a generation reload request.
        if MAINTENANCE.is_file():
            flags['reload'] = True

    for signum in [signal.SIGTERM, signal.SIGINT]:
        signal.signal(signum, forward)
    signal.signal(signal.SIGUSR1, reload_request)
    logger = logging.getLogger('comfyui')
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler('/workspace/state/logs/comfyui.log', maxBytes=16 * 1024 * 1024, backupCount=2)
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)
    explicit_reload = False
    while not flags['stop']:
        try:
            environment, required = selected_environment()
            for name in ['COMFYCTL_COMFY_ROOT', 'COMFYCTL_GENERATION_ID', 'COMFYCTL_WORKER_MAP_FILE', 'COMFYCTL_HOST_PYTHON', 'COMFYCTL_REQUIRED_ENDPOINTS']:
                os.environ.pop(name, None)
            os.environ.update(environment)
            status('starting')
            child = subprocess.Popen([os.environ['COMFYCTL_HOST_PYTHON'], '-I', '/opt/runtime/control/run_comfy.py', *sys.argv[1:]],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        except Exception as exc:
            status('recovery-required', error=str(exc), failed_generation=_desired_id())
            child = None
            if not explicit_reload and os.environ.get('COMFYCTL_IMAGE_RECOVERY')!='1':
                raise
        if child is None:
            while not flags['stop'] and not flags['reload']:
                time.sleep(0.2)
            flags['reload'] = False
            continue

        current = child

        def output():
            for line in current.stdout:
                logger.info(line.rstrip('\n'))
                print(line, end='', flush=True)

        reader = threading.Thread(target=output, daemon=True)
        reader.start()
        ready = False
        last_ready = 0.0
        deadline = time.monotonic() + int(os.environ.get('COMFYCTL_STARTUP_TIMEOUT', '300'))
        reload_now = False
        while child.poll() is None and not flags['stop']:
            if flags['reload'] and MAINTENANCE.exists():
                try:
                    idle = get('/comfyctl/runtime/idle')
                    if idle['running'] == idle['pending'] == idle['inflight'] == 0:
                        reload_now = True
                        status('restarting', child_pid=child.pid)
                        break
                except Exception:
                    # The CLI only signals after a confirmed drain. A failed
                    # startup/API can still be explicitly rolled back.
                    if not ready:
                        reload_now = True
                        break
            try:
                payload = get('/system_stats' if ready else '/object_info')
                if ready:
                    if 'system' not in payload or 'devices' not in payload:
                        raise RuntimeError('Invalid ComfyUI health response')
                else:
                    if not required.issubset(payload):
                        raise RuntimeError('Required nodes unavailable: ' + ','.join(sorted(required - payload.keys())))
                    info = get('/comfyctl/runtime/idle')
                    if info['generation_id'] != os.environ['COMFYCTL_GENERATION_ID']:
                        raise RuntimeError('Runtime control endpoint belongs to another generation')
                    for path in json.loads(os.environ.get('COMFYCTL_REQUIRED_ENDPOINTS', '[]')):
                        get(path)
                if not ready or time.monotonic() - last_ready >= 15:
                    status('ready', child_pid=child.pid)
                    last_ready = time.monotonic()
                ready = True
            except Exception as exc:
                if ready or time.monotonic() > deadline:
                    status('recovery-required', child_pid=child.pid, error=str(exc))
                    ready = False
            time.sleep(1)
        cleanup(child)
        reader.join(timeout=2)
        exit_code = child.returncode
        child = None
        if flags['stop']:
            status('stopped', exit_code=exit_code)
            return 0
        if reload_now or flags['reload']:
            flags['reload'] = False
            explicit_reload = True
            continue
        status('recovery-required' if exit_code else 'stopped', exit_code=exit_code)
        if not explicit_reload:
            return exit_code
        # A failed explicit switch keeps the control supervisor alive for one
        # rollback request. It does not loop restarting the failed application.
        while not flags['stop'] and not flags['reload']:
            time.sleep(0.2)
        flags['reload'] = False
    status('stopped')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
