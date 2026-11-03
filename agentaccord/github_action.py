"""Single-scan GitHub Action entry point. Run with python -I to exclude checkout imports."""
import json
import os
from pathlib import Path
import tempfile
from . import baseline, configuration
from .comparison import compare
from .engine import exit_code, scan
from .pr_reports import annotations, escape_command, safe_text, summary
from .reporters import sarif


def main():
    code = 2
    outputs = {}
    try:
        root = Path(os.environ.get('TARGET', '.')).resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Target must be a repository directory')
        base = os.environ.get('BASE_TARGET', '')
        if base:
            report, _ = compare(root, Path(base))
        else:
            policy = configuration.load(root)
            report = baseline.apply(scan(root, policy.active(), policy.exclude, policy.catalog(), policy.examples, java_version=policy.java.version), root)
        workspace = Path(os.environ.get('GITHUB_WORKSPACE', str(root))).resolve()
        if not root.is_relative_to(workspace):
            raise ValueError('Target must be inside GITHUB_WORKSPACE for file annotations')
        prefix = root.relative_to(workspace).as_posix()
        directory = Path(tempfile.mkdtemp(prefix='agentaccord-', dir=os.environ.get('RUNNER_TEMP')))
        report_path = directory / 'report.json'
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        sarif_path = directory / 'report.sarif'
        sarif_path.write_text(json.dumps(sarif(report), indent=2) + '\n', encoding='utf-8')
        # SARIF paths, like workflow annotations, are workspace-relative for nested checkouts.
        sarif_data = json.loads(sarif_path.read_text(encoding='utf-8'))
        if prefix != '.':
            from urllib.parse import quote
            for finding in sarif_data['runs'][0]['results']:
                location = finding['locations'][0]['physicalLocation']['artifactLocation']
                location['uri'] = quote(prefix, safe='/') + '/' + location['uri']
            sarif_path.write_text(json.dumps(sarif_data, indent=2) + '\n', encoding='utf-8')
        outputs.update({'report-path': str(report_path), 'sarif-path': str(sarif_path)})
        print(annotations(report, '' if prefix == '.' else prefix))
        rendered = summary(report)
        code = exit_code(report)
        if code == 2:
            print('::error::AgentAccord analysis is incomplete. See the job summary and JSON report.')
    except Exception as error:
        message = 'AgentAccord could not complete the check: ' + str(error)
        print('::error::' + escape_command(message))
        rendered = '## AgentAccord: incomplete analysis\n\n' + safe_text(message) + '\n'
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write(rendered)
    outputs['exit-code'] = str(code)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            for key, value in outputs.items():
                # File paths are generated under runner-owned temporary storage.
                if '\n' in value or '\r' in value:
                    raise ValueError('Invalid multiline action output')
                stream.write(key + '=' + value + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
