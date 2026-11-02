"""Portable, self-contained reports. Repository content is always escaped."""
import html
import json
from pathlib import PurePosixPath
from urllib.parse import quote


def sarif(report):
    ids = sorted({f['rule'] for f in report['findings']})
    return {'version': '2.1.0', '$schema': 'https://json.schemastore.org/sarif-2.1.0.json', 'runs': [{
        'columnKind': 'unicodeCodePoints',
        'tool': {'driver': {'name': 'AgentAccord', 'version': '0.3.0',
            'rules': [{'id': rule, 'shortDescription': {'text': rule}} for rule in ids]}},
        'results': [{'ruleId': f['rule'], 'level': 'error' if f['severity'] == 'error' else 'warning',
            'message': {'text': f['message'] + ' ' + f['remediation']},
            'locations': [{'physicalLocation': {'artifactLocation': {
                'uri': quote(PurePosixPath(f['path']).as_posix(), safe='/'), 'uriBaseId': '%SRCROOT%'},
                'region': {'startLine': f['line'], 'startColumn': f['column']}}}],
            **({'partialFingerprints': {'agentaccord/v1': f['fingerprint']}} if f.get('fingerprint') else {}),
            **({'baselineState': 'unchanged' if f.get('baselined') else 'new'} if report.get('baseline') else {}),
            'properties': {'confidence': f['confidence'], 'kind': f['kind']}}
            for f in report['findings']],
        'invocations': [{'executionSuccessful': not bool(report['skipped']) and report.get('approved_rules', 1) > 0,
            'toolExecutionNotifications': [{'level': 'warning', 'message': {'text': s['path'] + ': ' + s['reason']}} for s in report['skipped']]}]
    }]}


def dashboard(report):
    esc = lambda value: html.escape(str(value), quote=True)
    findings = [f for f in report['findings'] if not f.get('baselined')]
    errors = sum(f['severity'] == 'error' for f in findings)
    conflicts = sum(f['kind'] == 'instruction' for f in findings)
    cards = []
    for f in findings:
        cards.append(f'''<article data-severity="{esc(f['severity'])}" data-kind="{esc(f['kind'])}">
<div class="row"><span class="badge {esc(f['severity'])}">{esc(f['severity'])}</span><span class="muted">{esc(f['kind'])} · {esc(f['confidence'])}</span></div>
<h3>{esc(f['message'])}</h3><p class="location">{esc(f['path'])}:{f['line']}:{f['column']}</p>
<code>{esc(f['rule'])}</code><p class="fix">{esc(f['remediation'])}</p></article>''')
    notices = ''.join(f"<li>{esc(s['path'])}: {esc(s['reason'])}</li>" for s in report['skipped'])
    limits = ''.join(f'<li>{esc(item)}</li>' for item in report['limitations'])
    status = 'No approved rules' if report.get('approved_rules') == 0 else 'Incomplete analysis' if report['skipped'] else 'Changes required' if errors else 'No blocking findings'
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AgentAccord · Policy review</title><style>
:root{color-scheme:dark;--bg:#10151d;--panel:#19212c;--muted:#a4b2c4;--accent:#a8efca}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#edf2f8;font:16px/1.6 system-ui,sans-serif}main{max-width:1120px;margin:auto;padding:42px 24px}header{display:flex;justify-content:space-between;gap:20px;align-items:center;border-bottom:1px solid #334052;padding-bottom:22px}.brand{font-size:20px;font-weight:750;letter-spacing:-.5px}.brand b{color:var(--accent)}.muted,small{color:var(--muted)}.eyebrow{letter-spacing:2px;text-transform:uppercase;font-size:12px;color:var(--accent);margin-top:42px}h1{font-size:clamp(30px,5vw,52px);letter-spacing:-2px;line-height:1.15;margin:12px 0}h2{font-size:22px}h3{font-size:18px;margin:18px 0 6px}.intro{max-width:680px;color:var(--muted)}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:32px 0}.stat,article{background:var(--panel);border:1px solid #303c4d;border-radius:14px;padding:22px}.stat strong{display:block;font-size:34px}.stat span{color:var(--muted);font-size:13px}.toolbar,.row{display:flex;justify-content:space-between;align-items:center;gap:12px}.toolbar{flex-wrap:wrap;margin:30px 0 18px}input,select{border:1px solid #45546a;background:#19212c;color:#edf2f8;border-radius:8px;padding:11px;font:inherit}input{flex:1;min-width:200px}label{font-size:13px;color:var(--muted)}#findings{display:grid;grid-template-columns:1fr 1fr;gap:16px}article[hidden]{display:none}.badge{font-size:11px;text-transform:uppercase;font-weight:750;letter-spacing:1px;border-radius:5px;padding:3px 8px}.error{background:#492a34;color:#ffb1bc}.warning{background:#433b24;color:#f6d894}.location,code{font:13px/1.7 ui-monospace,monospace;overflow-wrap:anywhere}.location{color:var(--accent)}code{color:var(--muted)}.fix{font-size:14px;border-top:1px solid #334052;padding-top:14px;margin-bottom:0}details{margin:28px 0;border-top:1px solid #334052;padding-top:18px;color:var(--muted)}summary{cursor:pointer;color:#edf2f8}footer{margin-top:40px;color:var(--muted);font-size:12px}@media(max-width:650px){.stats{grid-template-columns:1fr 1fr}#findings{grid-template-columns:1fr}header{align-items:flex-start}.row{flex-wrap:wrap}}
</style><main><header><div class="brand"><b>◈</b> AgentAccord</div><small>LOCAL POLICY REVIEW · v0.3</small></header>
<p class="eyebrow">Engineering rules, connected</p>''' + f'''<h1>{status}</h1><p class="intro">Approved policy → agent guidance → source verification. Review supported violations and instruction conflicts in one place.</p>
<div class="stats"><div class="stat"><strong>{errors}</strong><span>Blocking findings</span></div><div class="stat"><strong>{len(findings)-errors}</strong><span>Warnings</span></div><div class="stat"><strong>{conflicts}</strong><span>Instruction conflicts</span></div><div class="stat"><strong>{len(report['skipped'])}</strong><span>Skipped files</span></div></div>
<h2>Review findings</h2><div class="toolbar"><label for="search">Search</label><input id="search" placeholder="File, rule, or recommendation…"><label for="severity">Severity</label><select id="severity"><option value="all">All severities</option><option value="error">Errors</option><option value="warning">Warnings</option></select><label for="kind">Source</label><select id="kind"><option value="all">All sources</option><option value="instruction">Instructions</option><option value="code">Code</option></select></div>
<p id="count" class="muted" aria-live="polite"></p><section id="findings">{''.join(cards)}</section>
<details><summary>Coverage and limitations</summary><ul>{limits}</ul></details>
<details {'open' if notices else ''}><summary>Skipped files ({len(report['skipped'])})</summary><ul>{notices}</ul></details>
<footer>Generated locally. No external scripts, fonts, analytics, or repository uploads. A clean result covers only the configured checks.</footer></main>''' + '''<script>
const search=document.getElementById('search'),severity=document.getElementById('severity'),kind=document.getElementById('kind');
function filter(){let count=0;document.querySelectorAll('article').forEach(card=>{const show=card.textContent.toLowerCase().includes(search.value.toLowerCase())&&(severity.value==='all'||card.dataset.severity===severity.value)&&(kind.value==='all'||card.dataset.kind===kind.value);card.hidden=!show;if(show)count++});document.getElementById('count').textContent=count+' finding(s) shown';} [search,severity,kind].forEach(el=>el.addEventListener('input',filter));filter();
</script></html>'''
