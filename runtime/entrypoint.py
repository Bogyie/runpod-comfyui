"""Prepare managed volume directories, drop privileges, then supervise ComfyUI."""
import ctypes
import json
import os
from pathlib import Path
import sys


def main():
    paths = [Path('/workspace/storage'), Path('/workspace/state'), Path('/workspace/cache')]
    paths += [paths[0] / name for name in ['models', 'input', 'output', 'user', 'temp', 'previews', 'datasets']]
    paths += [Path('/workspace/state/home'), Path('/workspace/state/logs'), Path('/workspace/cache/metadata')]
    for path in paths:
        if path.is_symlink() or path.resolve() != path:
            raise RuntimeError('Managed runtime directory may not be a symlink: ' + str(path))
        path.mkdir(parents=True, exist_ok=True)
        if os.getuid() == 0:
            # Only managed directory entries, never recursive user-data chown.
            os.chown(path, 1000, 1000)
    os.environ['COMFYCTL_RUNTIME_ID'] = json.loads(Path('/opt/runtime/control/identity.json').read_text())['runtime_id']
    os.umask(0o027)
    if os.getuid() == 0:
        os.setgroups([])
        os.setgid(1000)
        os.setuid(1000)
    if os.getuid() != 1000 or os.geteuid() != 1000:
        raise RuntimeError('Runtime requires service uid 1000')
    if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0):  # PR_SET_NO_NEW_PRIVS
        raise OSError(ctypes.get_errno(), 'Cannot set no_new_privs')
    os.execv(sys.executable, [sys.executable, '/opt/runtime/control/supervisor.py', *sys.argv[1:]])


if __name__ == '__main__':
    main()
