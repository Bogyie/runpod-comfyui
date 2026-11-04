"""Assemble a source-pinned node and private environment without active mutation."""
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from .candidate_env import prepare_environment, frozen_pins
from .node_sources import analyze, archive_files, download, source_identity, ARCHIVE_LIMIT, NodeSourceError


def environment_name(plugin, config):
    name = plugin.lower()
    for prefix in ['comfyui-', 'comfyui_']:
        if name.startswith(prefix):
            name = name[len(prefix):]
    name = name.replace('-', '').replace('_', '').replace(' ', '')
    parent = Path(config).parent
    suffix = parent.name.lower().replace('-', '').replace('_', '') if str(parent) != '.' else ''
    return name + ('-' + suffix if suffix else '')


def declared_requirements(plan):
    requirements = []
    for item in plan['requirements']:
        if item['review_required_lines']:
            raise NodeSourceError('Node requirements contain unsupported includes/options/direct URLs; normalize them before installation')
        requirements.extend(item['requirements'])
    for path, config in plan['configuration'].items():
        if Path(path).name != 'comfy-env.toml':
            continue
        if any(not isinstance(config.get(field, {}), dict) for field in ['cuda', 'dependencies', 'pypi-dependencies', 'env_vars']):
            raise NodeSourceError('Node comfy-env configuration has an unsupported table shape')
        if config.get('cuda', {}).get('packages'):
            raise NodeSourceError('Node CUDA extensions require an image build and GPU validation')
        for name, spec in config.get('dependencies', {}).items():
            if name != 'python' or spec not in {'*', '3.11', '3.11.*'}:
                raise NodeSourceError('Node system/Conda dependency requires image integration: ' + name)
        for name, spec in config.get('pypi-dependencies', {}).items():
            if not isinstance(spec, str):
                raise NodeSourceError('Node PyPI dependency needs normalization: ' + name)
            requirements.append(name + ('' if spec == '*' else spec))
        for name in config.get('env_vars', {}):
            if name.startswith(('PYTHON', 'LD_', 'COMFYCTL', 'COMFYUI_')) or name in {'PATH', 'HOME', 'TMPDIR', 'CUDA_VISIBLE_DEVICES'}:
                raise NodeSourceError('Node configuration overrides a managed environment variable: ' + name)
    result = []
    for value in requirements:
        requirement = Requirement(value)
        if requirement.url:
            raise NodeSourceError('Direct dependency URLs need normalization into the reviewed wheel lock')
        if requirement.marker and not requirement.marker.evaluate({'sys_platform': 'linux', 'platform_machine': 'x86_64', 'platform_system': 'Linux', 'os_name': 'posix', 'python_version': '3.11'}):
            continue
        # Resolve for this one Linux image, not a universal/moving platform set.
        requirement.marker = None
        result.append(str(requirement))
    return sorted(set(result))


def inspect_requirements(plan, pins):
    for value in declared_requirements(plan):
        requirement = Requirement(value)
        name = canonicalize_name(requirement.name)
        if name not in pins or not requirement.specifier.contains(pins[name], prereleases=True):
            raise NodeSourceError('Candidate lock does not satisfy declared node dependency: ' + value)


def extract_source(data, destination, expected_files):
    files, _, _, _ = archive_files(data)
    if files != expected_files:
        raise NodeSourceError('Node archive changed after source inspection')
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive:
            if not member.isfile():
                continue
            relative = Path(*Path(member.name).parts[1:])
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            content = stream.read()
            if hashlib.sha256(content).hexdigest() != files[relative.as_posix()]:
                raise NodeSourceError('Extracted node source hash mismatch')
            target.write_bytes(content)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)


