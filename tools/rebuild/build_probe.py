#!/usr/bin/env python3
"""Build an experimental Linux host probe locally; publication is handled by CI.

Uses complete archive contents, not the text-only audit snapshot. Model/GPU and
custom-node execution are separate gates after this core startup probe.
"""
from __future__ import annotations

import argparse
import io
import json
import platform
import shutil
import subprocess
import tarfile
import time
from pathlib import Path, PurePosixPath

import yaml

from snapshot_upstreams import ROOT, digest, fetch


def materialize(data: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for item in archive:
            parts = PurePosixPath(item.name).parts
            if not parts or parts[0] == "/" or ".." in parts:
                raise ValueError("Unsafe source archive path")
            if item.isdir():
                continue
            if not item.isfile():
                raise ValueError(f"Nonregular source archive entry: {item.name}")
            if len(parts) < 2:
                raise ValueError("Missing archive root")
            target = destination.joinpath(*parts[1:])
            if target.is_symlink() or not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Source extraction target escapes destination")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(item) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)



WORKER_ENVIRONMENTS = {
    "sam3": "sam3-nodes",
    "depth-anything-v3": "depthanythingv3-nodes",
    "itools": "itools-workernodes",
    "kjnodes": "kjnodes-workernodes",
    "video-helper-suite": "videohelpersuite-workernodes",
}


def execution_contract(stack, sources, definitions, host_lock_sha):
    def identity(value):
        return digest(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
    policy = {name:digest((ROOT/'tools/rebuild'/name).read_bytes()) for name in
              ['apply_comfy_env_patch.py','managed_metadata.py','link_gpu_packages.py']}
    abi = identity({'base':stack['base_image'],'python':stack['python'],
                    'gpu':definitions['gpu_lock_sha256'],'sdk_policy':policy})
    environment = identity({'abi':abi,'host':host_lock_sha,
        'workers':{name:item['lock_sha256'] for name,item in definitions['workers'].items()}})
    application = identity({'comfyui':sources['comfyui']['archive_sha256'],
        'workers':definitions,'manager':sources['manager']['archive_sha256'],
        'manager_adapter':{path.name:digest(path.read_bytes()) for path in sorted((ROOT/'build/adapters/manager').glob('*.py'))},
        'manager_patch':digest((ROOT/'tools/rebuild/apply_manager_adapter.py').read_bytes()),
        'runtime_api':{name:digest((ROOT/'runtime'/name).read_bytes()) for name in
                       ['control_plugin.py','runtime_paths.py','run_comfy.py']}})
    return {'generation_schema':2,'abi_id':abi,'environment_id':environment,'application_id':application,
            'compatibility_id':identity({'schema':2,'environment':environment,'application':application})}


def prepare_worker_install_inputs(context: Path, definitions: dict) -> None:
    """Keep package installation inputs independent of source/adapter metadata.

    Prefixes remain at their final absolute paths in every build stage. The
    complete runtime identity is assembled later, without reinstalling packages.
    """
    workers = definitions['workers']
    if {name: worker['environment'] for name, worker in workers.items()} != WORKER_ENVIRONMENTS:
        raise ValueError('Worker set/prefix changed; update the explicit Docker stages')
    for directory in ['worker-install', 'worker-identities']:
        root = context / directory
        if root.exists():
            shutil.rmtree(root)
        root.mkdir()
    for name, worker in workers.items():
        destination = context / 'worker-install' / name
        destination.mkdir()
        subset = {key: worker[key] for key in ['environment', 'lock_file', 'lock_sha256']}
        manifest = {'schema_version': 1, 'provider': definitions['provider'],
                    'gpu_lock_sha256': definitions['gpu_lock_sha256'], 'workers': {name: subset}}
        (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
        shutil.copyfile(context / 'worker-locks' / worker['lock_file'], destination / worker['lock_file'])
        identity = context / 'worker-identities' / worker['environment']
        identity.mkdir()
        (identity / 'worker-lock.json').write_text(json.dumps(worker, indent=2, sort_keys=True) + '\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["gpu-base", "host", "worker-probe", "runtime-probe"])
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    stack = yaml.safe_load((ROOT / "build/stack.yaml").read_text())
    args.target = args.target or stack.get("candidate", {}).get("target", "host")
    lock = json.loads((ROOT / "locks/upstreams.lock.json").read_text())
    context = ROOT / ".work/probe-context"
    context.mkdir(parents=True, exist_ok=True)
    for name in ("gpu", "host"):
        shutil.copyfile(ROOT / f"locks/{name}/linux-amd64-cu128.txt", context / f"{name}.txt")
    shutil.copyfile(ROOT / "tools/rebuild/apply_comfy_env_patch.py", context / "apply_comfy_env_patch.py")
    shutil.copyfile(ROOT / "tools/rebuild/managed_metadata.py", context / "managed_metadata.py")
    if args.target in {"host", "worker-probe", "runtime-probe"}:
        source = lock["sources"]["comfyui"]
        data = fetch(source["archive_url"])
        if digest(data) != source["archive_sha256"]:
            raise ValueError("ComfyUI source archive hash mismatch")
        destination = context / "ComfyUI"
        if destination.exists():
            shutil.rmtree(destination)
        materialize(data, destination)
    if args.target in {"worker-probe", "runtime-probe"}:
        import concurrent.futures
        definitions = json.loads((ROOT / "locks/workers/manifest.json").read_text())
        if definitions.get('gpu_lock_sha256') != digest((ROOT/'locks/gpu/linux-amd64-cu128.txt').read_bytes()):
            raise ValueError('Worker GPU lock identity changed without re-locking')
        inputs = json.loads((ROOT / "build/inputs/workers/workers.json").read_text())
        worker_locks = context / "worker-locks"
        if worker_locks.exists():
            shutil.rmtree(worker_locks)
        worker_locks.mkdir()
        for name, definition in definitions['workers'].items():
            recorded = {key:value for key,value in definition.items() if key not in {'lock_file','lock_sha256'}}
            if recorded != inputs['workers'][name]:
                raise ValueError(f'Worker definition changed without re-locking: {name}')
            for field in ['lock_file','environment','plugin_directory']:
                value = definition[field]
                if not value or Path(value).name != value or value in {'.','..'}:
                    raise ValueError(f'Unsafe worker {field}: {value}')
            if definition['commit'] != lock['sources'][definition['source']]['commit']:
                raise ValueError(f'Worker source changed without re-locking: {name}')
            if definition.get('adapter'):
                from prepare_workers import adapter_identity
                if adapter_identity(definition['adapter']) != definition.get('adapter_files_sha256'):
                    raise ValueError('Worker adapter changed without re-locking')
            raw_lock = (ROOT / 'locks/workers' / definition['lock_file']).read_bytes()
            if digest(raw_lock) != definition['lock_sha256']:
                raise ValueError(f'Worker lock file changed: {name}')
            (worker_locks / definition['lock_file']).write_bytes(raw_lock)
        (worker_locks/'manifest.json').write_text(json.dumps(definitions,indent=2,sort_keys=True)+'\n')
        prepare_worker_install_inputs(context, definitions)
        for script in ['link_gpu_packages.py','install_worker_envs.py']:
            shutil.copyfile(ROOT/'tools/rebuild'/script,context/script)
        nodes_root = context / 'worker-nodes'
        if nodes_root.exists():
            shutil.rmtree(nodes_root)
        def prepare_node(definition):
            source = lock['sources'][definition['source']]
            data = fetch(source['archive_url'])
            if digest(data) != source['archive_sha256']:
                raise ValueError(f"Node source archive hash mismatch: {definition['source']}")
            materialize(data,nodes_root/definition['plugin_directory'])
            if definition.get('adapter'):
                if definition['adapter'] == 'itools':
                    from apply_itools_adapter import apply
                elif definition['adapter'] == 'kjnodes':
                    from apply_kjnodes_adapter import apply
                elif definition['adapter'] == 'vhs':
                    from apply_vhs_adapter import apply
                else:
                    raise ValueError('Unknown worker source adapter')
                apply(nodes_root/definition['plugin_directory'],source,ROOT/'build/adapters'/definition['adapter'])
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(prepare_node,definitions['workers'].values()))
    if args.target == 'runtime-probe':
        runtime_nodes = context / 'runtime-nodes'
        if runtime_nodes.exists():
            shutil.rmtree(runtime_nodes)
        manager_source = lock['sources']['manager']
        manager_data = fetch(manager_source['archive_url'])
        if digest(manager_data) != manager_source['archive_sha256']:
            raise ValueError('Manager source archive hash mismatch')
        materialize(manager_data, runtime_nodes / 'ComfyUI-Manager')
        from apply_manager_adapter import apply as apply_manager
        apply_manager(runtime_nodes / 'ComfyUI-Manager', manager_source)
        control = context / 'runtime'
        if control.exists():
            shutil.rmtree(control)
        shutil.copytree(ROOT / 'runtime', control, ignore=shutil.ignore_patterns('__pycache__', 'comfyctl'))
        shutil.copyfile(ROOT / 'tools/rebuild/link_gpu_packages.py', control / 'gpu_links.py')
        exported = subprocess.check_output(['uv', 'export', '--frozen', '--no-dev', '--no-emit-project',
                                            '--no-header', '--format', 'requirements-txt'], cwd=ROOT, text=True)
        if exported != (ROOT / 'locks/tools/requirements.txt').read_text():
            raise ValueError('Management tool lock disagrees with uv.lock; reproduce the frozen export')
        shutil.copyfile(ROOT / 'locks/tools/requirements.txt', context / 'tools.txt')
        shutil.copyfile(ROOT / 'runtime/comfyctl', context / 'comfyctl')
        cli = context / 'cli-source'
        if cli.exists():
            shutil.rmtree(cli)
        shutil.copytree(ROOT / 'tools/comfyctl', cli, ignore=shutil.ignore_patterns('__pycache__'))
        identity_inputs = {str(path.relative_to(ROOT)): digest(path.read_bytes())
                           for path in [ROOT / 'build/stack.yaml', ROOT / 'docker/Dockerfile.probe',
                                        ROOT / 'locks/upstreams.lock.json', ROOT / 'locks/workers/manifest.json',
                                        ROOT / 'locks/tools/requirements.txt', ROOT / 'uv.lock', ROOT / 'pyproject.toml',
                                        ROOT / 'locks/gpu/linux-amd64-cu128.txt', ROOT / 'locks/host/linux-amd64-cu128.txt',
                                        ROOT / 'tools/rebuild/apply_comfy_env_patch.py',
                                        ROOT / 'tools/rebuild/managed_metadata.py',
                                        ROOT / 'tools/rebuild/link_gpu_packages.py',
                                        ROOT / 'tools/rebuild/apply_manager_adapter.py',
                                        *sorted((ROOT / 'build/adapters/manager').glob('*.py')),
                                        *sorted(p for p in (ROOT / 'runtime').rglob('*') if p.is_file() and '__pycache__' not in p.parts),
                                        *sorted((ROOT / 'tools/comfyctl').glob('*.py'))]}
        runtime_id = digest(json.dumps(identity_inputs, sort_keys=True).encode())
        (control / 'identity.json').write_text(json.dumps({'runtime_id': runtime_id, 'inputs': identity_inputs}, indent=2, sort_keys=True) + '\n')
        internal_plugin = context / 'worker-nodes/ComfyctlRuntimeControl'
        internal_plugin.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / 'runtime/control_plugin.py', internal_plugin / '__init__.py')
        required = stack['runtime_required_nodes']
        if set(required) != set(definitions['workers']):
            raise ValueError('Runtime required-node catalog disagrees with bundled workers')
        baseline = {'runtime_id': runtime_id, 'comfy_root': '/opt/probe/ComfyUI',
                    'worker_ui_packages_omitted': stack['workers']['skip_host_ui_packages'],
                    'host_python': '/opt/runtime/venv/bin/python',
                    'host_lock_sha256': digest((ROOT / 'locks/host/linux-amd64-cu128.txt').read_bytes()),
                    'gpu_lock_sha256': definitions['gpu_lock_sha256'],
                    'workers': {item['environment']: '/opt/workers/' + item['environment'] for item in definitions['workers'].values()},
                    'nodes': {name: {'directory': item['plugin_directory'], 'commit': item['commit'],
                                     'repository': lock['sources'][item['source']]['repository'],
                                     'enabled': True, 'required_nodes': required[name],
                                     'lock_sha256': item['lock_sha256']} for name, item in definitions['workers'].items()}}
        baseline['nodes']['manager'] = {'directory':'ComfyUI-Manager','commit':manager_source['commit'],
            'repository':manager_source['repository'],'enabled':True,'required_nodes':[],
            'required_endpoints':['/comfyctl/manager/status'],'lock_sha256':baseline['host_lock_sha256']}
        baseline.update(execution_contract(stack,lock['sources'],definitions,baseline['host_lock_sha256']))
        (control / 'baseline.json').write_text(json.dumps(baseline, indent=2, sort_keys=True) + '\n')
    if args.prepare_only:
        print(context)
        return
    command = ["docker", "buildx", "build", "--load", "--platform", stack["platform"],
               "--file", str(ROOT / "docker/Dockerfile.probe"), "--target", args.target,
               "--tag", f"runpod-comfyui:probe-{args.target}", "--progress", "plain",
               "--build-arg", f"BASE_IMAGE={stack['base_image']}",
               "--build-arg", f"UV_VERSION={stack['resolver']['uv']}",
               "--build-arg", f"TORCH_BACKEND={stack['gpu']['torch_backend']}",
               "--build-arg", f"WORKER_ATTENTION={stack['gpu']['attention_default']}", str(context)]
    started = time.monotonic()
    with (ROOT / ".work/probe-build.log").open("w") as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
        result = process.wait()
    if result:
        raise subprocess.CalledProcessError(result, command)
    identity = {
        "kind": "local-experimental-build", "target": args.target,
        "host": {"system": platform.system(), "architecture": platform.machine()},
        "image_platform": stack["platform"], "base_image": stack["base_image"],
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "lock_hashes": {name: digest((context / f"{name}.txt").read_bytes()) for name in ["gpu", "host"]},
        "scope": "Local Docker build only; not a GitHub Actions benchmark or GPU validation",
    }
    evidence = ROOT / "tests/evidence" / f"build-probe-{args.target}.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
