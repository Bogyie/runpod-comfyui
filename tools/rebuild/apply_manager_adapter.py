#!/usr/bin/env python3
"""Keep pinned Manager assets/catalog; replace its installer with CLI guidance."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
COMMIT = '4c50a2bc8b9e684d8a85930567957470b952bebe'
GUIDE = 'Managed image: use comfyctl node add/disable, env apply/rollback/reset, or model add. Manager direct mutation is disabled.'


def apply(destination, source):
    if source['commit'] != COMMIT:
        raise ValueError('Unreviewed Manager revision')
    originals = {}
    paths = sorted(destination.rglob('*.py'))
    for path in paths:
        relative = path.relative_to(destination).as_posix()
        data = path.read_bytes()
        if path.is_symlink() or hashlib.sha256(data).hexdigest() != source['files'].get(relative):
            raise ValueError('Unreviewed Manager Python source: ' + relative)
        originals[relative] = hashlib.sha256(data).hexdigest()
    # Legacy backend/prestartup/CLI/repair modules are deliberately ineligible,
    # even when invoked outside normal UI imports or with different env flags.
    for path in paths:
        path.write_text('raise RuntimeError('+repr(GUIDE)+')\n')
    adapter = ROOT/'build/adapters/manager'
    for path in sorted(adapter.glob('*.py')):
        shutil.copyfile(path, destination/path.name)
    (destination/'cm-cli.py').write_text('raise SystemExit('+repr(GUIDE)+')\n')
    original_js = {}
    for name, message in [('custom-nodes-manager.js','Node changes use comfyctl in the administrator terminal. See the managed image notice for commands.'),
                          ('model-manager.js','Model downloads use comfyctl model add in the administrator terminal.')]:
        path = destination/'js'/name
        data = path.read_bytes(); original_js[name] = hashlib.sha256(data).hexdigest()
        text = data.decode()
        anchor = 'This action is not allowed with this security level configuration.'
        if text.count(anchor) != 2:
            raise ValueError('Manager frontend error boundary changed: ' + name)
        path.write_text(text.replace(anchor, message))
    result = {'kind':'manager-readonly-catalog-cli-adapter','commit':COMMIT,'original_python':originals,
              'original_js':original_js,
              'adapter_files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(adapter.glob('*.py'))},
              'policy':'Original JS/catalog, read-only HTTP adapter, no legacy backend imports; mutations use comfyctl'}
    (destination/'_managed_identity.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result
