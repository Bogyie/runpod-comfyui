"""Read package metadata in the requested interpreter; never import node/GPU code."""
import base64
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import sysconfig


def main():
    deep = json.load(sys.stdin).get('deep', False)
    site = Path(sysconfig.get_path('purelib'))
    versions = {}
    files = []
    skipped = 0
    overrides = {}
    patch = site / 'comfy_env/runpod-patch.json'
    if patch.is_file():
        for name, expected in json.loads(patch.read_text())['patched'].items():
            overrides[str((site / 'comfy_env' / name).resolve())] = expected
    for dist in metadata.distributions():
        name = dist.metadata['Name']
        versions[name] = dist.version
        if not deep:
            continue
        for entry in dist.files or []:
            # Console scripts and generated/unhashed files need separate checks.
            if not entry.hash or entry.hash.mode != 'sha256' or '..' in Path(str(entry)).parts:
                skipped += 1
                continue
            path = Path(dist.locate_file(entry)).resolve()
            expected = overrides.get(str(path)) or base64.urlsafe_b64decode(entry.hash.value + '===').hex()
            files.append({'path': str(path), 'sha256': expected, 'package': name})
    origins = {}
    for module in ['torch', 'huggingface_hub', 'numpy']:
        spec = importlib.util.find_spec(module)
        origins[module] = str(Path(spec.origin).resolve()) if spec and spec.origin else None
    print(json.dumps({'prefix': sys.prefix, 'python': platform.python_version(), 'site': str(site),
                      'sys_path': sys.path, 'versions': versions, 'origins': origins,
                      'marker_environment': {'os_name': os.name, 'sys_platform': sys.platform,
                          'platform_machine': platform.machine(), 'python_version': f'{sys.version_info.major}.{sys.version_info.minor}',
                          'python_full_version': platform.python_version(), 'platform_system': platform.system(),
                          'platform_python_implementation': platform.python_implementation(),
                          'implementation_name': sys.implementation.name},
                      'record_files': files, 'unhashed_or_generated_files_skipped': skipped}))


if __name__ == '__main__':
    main()
