# AgentContract

**Define engineering rules once. Keep agent guidance and source code aligned.**

AgentContract is a local developer tool with a browser workspace and an automation-friendly CLI. Version 0.3 focuses on an end-to-end Spring Boot workflow: approve policies, generate consistent guidance, check Java and instruction files, and review actionable findings.

## Start the app

Python 3.12+ is required. From this repository:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/agentcontract serve examples/spring-demo
```

Open the complete URL printed by the command. It contains a temporary local session token. Keep the terminal running; Ctrl+C stops the app. The service listens only on `127.0.0.1` and is bound to the repository selected at startup. Use `--port 0` to choose a free port.

After installation, the convenience launcher does the same thing:

```sh
./run.sh examples/spring-demo
```

The app provides four screens: repository overview, explicit policy approval, managed guidance preview/update, and findings with search, filters, coverage details, and JSON/SARIF/HTML downloads. It does not upload repositories or need an AI API key. Installing dependencies initially requires access to a Python package registry.

## Try your own repository

```sh
.venv/bin/agentcontract init /path/to/project
.venv/bin/agentcontract serve /path/to/project
```

`init` creates proposed rules, with `approved: false`. Review them in Policies, select the conventions your team wants, and save. No rules become blocking merely because they are available. The starter catalog is not inferred from your code.

Then preview guidance, update its managed section if appropriate, and run checks. Handwritten instructions are preserved—even if they conflict; findings identify those lines for human correction.

## Command line

```sh
.venv/bin/agentcontract scan examples/spring-demo
.venv/bin/agentcontract check examples/spring-demo
.venv/bin/agentcontract check examples/spring-demo --format json
.venv/bin/agentcontract check examples/spring-demo --format html --output review.html
.venv/bin/agentcontract check examples/spring-demo --format sarif --output results.sarif
.venv/bin/agentcontract guidance examples/spring-demo
.venv/bin/agentcontract guidance /path/to/project --write
.venv/bin/agentcontract rules
.venv/bin/agentcontract doctor examples/spring-demo
```

The Spring demo intentionally produces **4 errors and 1 warning**, including two instruction conflicts. It consists of analysis fixtures, not a runnable Spring application. `examples/passing` remains a clean legacy-policy fixture.

`--output` never overwrites an existing report. The export preserves the check exit code, even if a report was saved successfully:

| Exit | Meaning |
| --- | --- |
| 0 | No blocking violations among configured, supported checks |
| 1 | Approved policy violations |
| 2 | Tool/configuration failure, incomplete analysis, or no approved rules |

## Approved policy format

```yaml
version: 1
rules:
  spring.no-field-injection:
    enabled: true
    approved: true
    severity: error
  spring.no-webmvctest:
    enabled: true
    approved: true
    severity: error
  spring.no-value:
    enabled: true
    approved: false
    severity: warning
```

The last rule is proposed and does not run. Unknown rule IDs/options, invalid severities, duplicate YAML keys, aliases, and unsupported versions are rejected. Existing `.agentcontract.toml` v0.1/v0.2 policies remain readable and are treated as previously approved. Saving through the app writes `.agentcontract.yml`, which takes precedence; the old file is retained.

Policies represent team choices. Neither `@WebMvcTest` nor `@Value` is universally wrong.

## Supported analysis

| Rule | What is checked |
| --- | --- |
| `spring.no-field-injection` | Field-level Spring `@Autowired`, Jakarta/Javax `@Inject` and `@Resource`; constructor and setter annotations are not flagged |
| `spring.no-webmvctest` | Supported Spring Boot `@WebMvcTest` annotations |
| `spring.no-value` | Spring `@Value` annotations |
| `python.no-mutable-defaults` | List/dict/set literal defaults, using Python AST |
| `python.require-type-hints` | Missing function argument/return annotations, exempting self/cls |

Java uses Tree-sitter and explicit imports/fully qualified annotation names. Unrelated explicitly imported annotations are not flagged. Unresolvable relevant names and syntax errors produce incomplete-analysis diagnostics instead of a false clean result. Custom meta-annotations, cross-file resolution, and wildcard import resolution are not supported.

Instruction checks recognize direct affirmative `Use`, `Prefer`, and `Always use` patterns for `@WebMvcTest`, `@Value`, and field injection. Fenced examples, indented code, block quotes, HTML comments, negative lines, and selected conditional patterns are excluded. This is deterministic pattern matching, not general natural-language understanding. Policies apply repository-wide; instruction precedence and scope semantics are not interpreted.

Recognized instruction files: AGENTS.md, CLAUDE.md, SKILL.md, copilot-instructions.md, and *.instructions.md. Discovery counts source extensions and manifest filenames; it does not infer framework versions or approve conventions.

## Guidance preservation

`guidance --write` and the app update only the block between:

```text
<!-- agentcontract:begin -->
<!-- agentcontract:end -->
```

Text outside the block is preserved. If no block exists it is appended. Malformed/duplicate markers and symlink targets are rejected. The operation is idempotent and uses atomic replacement.

## Privacy and limits

Scanning never executes project scripts or imports scanned Python modules. Symlinks are not followed. Relevant files exceeding 1 MB, unreadable encodings, and parse errors are reported. Scanning stops after 10,000 file entries; build/vendor directories are excluded. Reports can include paths and short evidence, so review them before sharing.

The local app uses a per-session token, strict Host/Origin checks, a content security policy, and loopback binding. It is a local development app, not a hosted multi-user service or a sandbox against hostile concurrent filesystem changes. Stop it when finished.

## Development and verification

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover analyzers, false positives, YAML validation, legacy migration, guidance preservation, report escaping, SARIF structure, and real local HTTP API flows. HTTP tests require loopback socket access. Browser QA covers the overview, policy save, generated guidance, running checks, and finding filters.

See `docs/ROADMAP.md` for scope and outstanding work. This release does not complete the original universal-platform specification: TypeScript/C#, general convention inference, PR diff/baseline analysis, full plugin contracts, and production hardening remain future work.
