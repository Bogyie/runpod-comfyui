from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .models import MODEL_TYPES, ModelError, ModelStore


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="comfyctl")
    parser.add_argument("--storage", type=Path, default=Path(os.environ.get("COMFYCTL_STORAGE_DIR", os.environ.get("STORAGE_DIR", "/workspace/storage"))))
    parser.add_argument("--state", type=Path, default=Path(os.environ.get("COMFYCTL_STATE_DIR", "/workspace/state/comfyctl")))
    commands = parser.add_subparsers(dest="command", required=True)
    model = commands.add_parser("model")
    actions = model.add_subparsers(dest="action", required=True)
    add = actions.add_parser("add")
    add.add_argument("source")
    add.add_argument("--type", choices=sorted(MODEL_TYPES), dest="model_type")
    add.add_argument("--target")
    add.add_argument("--sha256")
    add.add_argument("--file-id", type=int)
    status = actions.add_parser("status")
    status.add_argument("--verify", action="store_true")
    sync = actions.add_parser("sync")
    sync.add_argument("manifest", type=Path)
    env = commands.add_parser("env")
    env_actions = env.add_subparsers(dest="action", required=True)
    env_actions.add_parser("status", help="Inspect image environment versions, paths and live runtime state")
    doctor = env_actions.add_parser("doctor", help="Check dependencies and runtime API; no package changes")
    doctor.add_argument("--deep", action="store_true", help="Also verify installed RECORD file hashes (may take time)")
    for name in ['rollback', 'reset']:
        operation = env_actions.add_parser(name, help="Select a preserved/default generation for the next restart")
        mode = operation.add_mutually_exclusive_group(required=True)
        mode.add_argument('--defer', action='store_true', help='Apply on the next container restart')
        mode.add_argument('--restart', action='store_true', help='Drain and restart the running service')
        operation.add_argument('--drain-timeout', type=float, default=300)
        operation.add_argument('--startup-timeout', type=float, default=330)
    node = commands.add_parser('node')
    node_actions = node.add_subparsers(dest='action', required=True)
    plan = node_actions.add_parser('plan', help='Inspect a pinned node source without importing or installing it')
    plan.add_argument('repository')
    plan.add_argument('--commit', required=True)
    plan.add_argument('--archive-sha256')
    plan.add_argument('--archive', type=Path, help='Inspect a local archive with a required SHA256')
    node_add = node_actions.add_parser('add', help='Build and validate a source-pinned node with a complete reviewed worker lock')
    node_add.add_argument('repository')
    node_add.add_argument('--name', required=True)
    node_add.add_argument('--commit', required=True)
    node_add.add_argument('--archive-sha256')
    node_add.add_argument('--archive', type=Path)
    node_add.add_argument('--lock', type=Path, help='Use a reviewed complete wheel lock; otherwise resolve in an isolated candidate')
    node_add.add_argument('--mode', choices=['auto', 'native', 'adapter'], default='auto')
    node_add.add_argument('--skip-hooks', action='store_true')
    node_add.add_argument('--required-node', action='append', required=True)
    node_add.add_argument('--smoke-workflow', type=Path, required=True)
    add_mode = node_add.add_mutually_exclusive_group(required=True)
    add_mode.add_argument('--defer', action='store_true')
    add_mode.add_argument('--restart', action='store_true')
    node_add.add_argument('--drain-timeout', type=float, default=300)
    node_add.add_argument('--startup-timeout', type=float, default=330)
    for name in ['disable', 'enable']:
        operation = node_actions.add_parser(name, help="Validate a state-only generation for the next restart")
        operation.add_argument('name')
        mode = operation.add_mutually_exclusive_group(required=True)
        mode.add_argument('--defer', action='store_true')
        mode.add_argument('--restart', action='store_true')
        operation.add_argument('--drain-timeout', type=float, default=300)
        operation.add_argument('--startup-timeout', type=float, default=330)
    apply = env_actions.add_parser('apply', help='Drain and apply the staged desired generation')
    apply.add_argument('--restart', action='store_true', required=True)
    apply.add_argument('--drain-timeout', type=float, default=300)
    apply.add_argument('--startup-timeout', type=float, default=330)
    args = parser.parse_args(argv)
    mutation = (args.command == 'node' and args.action != 'plan') or (args.command == 'env' and args.action in {'rollback', 'reset', 'apply'})
    if mutation:
        if os.geteuid() != 0 or not Path('/opt/runtime/control/baseline.json').is_file():
            print('comfyctl: Generation mutation requires the managed container administrator (uid 0)', file=sys.stderr)
            return 1
        from .generations import operate, SelectionError
        try:
            print(json.dumps(operate(args), indent=2))
            return 0
        except (SelectionError, OSError, ValueError, KeyError) as exc:
            print('comfyctl: ' + str(exc), file=sys.stderr)
            return 1
    # RunPod terminals often start as root. Downloads and diagnostics should
    # use the same identity as ComfyUI, without leaving root-owned user files.
    if os.environ.get('COMFYCTL_SERVICE_UID') == '1000' and os.getuid() == 0:
        os.setgroups([])
        os.setgid(1000)
        os.setuid(1000)
    if os.environ.get('COMFYCTL_SERVICE_UID') == '1000':
        import ctypes
        os.umask(0o027)
        if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0):
            raise OSError(ctypes.get_errno(), 'Cannot set no_new_privs')
    from .environments import EnvironmentError
    try:
        if args.command == 'node':
            from .node_sources import plan_source
            result = plan_source(args.repository, args.commit, args.archive_sha256, args.archive)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        if args.command == 'env':
            from .environments import inspect_runtime
            result = inspect_runtime(args.state, doctor=args.action == 'doctor', deep=getattr(args, 'deep', False))
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if args.action == 'status' or result['ok'] else 2
        store = ModelStore(args.storage / "models", args.state)
        if args.action == "add":
            result = store.add(args.source, args.model_type, args.target, args.sha256, args.file_id)
        elif args.action == "status":
            result = store.status(args.verify)
        else:
            import yaml
            try:
                manifest = yaml.safe_load(args.manifest.read_text())
            except yaml.YAMLError:
                raise ModelError("Model manifest is not valid YAML") from None
            if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(manifest.get("models"), list):
                raise ModelError("Manifest requires schema_version: 1 and a models list")
            result = []
            for entry in manifest["models"]:
                if not isinstance(entry, dict):
                    raise ModelError("Each manifest model must be a mapping")
                source = entry.get("source") or entry.get("hf_down_url")
                target = entry.get("target") or entry.get("target_path")
                if target and not isinstance(target, str):
                    raise ModelError("Model target must be a relative path string")
                if target and target.startswith("models/"):
                    target = target[len("models/"):]
                if not source or not target:
                    raise ModelError("Each manifest model needs source and target")
                receipt = store.add(source, target=target, expected_hash=entry.get("sha256"), file_id=entry.get("file_id"))
                result.append(receipt)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ModelError, EnvironmentError, OSError, ValueError, KeyError) as exc:
        # URL-bearing provider exceptions are converted to ModelError before this boundary.
        print(f"comfyctl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
