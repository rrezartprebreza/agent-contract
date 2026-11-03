"""Command line entry point; the local app uses the same engine and policies."""
import argparse
import json
import sys
from pathlib import Path
import yaml
from . import baseline, configuration, instructions
from . import __version__
from .rules import RULES
from .engine import analyze, scan, exit_code, EXCLUDED
from .reporters import dashboard, sarif

# Retained for legacy configuration regression fixtures.
CONFIG = 'version = 1\n[rules]\n"spring.no-webmvctest" = "error"\n"spring.no-value" = "warning"\n'


def load_policy(root):
    return configuration.load(root).active()


def main(argv=None):
    parser = argparse.ArgumentParser(description='AgentAccord — approved policies, consistent guidance, verified code')
    parser.add_argument('--version', action='version', version=f'AgentAccord {__version__}')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('init', 'check', 'baseline', 'guidance', 'scan', 'doctor', 'rules', 'serve', 'quick'):
        cmd = sub.add_parser(command)
        if command != 'quick':
            cmd.add_argument('path', nargs='?', default='.')
        if command == 'check':
            cmd.add_argument('--format', choices=['console', 'json', 'html', 'sarif', 'markdown', 'github'], default='console')
            cmd.add_argument('--output', type=Path, help='Create a new report file')
            cmd.add_argument('--compare-to', type=Path, help='Base checkout; compare both snapshots using its approved policy')
            cmd.add_argument('--no-baseline', action='store_true', help='Report every finding, ignoring the baseline')
        if command == 'baseline':
            cmd.add_argument('--prune', action='store_true', help='Remove fixed entries; never adds new ones')
        if command == 'guidance':
            cmd.add_argument('--write', action='store_true', help='Update only the managed section of AGENTS.md')
        if command in ('serve', 'quick'):
            cmd.add_argument('--port', type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        if args.command == 'quick':
            from tempfile import TemporaryDirectory
            from .server import serve
            with TemporaryDirectory(prefix='agentaccord-workspace-') as directory:
                serve(Path(directory), args.port, quick=True)
            return 0
        root = Path(args.path).resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Repository path must be a directory')
        if args.command == 'init':
            if any((root / name).exists() or (root / name).is_symlink() for name in configuration.POLICY_FILES):
                raise ValueError('A policy already exists; refusing overwrite')
            policy = configuration.Policy(rules={key: configuration.RulePolicy() for key in RULES})
            configuration.save(root, policy)
            print('Created .agentaccord.yml with proposed rules. Approve rules in agentaccord serve or set approved: true explicitly.')
            return 0
        if args.command == 'serve':
            from .server import serve
            serve(root, args.port)
            return 0
        if args.command == 'rules':
            catalog = configuration.load(root, optional=True).catalog()
            for key, rule in catalog.items():
                print(f'{key}: {rule["guidance"]}' + (' (custom)' if rule.get('custom') else ''))
            return 0
        if args.command == 'scan':
            from .discovery import discover
            print(json.dumps(discover(root), indent=2))
            return 0
        base_root = args.compare_to if args.command == 'check' else None
        policy = configuration.load(base_root.resolve(strict=True) if base_root else root)
        rules = policy.active()
        catalog = policy.catalog()
        if args.command == 'doctor':
            print(f'AgentAccord {__version__} | Python {sys.version.split()[0]}\nPolicy valid: {len(rules)} approved rule(s)\nJava: Tree-sitter | Python: AST | Instructions: explicit patterns')
            return 0
        if args.command == 'guidance':
            if not rules:
                raise ValueError('Approve at least one rule before generating guidance')
            if args.write:
                changed = instructions.sync(root, rules, catalog)
                print('Updated managed section in AGENTS.md' if changed else 'Guidance already up to date')
            else:
                print(instructions.guidance(rules, catalog))
            return 0
        if base_root:
            from .comparison import compare
            report, policy = compare(root, base_root)
        else:
            report = scan(root, rules, policy.exclude, catalog, policy.examples)
        if args.command == 'baseline':
            if args.prune:
                removed = baseline.prune(root, report)
                print(f'Removed {removed} fixed finding(s) from {baseline.FILENAME}' if removed else 'Baseline already minimal')
            else:
                accepted = baseline.create(root, report)
                print(f'Created {baseline.FILENAME} accepting {accepted} existing finding(s). New findings will still fail checks.')
            if report['skipped']:
                print(f'Note: {len(report["skipped"])} file(s) could not be analyzed; checks stay incomplete until they are fixed or excluded.')
            return 0
        if not base_root and not args.no_baseline:
            baseline.apply(report, root)
        if not rules:
            report['limitations'] = [*report['limitations'], 'No approved rules: this is not a compliance pass.']
        if args.format == 'json':
            rendered = json.dumps(report, indent=2)
        elif args.format == 'sarif':
            rendered = json.dumps(sarif(report), indent=2)
        elif args.format in ('markdown', 'github'):
            from .pr_reports import summary, annotations
            rendered = summary(report) if args.format == 'markdown' else annotations(report)
        elif args.format == 'html':
            rendered = dashboard(report)
        else:
            lines = [f"{f['severity'].upper()} {f['path']}:{f['line']}:{f['column']} [{f['rule']}; {f['kind']}] {f['message']}"
                     for f in report['findings'] if not f.get('baselined') and f.get('change') != 'existing']
            lines += [f"SKIPPED {s['path']}: {s['reason']}" for s in report['skipped']]
            excluded = f" · {report['excluded_files']} excluded by policy" if report['excluded_files'] else ''
            known = report.get('baseline') or {}
            new = sum(not f.get('baselined') and f.get('change') != 'existing' for f in report['findings'])
            accepted = f" · {known['accepted']} accepted by baseline" if known.get('accepted') else ''
            lines.append(f"{new} finding(s){accepted} · {report['analyzed_files']} files analyzed{excluded} · {len(rules)} approved rules")
            if policy.examples.java:
                lines.append(f"{report['example_files']} Java example files analyzed as warnings · "
                             f"{len(report['counter_example_files'])} configured counter-example files omitted")
            if report['rule_scope_omissions']:
                lines.append(f"{len(report['rule_scope_omissions'])} files have rules omitted by per-rule path scopes")
            if report.get('comparison'):
                c = report['comparison']
                lines.append(f"Comparison: {c['new']} new · {c['existing']} existing · {c['resolved']} absent prior occurrences (base policy)")
                lines += [f"BASE SKIPPED {s['path']}: {s['reason']}" for s in c['base_skipped']]
            if known.get('stale'):
                lines.append(f"{known['stale']} baseline entries were fixed: run agentaccord baseline --prune")
            if not rules:
                lines.append('No approved rules. Approve policies before checking compliance.')
            rendered = '\n'.join(lines)
        if args.output:
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(rendered + '\n')
            print(f'Report written: {args.output}')
        else:
            print(rendered)
        return exit_code(report)
    except (OSError, ValueError, yaml.YAMLError, RecursionError) as error:
        print(f'agentaccord: {error}', file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 — an uncaught crash would exit 1, which means "violations"
        print(f'agentaccord: internal error ({type(error).__name__}: {error}). Please report it.', file=sys.stderr)
        return 2
