"""Configure identical ComfyUI data paths before importing node code."""
import os
from pathlib import Path


def configure():
    root = Path(os.environ['COMFYCTL_STORAGE_DIR'])
    source = Path(os.environ.get('COMFYCTL_COMFY_ROOT', '/opt/probe/ComfyUI'))
    if not root.is_absolute() or not source.is_absolute():
        raise RuntimeError('Runtime source and storage paths must be absolute')
    from comfy.cli_args import args
    managed = {'base_directory': root, 'models_directory': root / 'models',
               'input_directory': root / 'input', 'output_directory': root / 'output',
               'user_directory': root / 'user', 'temp_directory': root,
               'previews_directory': root / 'previews'}
    for name, expected in managed.items():
        requested = getattr(args, name, None)
        if requested and Path(requested) != expected:
            raise RuntimeError(f'Managed runtime requires {name}={expected}')
    if args.extra_model_paths_config or (source / 'extra_model_paths.yaml').exists():
        raise RuntimeError('Extra model path configs are not yet propagated to managed workers; use /workspace/storage/models')
    args.base_directory = str(root)
    args.models_directory = str(root / 'models')
    args.input_directory = str(root / 'input')
    args.output_directory = str(root / 'output')
    args.user_directory = str(root / 'user')
    args.previews_directory = str(root / 'previews')
    # main.py appends /temp to this flag.
    args.temp_directory = str(root)
    import folder_paths
    # A source import before path setup would leave its model mappings stale.
    if Path(folder_paths.models_dir) != root / 'models':
        raise RuntimeError('folder_paths was imported before runtime storage setup')
    folder_paths.folder_names_and_paths['custom_nodes'] = ([str(source / 'custom_nodes')], set())
    folder_paths.set_input_directory(str(root / 'input'))
    folder_paths.set_output_directory(str(root / 'output'))
    folder_paths.set_user_directory(str(root / 'user'))
    folder_paths.set_temp_directory(str(root / 'temp'))
    folder_paths.previews_directory = str(root / 'previews')
    # Match ComfyUI main.apply_custom_paths in metadata scans and workers.
    for name in ['checkpoints', 'clip', 'vae', 'diffusion_models', 'loras']:
        folder_paths.add_model_folder_path(name, str(root / 'output' / name))
