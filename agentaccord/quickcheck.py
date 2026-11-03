"""Ephemeral checks of explicitly supplied text. No repository writes or code execution."""
from pathlib import Path
from tempfile import TemporaryDirectory
from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator
from .configuration import Policy, RulePolicy, Examples
from .engine import scan, exit_code
from .rules import RULES


class InputFile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: StrictStr = Field(min_length=1, max_length=120)
    content: StrictStr = Field(max_length=100_000)

    @model_validator(mode='after')
    def safe_name(self):
        if self.name in {'.', '..'} or any(c in self.name for c in '/\\:') or any(ord(c) < 32 for c in self.name):
            raise ValueError('Use a filename without folders or control characters')
        if len(self.content.encode('utf-8')) > 100_000:
            raise ValueError('Each file must be at most 100 KB of UTF-8 text')
        return self


class QuickRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    files: list[InputFile] = Field(min_length=1, max_length=20)
    rules: list[StrictStr] = Field(min_length=1, max_length=50)

    @model_validator(mode='after')
    def validate_request(self):
        if len(set(self.rules)) != len(self.rules) or set(self.rules) - set(RULES):
            raise ValueError('Select unique supported built-in rules')
        if len({f.name for f in self.files}) != len(self.files):
            raise ValueError('File names must be unique')
        if sum(len(f.content.encode('utf-8')) for f in self.files) > 400_000:
            raise ValueError('Selected text must total at most 400 KB')
        return self


def check(body):
    request = QuickRequest.model_validate(body)
    policy = Policy(rules={r: RulePolicy(approved=True) for r in request.rules},
                    examples=Examples(java=['**/*.java']))
    languages = {RULES[r]['language'] for r in request.rules}
    unsupported, names = [], {}
    with TemporaryDirectory(prefix='agentaccord-check-') as directory:
        root = Path(directory)
        for index, file in enumerate(request.files):
            suffix = Path(file.name).suffix.lower()
            language = {'.java': 'Java', '.py': 'Python', '.json': 'JSON'}.get(suffix)
            if (suffix != '.md' and (language is None or language not in languages)):
                unsupported.append(dict(path=file.name, reason='Unsupported file type or no selected rule for its language'))
                continue
            # Internal names are generated; supplied names never become filesystem paths.
            rel = f'file{index}/' + ('SKILL.md' if suffix == '.md' else 'source' + suffix)
            names[rel] = file.name
            destination = root / rel
            destination.parent.mkdir()
            destination.write_text(file.content, encoding='utf-8')
        report = scan(root, policy.active(), catalog=policy.catalog(), examples=policy.examples, capture_scope=True)
    for collection in ('findings', 'skipped', 'scope_files', 'rule_scope_omissions'):
        for item in report.get(collection, []):
            item['path'] = names.get(item['path'], item['path'])
    report['skipped'].extend(unsupported)
    report['limitations'].append('Quick check uses only supplied text and explicitly selected rules. Java files are teaching examples; findings are warnings. Markdown checks explicit Java instruction patterns and Java/Python/JSON fences; other prose and fenced languages are not validated. No project policy or baseline is applied.')
    return dict(report=report, exit_code=exit_code(report))
