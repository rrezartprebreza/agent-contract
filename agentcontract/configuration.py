"""Validated approved policies. Unapproved rules never block checks."""
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator
from .rules import RULES

class RulePolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: StrictBool = True
    approved: StrictBool = False
    severity: Literal['error', 'warning'] = 'error'

class Policy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: StrictInt = 1
    rules: dict[str, RulePolicy] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_contract(self):
        if self.version != 1:
            raise ValueError('Only policy version 1 is supported')
        unknown = set(self.rules) - set(RULES)
        if unknown:
            raise ValueError('Unknown rules: ' + ', '.join(sorted(unknown)))
        return self

    def active(self):
        return {rule: p.severity for rule, p in self.rules.items() if p.enabled and p.approved}

class UniqueLoader(yaml.SafeLoader):
    pass

def unique_mapping(loader, node, deep=False):
    result = {}
    for key, value in node.value:
        name = loader.construct_object(key, deep=deep)
        if not isinstance(name, str) or name in result:
            raise ValueError('Policy mapping keys must be unique strings')
        result[name] = loader.construct_object(value, deep=deep)
    return result
UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def read_regular(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError(f'{path.name} must be a regular file under 1 MB')
    return path.read_text(encoding='utf-8')


def load(root, optional=False):
    path = root / '.agentcontract.yml'
    if path.exists() or path.is_symlink():
        source = read_regular(path)
        # No aliases: avoid recursive and expansion-based YAML inputs.
        if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(source)):
            raise ValueError('YAML aliases and anchors are not supported')
        data = yaml.load(source, Loader=UniqueLoader)
        return Policy.model_validate(data)
    legacy = root / '.agentcontract.toml'
    if legacy.exists() or legacy.is_symlink():
        data = tomllib.loads(read_regular(legacy))
        if set(data) != {'version', 'rules'} or type(data['version']) is not int or data['version'] != 1:
            raise ValueError('Invalid legacy TOML policy')
        rules = data['rules']
        if not isinstance(rules, dict) or not rules:
            raise ValueError('Legacy TOML requires a nonempty rules table')
        if any(value not in ('error', 'warning', 'off') for value in rules.values()):
            raise ValueError('Invalid legacy rule severity')
        return Policy(rules={key: RulePolicy(approved=True, enabled=value != 'off', severity='error' if value == 'off' else value) for key, value in rules.items()})
    if optional:
        return Policy()
    raise ValueError('No policy found. Run agentcontract init, then approve rules in agentcontract serve.')


def save(root, policy):
    target = root / '.agentcontract.yml'
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError('Refusing to replace a non-regular policy file')
    serialized = yaml.safe_dump(policy.model_dump(), sort_keys=False)
    fd, temporary = tempfile.mkstemp(prefix='.agentcontract-', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(serialized)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_write(path, content):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('Refusing to replace a non-regular file')
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, temporary = tempfile.mkstemp(prefix='.agentcontract-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
