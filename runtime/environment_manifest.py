"""Hash private environment files without traversing immutable GPU links."""
import hashlib
import json
import os
from pathlib import Path


def snapshot(prefix):
    prefix = Path(prefix)
    links = json.loads((prefix / 'gpu-links.json').read_text())
    site = prefix / 'lib/python3.11/site-packages'
    allowed = {site / name: Path(links['source']) / name
               for package in links['packages'].values() for name in package['paths'] if not name.endswith('.dist-info')}
    files, symlinks = {}, {}
    for path in sorted(prefix.rglob('*')):
        if '__pycache__' in path.parts:
            continue
        mode = path.lstat()
        if mode.st_uid != 0 or (not path.is_symlink() and mode.st_mode & 0o022):
            raise ValueError('Candidate environment is not sealed: ' + str(path))
        relative = path.relative_to(prefix).as_posix()
        if path.is_symlink():
            target = path.resolve(strict=True)
            valid_python = path.parent == prefix / 'bin' and path.name in {'python', 'python3', 'python3.11'} and target == Path('/usr/local/bin/python3.11').resolve()
            if not (target.is_relative_to(prefix) or valid_python or path in allowed and target == allowed[path].resolve()):
                raise ValueError('Unexpected environment symlink: ' + relative)
            symlinks[relative] = os.readlink(path)
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            files[relative] = digest.hexdigest()
    return {'files': files, 'symlinks': symlinks}
