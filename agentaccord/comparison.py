"""Compare source snapshots under the base checkout's approved policy; never execute Git."""
from collections import Counter
from . import configuration
from .engine import scan


def compare(root, base_root):
    root, base_root = root.resolve(strict=True), base_root.resolve(strict=True)
    if not root.is_dir() or not base_root.is_dir():
        raise ValueError('Comparison paths must be directories')
    if root == base_root or root.is_relative_to(base_root) or base_root.is_relative_to(root):
        raise ValueError('Compare two separate, non-overlapping repository checkouts')
    policy = configuration.load(base_root)
    rules, catalog = policy.active(), policy.catalog()
    previous = scan(base_root, rules, policy.exclude, catalog, policy.examples, java_version=policy.java.version)
    current = scan(root, rules, policy.exclude, catalog, policy.examples, java_version=policy.java.version)
    remaining = Counter(f['fingerprint'] for f in previous['findings'])
    existing = 0
    for finding in current['findings']:
        if remaining[finding['fingerprint']]:
            finding['change'] = 'existing'
            remaining[finding['fingerprint']] -= 1
            existing += 1
        else:
            finding['change'] = 'new'
    current['comparison'] = dict(new=len(current['findings'])-existing, existing=existing,
        resolved=sum(remaining.values()), base_skipped=previous['skipped'], policy_source='base checkout')
    current['limitations'].append(
        'Comparison uses the base checkout policy for both snapshots and ignores baseline files. '
        'Only new findings block. Matching uses rule, path, normalized source line, and occurrence count; '
        'renames and edited finding lines count as new, and identical copies may be attributed to a different occurrence.')
    if previous['skipped']:
        current['limitations'].append('Base analysis is incomplete; new/existing classification may be uncertain.')
    return current, policy
