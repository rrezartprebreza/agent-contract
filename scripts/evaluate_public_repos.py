"""Reproduce the public repository trial using existing, pinned, clean checkouts.

Reads source with AgentAccord; never installs, imports, builds, or runs target projects.
Policies are hypothetical evaluator choices, not upstream maintainer approvals.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from agentaccord import __version__
from agentaccord.configuration import Policy, RulePolicy
from agentaccord.engine import exit_code, scan
from agentaccord.reporters import dashboard

REPOSITORIES = {
    'spring-petclinic': ('https://github.com/spring-projects/spring-petclinic', '500158f732419217507c7656904b8e6aa1bcc0d6'),
    'gs-batch-processing': ('https://github.com/spring-guides/gs-batch-processing', '8432843d2be2c50a473541887d5f96f27581d667'),
    'flask': ('https://github.com/pallets/flask', '49943b5a94413a530761350f04e896f76e8d620e'),
}
SPRING = {'spring.no-field-injection': {}, 'spring.no-value': {}, 'spring.no-webmvctest': {}}
PROFILES = [
    ('spring-petclinic', 'spring-strict', SPRING),
    ('gs-batch-processing', 'spring-strict', SPRING),
    ('flask', 'python-global', {'python.no-mutable-defaults': {}, 'python.require-type-hints': {}}),
    ('flask', 'python-source', {'python.no-mutable-defaults': {}, 'python.require-type-hints': {'include': ['src/**']}}),
]


def git(root, *args):
    return subprocess.check_output(
        ['git', '-c', 'core.fsmonitor=false', '-C', str(root), *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkouts', type=Path, help='Directory containing the three named checkouts')
    parser.add_argument('output', type=Path, help='New output directory (must not already exist)')
    args = parser.parse_args()
    checkouts = args.checkouts.resolve()
    output = args.output.resolve()
    for name, (_, revision) in REPOSITORIES.items():
        root = checkouts / name
        if output.is_relative_to(root):
            parser.error('Output must be outside the repositories under evaluation')
        if git(root, 'rev-parse', 'HEAD') != revision:
            parser.error(f'{name}: expected pinned revision {revision}')
        if git(root, 'status', '--porcelain'):
            parser.error(f'{name}: checkout must be clean, including untracked files')
    output.mkdir(parents=True, exist_ok=False)
    summaries = []
    for name, profile, settings in PROFILES:
        policy = Policy(rules={rule: RulePolicy(approved=True, **options) for rule, options in settings.items()})
        report = scan(checkouts / name, policy.active(), policy.exclude, policy.catalog(), policy.examples)
        key = name + '-' + profile
        (output / (key + '.json')).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        (output / (key + '-policy.json')).write_text(json.dumps(policy.model_dump(), indent=2) + '\n', encoding='utf-8')
        (output / (key + '.html')).write_text(dashboard(report), encoding='utf-8')
        url, revision = REPOSITORIES[name]
        item = dict(repository=name, url=url, revision=revision, profile=profile,
                    analyzed_files=report['analyzed_files'], findings=len(report['findings']),
                    by_rule=dict(Counter(f['rule'] for f in report['findings'])),
                    skipped=report['skipped'], exit_code=exit_code(report))
        summaries.append(item)
        print(f"{key}: {item['analyzed_files']} analyzed, {item['findings']} findings, "
              f"{len(item['skipped'])} skipped, check exit {item['exit_code']}")
    hashes = {p.relative_to(PROJECT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((PROJECT / 'agentaccord').rglob('*.py'))}
    (output / 'summary.json').write_text(json.dumps(
        dict(version=__version__, source_hashes=hashes, runs=summaries), indent=2) + '\n', encoding='utf-8')
    # A policy finding is trial data, not a failure to run the evaluator.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
