"""Prepare managed volume directories, drop privileges, then supervise ComfyUI."""
import ctypes
import json
import os
from pathlib import Path
import sys


def main():
    workspace = Path('/workspace')
    if workspace.is_symlink() or workspace.resolve() != workspace:
        raise RuntimeError('Workspace mount may not be a symlink')
    workspace.mkdir(exist_ok=True)
    if os.getuid() == 0:
        # Protect root-managed control entries from rename by the service user.
        os.chown(workspace, 0, 0)
        workspace.chmod(0o755)
    for path in [workspace / 'runtime', workspace / 'runtime/control', workspace / 'runtime/generations']:
        if path.is_symlink() or path.resolve() != path:
            raise RuntimeError('Unsafe runtime control directory')
        path.mkdir(exist_ok=True)
        if os.getuid() == 0:
            os.chown(path, 0, 0)
            path.chmod(0o755)
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
    if sys.argv[1:2] == ['comfyctl']:
        os.execv('/usr/local/bin/comfyctl', ['comfyctl', *sys.argv[2:]])
    sys.path.insert(0, str(Path(__file__).parent))
    from selection import Store, SelectionError
    store=Store()
    os.environ.pop('COMFYCTL_IMAGE_RECOVERY',None)
    with store.locked():
        try:
            store.prepare_image()
            store.recover_interrupted()
            store.state()
        except SelectionError as error:
            print('Image selection requires explicit recovery: '+str(error),file=sys.stderr,flush=True)
            os.environ['COMFYCTL_IMAGE_RECOVERY']='1'
    os.umask(0o027)
    if os.getuid() == 0:
        os.setgroups([])
        os.setgid(1000)
        os.setuid(1000)
    if os.getuid() != 1000 or os.geteuid() != 1000:
        raise RuntimeError('Runtime requires service uid 1000')
    if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0):  # PR_SET_NO_NEW_PRIVS
        raise OSError(ctypes.get_errno(), 'Cannot set no_new_privs')
    os.execv(sys.executable, [sys.executable, '-I', '/opt/runtime/control/supervisor.py', *sys.argv[1:]])


if __name__ == '__main__':
    main()