def stage_node(store, args):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', args.name):
        raise NodeSourceError('Node name must be lowercase letters/digits/dashes, beginning with a letter')
    parent = store.desired()
    if args.name in parent['nodes']:
        raise NodeSourceError('Managed node already exists; use disable/enable or a reviewed update')
    repository, commit = source_identity(args.repository, args.commit)
    if args.archive:
        if not args.archive_sha256:
            raise NodeSourceError('Offline node installation requires --archive-sha256')
        with args.archive.open('rb') as stream:
            data = stream.read(ARCHIVE_LIMIT + 1)
    else:
        data = download(repository, commit)
    plan = analyze(repository, commit, data, args.archive_sha256)
    if plan['hooks'] and not args.skip_hooks:
        raise NodeSourceError('Node contains install/startup/build hooks; review node plan and explicitly use --skip-hooks or integrate it in an image build')
    if plan['unparsed_text']:
        raise NodeSourceError('Node contains unparsed source/configuration; use a reviewed image adapter')
    mode = ('native' if plan['classification'] == 'native-comfy-env-candidate' else 'adapter') if args.mode == 'auto' else args.mode
    configs = plan['classification_evidence']['worker_configurations']
    if mode == 'native' and plan['classification'] != 'native-comfy-env-candidate':
        raise NodeSourceError('Native mode requires upstream comfy-env configuration and registration')
    if mode == 'adapter' and configs:
        raise NodeSourceError('Existing comfy-env configuration needs native mode or a reviewed custom adapter')
    requirements = declared_requirements(plan)
    lock_data = args.lock.read_bytes() if args.lock else None
    if lock_data:
        inspect_requirements(plan, frozen_pins(lock_data))
    if mode == 'adapter':
        _, texts, _, _ = archive_files(data)
        if any('PromptServer' in value or 'from server import' in value for path, value in texts.items() if path.endswith('.py')):
            raise NodeSourceError('Host server hooks require a reviewed custom adapter; generic worker isolation is insufficient')
    workflow = json.loads(args.smoke_workflow.read_text())
    if not isinstance(workflow, dict) or not any(item.get('class_type') in args.required_node for item in workflow.values() if isinstance(item, dict)):
        raise NodeSourceError('Smoke workflow must contain at least one required added node')
    profile = store.fork_code()
    generation = store.generations / profile['id']
    if lock_data is None:
        from .candidate_resolve import resolve_environment
        lock_data = resolve_environment(generation, requirements)
        inspect_requirements(plan, frozen_pins(lock_data))
    directory = 'ComfyUI-' + args.name
    destination = Path(profile['comfy_root']) / 'custom_nodes' / directory
    if destination.exists():
        raise NodeSourceError('Node source directory collides with existing code')
    if mode == 'adapter':
        destination.mkdir()
        extract_source(data, destination / 'managed_worker', plan['files'])
        (destination / '__init__.py').write_text('from comfy_env import register_nodes\nNODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS = register_nodes(nodes_package="managed_worker")\n' +
            ('WEB_DIRECTORY = "./managed_worker/web"\n' if (destination / 'managed_worker/web').is_dir() else ''))
        (destination / 'managed_worker/comfy-env.toml').write_text('# Dependency installation is managed by the sealed candidate lock.\n')
        configs = ['managed_worker/comfy-env.toml']
    else:
        extract_source(data, destination, plan['files'])
    # ComfyUI executes root prestartup hooks independently of node imports.
    # Preserve skipped scripts as evidence but make them ineligible at boot.
    for path in destination.rglob('prestartup_script.py'):
        path.rename(path.with_name('prestartup_script.py.disabled'))
    keys = [environment_name(directory, config) for config in configs]
    if len(set(keys)) != len(keys) or any(key in profile['workers'] for key in keys):
        raise NodeSourceError('Node worker environment name collides with an existing mapping')
    receipt = prepare_environment(generation, args.name, lock_data, hashlib.sha256(lock_data).hexdigest())
    receipt_path = Path(receipt['prefix']).parent / 'receipt.json'
    binding = {'lock_sha256': receipt['lock_sha256'], 'receipt_sha256': hashlib.sha256(receipt_path.read_bytes()).hexdigest()}
    profile.update(kind='managed-nodes-v1')
    bindings = profile.setdefault('environment_bindings', {})
    for key in keys:
        profile['workers'][key] = receipt['prefix']
        bindings[key] = binding
    profile['nodes'][args.name] = {'directory': directory, 'enabled': True, 'repository': repository, 'commit': commit,
        'archive_sha256': plan['archive_sha256'], 'source_plan_sha256': plan['plan_sha256'], 'source_plan': plan,
        'install_mode': mode, 'hooks_skipped': plan['hooks'], 'environment_keys': keys,
        'required_nodes': args.required_node, 'lock_sha256': receipt['lock_sha256']}
    return store.save_candidate(profile), workflow
