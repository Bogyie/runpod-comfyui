"""Select reviewed root requirements; never run package installation hooks."""
import re


def name(requirement):
    match=re.match(r'([A-Za-z0-9][A-Za-z0-9_.-]*)',requirement)
    if not match:raise ValueError('Unsupported requirement: '+requirement)
    return re.sub(r'[-_.]+','-',match[1]).lower()


def select(requirements,files,policy,environment):
    if not policy:return list(requirements)
    existing={name(r) for r in requirements if r.strip() and not r.lstrip().startswith('#')}
    if not set(policy).issubset(existing):raise ValueError('Unknown root requirement policy')
    for package,rule in policy.items():
        if not rule.get('reason') or not rule.get('evidence_files') or not all(p in files for p in rule['evidence_files']):
            raise ValueError('Missing reviewed root-requirement evidence: '+package)
        if any(environment.get(k)!=v for k,v in rule.get('requires_env',{}).items()):
            raise ValueError('Root requirement omission needs explicit runtime environment: '+package)
        replacement=rule.get('replacement')
        if replacement is not None:name(replacement)
    selected=[]
    for requirement in requirements:
        if not requirement.strip() or requirement.lstrip().startswith('#'):selected.append(requirement);continue
        rule=policy.get(name(requirement))
        if rule is None:selected.append(requirement)
        elif rule.get('replacement') is not None:selected.append(rule['replacement'])
    return selected
