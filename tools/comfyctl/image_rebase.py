"""Explicitly validate preserved node sources against a different image contract."""
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from selection import Store, SelectionError, durable_json
from .candidate_env import frozen_pins, verify_gpu_pins
from .candidate_resolve import base_requirements


def satisfies(requirements,pins):
    for value in requirements:
        requirement=Requirement(value)
        if requirement.marker and not requirement.marker.evaluate({'sys_platform':'linux','platform_machine':'x86_64',
                'platform_system':'Linux','os_name':'posix','python_version':'3.11'}):
            continue
        name=canonicalize_name(requirement.name)
        if requirement.url or name not in pins or not requirement.specifier.contains(pins[name],prereleases=True):
            return False
    return True


def reusable_environment(current,source,profile,node):
    """Called only after the old generation's complete seal was verified."""
    from .node_install import declared_requirements
    if current.base['abi_id']!=source.base['abi_id']:
        return None
    prefixes={node_profile for name,node_profile in profile['workers'].items()
              if name in node['environment_keys']}
    if len(prefixes)!=1:return None
    prefix=Path(prefixes.pop())
    lock=prefix.parent/'requirements.txt'
    pins=frozen_pins(lock.read_bytes())
    gpu=frozen_pins(Path('/opt/locks/gpu.txt').read_bytes())
    host=frozen_pins(Path('/opt/locks/host.txt').read_bytes())
    verify_gpu_pins(pins,gpu)
    requirements=base_requirements(Path(current.base['comfy_root'],'requirements.txt').read_text(),
                                 gpu,host,current.base['worker_ui_packages_omitted'])
    if not satisfies(requirements+declared_requirements(node['source_plan']),pins):return None
    bindings=profile['environment_bindings']
    values=[bindings[key] for key in node['environment_keys']]
    if any(value!=values[0] for value in values):return None
    return {'prefix':str(prefix),'binding':values[0],'lock':lock}


def restore_node_states(store,profile,states):
    root=Path(profile['comfy_root'])/'custom_nodes'
    changed=False
    for name,enabled in states.items():
        if name not in profile['nodes']:continue
        node=profile['nodes'][name]
        if node['enabled']==enabled:continue
        before=node['directory']+('' if node['enabled'] else '.disabled')
        after=node['directory']+('' if enabled else '.disabled')
        (root/before).rename(root/after)
        node['enabled']=enabled
        changed=True
    if changed:
        profile['validation']=None
        return store.save_candidate(profile)
    return profile


def rebase(store,source_identity):
    from .node_install import stage_node
    from .generations import validate
    if not store.images.enabled:
        raise SelectionError('Rebase requires an image compatibility manifest')
    if source_identity==store.images.key:
        raise SelectionError('This image is already compatible; use normal node/rollback commands')
    if store.pending_transition():
        raise SelectionError('Unfinished live transition; recover the previous image first')
    directory=store.images.directory(source_identity)
    baseline=directory/'baseline.json'
    if not baseline.is_file() or baseline.is_symlink():
        raise SelectionError('Previous image baseline is missing or unsafe')
    source=Store(store.control,store.generations,baseline)
    if source.images.key!=source_identity or source.base.get('generation_schema',1)<2:
        raise SelectionError('Previous image lacks verified rebase provenance')
    snapshot=source.images.load_selection(directory/'selection.json')
    if snapshot.get('compatibility_id')!=source_identity:
        raise SelectionError('Previous image selection identity drift')
    old=source.profile(snapshot['desired'],verify_environments=False)
    extras=sorted(old['nodes'].keys()-source.base['nodes'].keys())
    if set(extras)&store.base['nodes'].keys():
        raise SelectionError('An added node now collides with the image catalog; resolve explicitly')
    # A damaged private environment can be rebuilt from sealed source. Reuse,
    # however, requires every old private receipt and file to pass verification.
    reusable=False
    if source.base['abi_id']==store.base['abi_id']:
        try:
            source.profile(snapshot['desired'])
            reusable=True
        except (SelectionError,OSError,ValueError,KeyError):
            pass
    states={name:node['enabled'] for name,node in old['nodes'].items()}
    profile=store.fork_code(store.profile('image-base'))
    profile=restore_node_states(store,profile,{name:enabled for name,enabled in states.items() if name in store.base['nodes']})
    profile=store.save_candidate(profile)
    decisions={}
    for name in extras:
        node=old['nodes'][name]
        reuse=reusable_environment(store,source,old,node) if reusable else None
        args=SimpleNamespace(name=name,action='add',repository=node['repository'],commit=node['commit'],
            archive=Path(node['source_archive']),archive_sha256=node['archive_sha256'],
            skip_hooks=bool(node['hooks_skipped']),mode=node['install_mode'],
            lock=reuse['lock'] if reuse else None,required_node=node['required_nodes'],
            smoke_workflow=store.generations/profile['id']/('rebase-smoke-'+name+'.json'))
        durable_json(args.smoke_workflow,node['smoke_workflow'])
        profile,_=stage_node(store,args,parent=profile,reuse_environment=reuse)
        decisions[name]='reused-verified-prefix' if reuse else 'rebuilt-private-environment'
    workflows=[old['nodes'][name]['smoke_workflow'] for name in extras]
    profile=validate(store,profile,workflows)
    smoke_receipt=json.loads(json.dumps(profile['validation']))
    profile=restore_node_states(store,profile,states)
    if profile['validation'] is None:
        profile=validate(store,profile)
    profile['validation']['rebase']={'from_compatibility_id':source_identity,'environments':decisions,
                                     'source_generation':old['id'],'added_node_smokes':smoke_receipt}
    profile=store.validated(profile,profile['validation'])
    # No selection write occurs until all installation and validation succeeds.
    # Preserve the outgoing image's snapshot and raw state before one atomic
    # desired update. Image rollback remains a redeploy of its original digest.
    store.images.register()
    if store.state_file.exists():
        current=store.images.load_selection(store.state_file)
        store.images.save(current)
        durable_json(store.control/('previous-selection-'+uuid.uuid4().hex+'.json'),current)
    else:
        current=store.state()
    if current.get('compatibility_id')!=store.images.key:
        current={'runtime_id':store.base['runtime_id'],'desired':'image-base','last_good':None,
                 'previous_good':None,'revision':current['revision']}
    current.update(runtime_id=store.base['runtime_id'],desired=profile['id'],revision=current['revision']+1)
    store.write_state(current)
    return {'selection':current,'restart_required':True,'applied_to_running_process':False,
            'from_compatibility_id':source_identity,'environments':decisions,
            'scope':'Validated CPU rebase; restart container to apply. GPU workflows require separate verification.'}
