"""Accepted existing findings. A baseline can only shrink: new violations are never absorbed."""
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator
from .configuration import atomic_write

FILENAME = '.agentaccord-baseline.json'
LEGACY_FILENAME = '.agentcontract-baseline.json'  # AgentContract (former name); read, never written
MAX_BYTES = 5_000_000


class Entry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rule: StrictStr
    path: StrictStr
    count: StrictInt = Field(ge=1)


class Baseline(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: StrictInt = 1
    created: StrictStr
    findings: dict[str, Entry] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_contract(self):
        if self.version != 1:
            raise ValueError('Only baseline version 1 is supported')
        if any(not re.fullmatch(r'[0-9a-f]{32}', key) for key in self.findings):
            raise ValueError('Baseline fingerprints must be 32 lowercase hex characters')
        return self


def present(root):
    return next((root / name for name in (FILENAME, LEGACY_FILENAME)
                 if (root / name).exists() or (root / name).is_symlink()), None)


def load(root):
    path = present(root)
    if path is None:
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError(f'{path.name} must be a regular file under 5 MB')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        raise ValueError(f'{path.name} is not valid JSON: {error}') from error
    return Baseline.model_validate(data)


def entries(findings):
    counts = Counter(f['fingerprint'] for f in findings)
    first = {}
    for f in findings:
        first.setdefault(f['fingerprint'], f)
    return {fp: Entry(rule=first[fp]['rule'], path=first[fp]['path'], count=n) for fp, n in sorted(counts.items())}


def write(root, baseline):
    text = json.dumps(baseline.model_dump(), indent=2, sort_keys=True, ensure_ascii=False) + '\n'
    atomic_write(root / FILENAME, text)


def create(root, report):
    if not report.get('approved_rules'):
        raise ValueError('Approve at least one rule before creating a baseline')
    existing = present(root)
    if existing is not None:
        raise ValueError(f'{existing.name} already exists; refusing overwrite. Use --prune to remove fixed entries')
    baseline = Baseline(created=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                        findings=entries(report['findings']))
    write(root, baseline)
    return sum(entry.count for entry in baseline.findings.values())


def prune(root, report):
    """Drop entries that no longer occur and lower counts that shrank. Never adds or raises counts."""
    baseline = load(root)
    if baseline is None:
        raise ValueError(f'No {FILENAME} to prune. Create one with agentaccord baseline')
    current = Counter(f['fingerprint'] for f in report['findings'])
    kept = {fp: entry.model_copy(update={'count': min(entry.count, current[fp])})
            for fp, entry in baseline.findings.items() if current[fp]}
    removed = sum(e.count for e in baseline.findings.values()) - sum(e.count for e in kept.values())
    if removed:
        write(root, baseline.model_copy(update={'findings': kept}))
    return removed


def apply(report, root):
    """Mark findings covered by the baseline. Matching is by fingerprint count, so a third copy
    of a twice-baselined violation is still new."""
    baseline = load(root)
    if baseline is None:
        return report
    remaining = {fp: entry.count for fp, entry in baseline.findings.items()}
    accepted = 0
    for finding in report['findings']:
        covered = remaining.get(finding['fingerprint'], 0) > 0
        finding['baselined'] = covered
        if covered:
            remaining[finding['fingerprint']] -= 1
            accepted += 1
    stale = sum(remaining.values())
    report['baseline'] = dict(file=FILENAME, accepted=accepted, stale=stale)
    notes = []
    if accepted:
        notes.append(f'{accepted} existing finding(s) accepted by the baseline ({FILENAME}); reported, but not blocking.')
    if stale:
        notes.append(f'{stale} baseline entr{"y" if stale == 1 else "ies"} no longer occur: run agentaccord baseline --prune to shrink it.')
    report['limitations'] = [*report['limitations'], *notes]
    return report
