# Pull-request feedback

This unreleased feature compares separate base and current checkouts:

```sh
agentaccord check /path/to/current --compare-to /path/to/base
agentaccord check /path/to/current --compare-to /path/to/base --format markdown
agentaccord check /path/to/current --compare-to /path/to/base --format json
```

Both scans use the **base checkout's approved policy**, including scopes, custom
rules, and example settings. A PR's edits to its policy or baseline cannot suppress
new findings. Baseline files are ignored in comparison mode. To adopt new rules,
review and merge the policy changes first; the comparison does not evaluate proposed
policy changes as though they were already approved.

- Exit 0: no new error findings under the base policy.
- Exit 1: new error findings. New warnings remain non-blocking.
- Exit 2: either snapshot is incomplete, the base policy is unavailable/invalid,
  or no rules are approved.

Full JSON retains every current finding with `change: new` or `change: existing`.
The comparison section records new, existing, and absent prior occurrence counts,
plus skipped base files. Existing matches remain visible in a collapsed job-summary
section and HTML report. SARIF marks them unchanged.

## GitHub Actions

Use two sibling checkouts. The example below uses the development branch containing
this feature; pin a reviewed commit SHA for regular use. Published v0.4.1 does not
contain these new inputs.

```yaml
name: AgentAccord PR review
on: pull_request
permissions:
  contents: read
jobs:
  policies:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          ref: ${{ github.event.pull_request.base.sha }}
          path: base
          persist-credentials: false
      - uses: actions/checkout@v7
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          path: current
          persist-credentials: false
      - uses: rrezartprebreza/agentaccord@codex/pull-request-feedback
        id: accord
        with:
          path: current
          base-path: base
          sarif: "false"
      - uses: actions/upload-artifact@v4
        if: always() && steps.accord.outputs.report-path != ''
        with:
          name: agentaccord-findings
          path: ${{ steps.accord.outputs.report-path }}
```

Use `pull_request`, not `pull_request_target` with untrusted checkout code.
The scanner does not build, import, or execute the target project. The action invokes
its installed package in Python isolated mode so a checkout cannot shadow it.
No PR comment or bot token is required for annotations and the job summary.
Optional SARIF upload retains its existing permissions requirements.

The action scans once per snapshot, emits up to 50 new/unaccepted file annotations,
and groups the job summary into code, instruction, and example conflicts. Each new
finding includes its current path, line, column, and suggested fix. GitHub controls
where annotations appear; this does not post inline review comments.

The summary shows up to 50 new and 50 existing findings. The JSON artifact retains
all findings and their bounded source excerpts. Existing conflicts do not disappear
from the report just because they no longer block the check.

Without `base-path`, the action keeps the ordinary repository check and baseline
behavior, while still producing annotations, a summary, and a JSON output path.

## Matching limits

Matching uses the rule ID, repository-relative path, whitespace-normalized finding
line, and occurrence counts. Moving a line within a file preserves its identity.
An extra duplicate occurrence remains new; identical occurrences cannot always be
attributed to the exact inserted copy. Renamed files and edited finding lines count
as new. This is finding comparison, not semantic Git diff analysis or proof of recall.

A finding's reported location is its current source location. A clean comparison
does not mean the whole repository has no existing policy conflicts. Resolve skipped
files in either checkout before treating the comparison as complete.
