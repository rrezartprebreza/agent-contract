"""Bounded GitHub annotations and Markdown summaries; source cannot inject workflow commands."""
import html
import re
from pathlib import PurePosixPath


def actionable(finding):
    return finding.get('change') != 'existing' and not finding.get('baselined')


def escape_command(value, property=False):
    value = str(value).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    return value.replace(':', '%3A').replace(',', '%2C') if property else value


def annotations(report, prefix='', limit=50):
    lines = []
    for finding in [f for f in report['findings'] if actionable(f)][:limit]:
        path = str(PurePosixPath(prefix) / finding['path']) if prefix else finding['path']
        title = finding['kind'] + ' policy conflict: ' + finding['rule']
        properties = f"file={escape_command(path, True)},line={finding['line']},col={finding['column']},title={escape_command(title, True)}"
        message = finding['message'] + ' Suggested fix: ' + finding['remediation']
        level = 'error' if finding['severity'] == 'error' else 'warning'
        lines.append(f'::{level} {properties}::{escape_command(message)}')
    return '\n'.join(lines)


def safe_text(value, limit=600):
    # Escape HTML and Markdown syntax, collapse line breaks, prevent mention autolinks.
    text = html.escape(' '.join(str(value).split()), quote=True)[:limit]
    text = re.sub(r'([\\`*_{}\[\]()#+.!|>~-])', r'\\\1', text)
    return text.replace('@', '&#64;')


def summary(report, limit=50):
    new = [f for f in report['findings'] if actionable(f)]
    existing = [f for f in report['findings'] if not actionable(f)]
    comparison = report.get('comparison', {})
    incomplete = bool(report['skipped'] or comparison.get('base_skipped') or not report.get('approved_rules'))
    status = 'Incomplete analysis' if incomplete else 'New policy conflicts' if new else 'No new policy conflicts'
    lines = ['## AgentAccord: ' + status, '',
             f"{len(new)} new/unaccepted findings · {len(existing)} existing/accepted findings · {report['analyzed_files']} analyzed files", '']
    if comparison:
        lines += ['Both snapshots use the base checkout policy. Baseline files are ignored.',
                  f"{comparison['resolved']} prior finding occurrences are absent under the same policy.", '']
    lines += ['These are team-policy matches, not automatically bugs. Warnings do not block.', '']
    shown = 0
    for kind, title in [('code', 'New code conflicts'), ('instruction', 'New instruction conflicts'), ('example', 'New example warnings')]:
        group = [f for f in new if f['kind'] == kind]
        lines += ['### ' + title + f' ({len(group)})', '']
        for finding in group[:max(0, limit-shown)]:
            lines += [f"- **{safe_text(finding['severity'])}** {safe_text(finding['path'])}:{finding['line']}:{finding['column']} — {safe_text(finding['rule'])}",
                      f"  {safe_text(finding['message'])} Suggested fix: {safe_text(finding['remediation'])}"]
            shown += 1
        if not group:
            lines.append('None.')
        lines.append('')
    if len(new) > shown:
        lines += [f'{len(new)-shown} additional new findings are in the JSON report.', '']
    lines += ['<details><summary>Existing findings (not blocking)</summary>', '']
    for finding in existing[:limit]:
        lines.append(f"- {safe_text(finding['path'])}:{finding['line']} — {safe_text(finding['rule'])} ({safe_text(finding['kind'])})")
    if not existing:
        lines.append('None.')
    if len(existing) > limit:
        lines.append(f'{len(existing)-limit} additional existing findings are in the JSON report.')
    lines += ['', '</details>', '', '### Coverage', '']
    for side, skipped in [('Current', report['skipped']), ('Base', comparison.get('base_skipped', []))]:
        for item in skipped[:limit]:
            lines.append(f"- {side}: {safe_text(item['path'])}: {safe_text(item['reason'])}")
        if len(skipped) > limit:
            lines.append(f'- {side}: {len(skipped)-limit} more skipped files in JSON.')
    if not report.get('approved_rules'):
        lines.append('- No active approved rules: this is not a passing policy check.')
    lines += ['- ' + safe_text(note, 1000) for note in report['limitations']]
    return '\n'.join(lines) + '\n'
