"""Validated approved policies. Unapproved rules never block checks."""
import os
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator
from .rules import RULES

def validate_patterns(patterns):
    for pattern in patterns:
        if (not pattern or len(pattern) > 200 or pattern != pattern.strip()
                or pattern.startswith('/') or '\\' in pattern
                or any(part in ('', '.', '..') for part in pattern.split('/'))):
            raise ValueError(f'Invalid path pattern: {pattern!r}. Use repository-relative globs')
    if len(set(patterns)) != len(patterns):
        raise ValueError('Duplicate path patterns')


class PathScope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    include: list[StrictStr] = Field(default_factory=list, max_length=50)
    exclude: list[StrictStr] = Field(default_factory=list, max_length=50)

    @model_validator(mode='after')
    def validate_scope(self):
        validate_patterns(self.include)
        validate_patterns(self.exclude)
        return self


class Examples(BaseModel):
    model_config = ConfigDict(extra='forbid')
    java: list[StrictStr] = Field(default_factory=list, max_length=50)
    counter_examples: list[StrictStr] = Field(default_factory=list, max_length=50)

    @model_validator(mode='after')
    def validate_paths(self):
        validate_patterns(self.java)
        validate_patterns(self.counter_examples)
        return self


class RulePolicy(PathScope):
    model_config = ConfigDict(extra='forbid')
    enabled: StrictBool = True
    approved: StrictBool = False
    severity: Literal['error', 'warning'] = 'error'
    allow_job_parameters: StrictBool = False

JAVA_NAME = r'[A-Za-z_$][A-Za-z0-9_$]*'


class CustomRule(BaseModel):
    """A team-defined prohibited Java annotation, checked like the built-in Spring rules."""
    model_config = ConfigDict(extra='forbid')
    title: StrictStr = Field(min_length=1, max_length=80)
    annotation: StrictStr = Field(pattern=rf'^{JAVA_NAME}(?:\.{JAVA_NAME})+$', max_length=200)
    guidance: StrictStr = Field(min_length=1, max_length=300)
    remediation: StrictStr | None = Field(default=None, max_length=300)
    target: Literal['any', 'field'] = 'any'


class Policy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: StrictInt = 1
    rules: dict[str, RulePolicy] = Field(default_factory=dict)
    # Approved scope exclusions (e.g. teaching examples). Excluded files are counted in reports.
    exclude: list[StrictStr] = Field(default_factory=list, max_length=50)
    examples: Examples = Field(default_factory=Examples)
    # Team-defined rules (ids start with "custom."); like built-ins they run only once approved.
    custom: dict[str, CustomRule] = Field(default_factory=dict, max_length=50)

    @model_validator(mode='after')
    def validate_contract(self):
        if self.version != 1:
            raise ValueError('Only policy version 1 is supported')
        for rule in self.custom:
            if not re.fullmatch(r'custom\.[a-z0-9][a-z0-9-]{0,62}', rule):
                raise ValueError(f'Custom rule id {rule!r} must look like custom.no-lombok-data')
        unknown = set(self.rules) - set(RULES) - set(self.custom)
        if unknown:
            raise ValueError('Unknown rules: ' + ', '.join(sorted(unknown)))
        validate_patterns(self.exclude)
        for rule, settings in self.rules.items():
            if settings.allow_job_parameters and rule != 'spring.no-value':
                raise ValueError('allow_job_parameters is supported only by spring.no-value')
        return self

    def catalog(self):
        """Built-in rules plus this policy's custom rules, in the shape the analyzers expect."""
        merged = {key: dict(spec) for key, spec in RULES.items()}
        for rule, spec in self.custom.items():
            simple = spec.annotation.rsplit('.', 1)[-1]
            merged[rule] = {'title': spec.title, 'language': 'Java', 'guidance': spec.guidance,
                'remediation': spec.remediation or spec.guidance, 'annotation': simple,
                'imports': [spec.annotation], 'custom': True,
                **({'target': 'field'} if spec.target == 'field' else {})}
        for rule, settings in self.rules.items():
            merged[rule]['include'] = settings.include
            merged[rule]['exclude'] = settings.exclude
            if settings.include or settings.exclude:
                scope = (' Included paths: ' + ', '.join(settings.include) + '.' if settings.include else '')
                scope += (' Excluded paths: ' + ', '.join(settings.exclude) + '.' if settings.exclude else '')
                merged[rule]['guidance'] += scope
            if settings.allow_job_parameters:
                merged[rule]['allow_job_parameters'] = True
                merged[rule]['guidance'] += ' Exception: literal @Value jobParameters lookups are allowed.'
        return merged

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


POLICY_FILE = '.agentaccord.yml'
# Earlier names, still read so existing repositories keep working. The first match wins;
# saving always writes POLICY_FILE, which then takes precedence (the old file is retained).
LEGACY_YAML = '.agentcontract.yml'    # AgentContract 0.3
LEGACY_TOML = '.agentcontract.toml'   # AgentContract 0.1/0.2
POLICY_FILES = (POLICY_FILE, LEGACY_YAML, LEGACY_TOML)


def load(root, optional=False):
    path = next((root / name for name in (POLICY_FILE, LEGACY_YAML)
                 if (root / name).exists() or (root / name).is_symlink()), None)
    if path is not None:
        source = read_regular(path)
        # No aliases: avoid recursive and expansion-based YAML inputs.
        if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(source)):
            raise ValueError('YAML aliases and anchors are not supported')
        data = yaml.load(source, Loader=UniqueLoader)
        return Policy.model_validate(data)
    legacy = root / LEGACY_TOML
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
    raise ValueError('No policy found. Run agentaccord init, then approve rules in agentaccord serve.')


def save(root, policy):
    target = root / POLICY_FILE
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError('Refusing to replace a non-regular policy file')
    data = policy.model_dump()
    if not any(data['examples'].values()):
        del data['examples']
    for settings in data['rules'].values():
        for key in ('include', 'exclude', 'allow_job_parameters'):
            if not settings[key]:
                del settings[key]
    for optional in ('exclude', 'custom'):
        if not data[optional]:
            del data[optional]  # keep existing policy files unchanged when the feature is unused
    for spec in data.get('custom', {}).values():
        if spec['remediation'] is None:
            del spec['remediation']
        if spec['target'] == 'any':
            del spec['target']
    serialized = yaml.safe_dump(data, sort_keys=False)
    fd, temporary = tempfile.mkstemp(prefix='.agentaccord-', dir=root)
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
    fd, temporary = tempfile.mkstemp(prefix='.agentaccord-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
