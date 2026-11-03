# AgentAccord

**Team engineering rules for AI coding agents — checked in your skills, `AGENTS.md`, `CLAUDE.md`, and code.**

[![CI](https://github.com/rrezartprebreza/agentaccord/actions/workflows/ci.yml/badge.svg)](https://github.com/rrezartprebreza/agentaccord/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![Local only](https://img.shields.io/badge/runs-100%25%20local-success.svg)

Coding agents follow `AGENTS.md`, `CLAUDE.md`, and `SKILL.md` files, not your wiki. When those files drift from the rules your team agreed on, agents faithfully produce the code you were trying to prevent. AgentAccord keeps three things in agreement:

```mermaid
flowchart LR
    P["Approved policy<br/>.agentaccord.yml"] -->|generates| G["Agent guidance<br/>managed block in AGENTS.md"]
    P -->|verifies| C["Source code<br/>Java · Python"]
    P -->|verifies| I["Instruction files<br/>sentences + code examples"]
```

It is free, MIT-licensed, and fully local: no account, no AI API key, no uploads.

> **Formerly AgentContract.** The project was renamed because another AI-agent project already publishes `agentcontract` on PyPI. Existing repositories keep working: `.agentcontract.yml`, `.agentcontract.toml`, `.agentcontract-baseline.json`, and `agentcontract:begin/end` markers are still read, and the next `guidance --write` migrates the markers. New files use the `agentaccord` names.

## What it catches

| Your team decided… | …but an instruction file says | …or the code does |
| --- | --- | --- |
| Constructor injection only | `Prefer field injection for services.` | `@Autowired private Store store;` |
| No `@WebMvcTest` slices | a code example annotated `@WebMvcTest` | `@WebMvcTest class OrderControllerTest` |
| Typed configuration | ```` ```java ```` example using `@Value("${url}")` | `@Value("${payments.url}") String url;` |
| *Your own rule*, e.g. no Lombok `@Data` | `Use @Data for DTOs.` | `@Data public class Money` |

## Evidence and first use

The [public repository trial](docs/public-repository-trial.md) checked pinned
Spring Petclinic, Spring Batch guide, and Flask revisions. It records coverage,
manual review, and limitations without presenting hypothetical policy matches as
upstream bugs. The results are reproducible with the included evaluator.

Use the [pilot guide](docs/pilot-guide.md) to try one agreed team rule, check both
instruction and code conflicts, and record whether the findings are useful.

## Install

```sh
pipx install agentaccord        # or: python3 -m pip install agentaccord
```

Python 3.12 or newer. Linux and macOS are tested in CI.

## See it in 60 seconds

The repository ships a demo with every kind of finding:

```sh
git clone https://github.com/rrezartprebreza/agentaccord.git && cd agentaccord
python3 -m venv .venv && .venv/bin/python -m pip install .
.venv/bin/agentaccord check examples/spring-demo
```

```text
ERROR AGENTS.md:3:1 [spring.no-webmvctest; instruction] Instruction contradicts an approved policy: Approved integration testing
ERROR AGENTS.md:4:1 [spring.no-field-injection; instruction] Instruction contradicts an approved policy: Constructor injection
WARNING AGENTS.md:18:5 [spring.no-value; instruction] Code example teaches a pattern the approved policy prohibits: Typed configuration
WARNING src/Money.java:5:1 [custom.no-lombok-data; code] @Data is prohibited by approved policy
ERROR src/OrderControllerTest.java:5:1 [spring.no-webmvctest; code] @WebMvcTest is prohibited by approved policy
ERROR src/OrderService.java:7:5 [spring.no-field-injection; code] Field injection violates the approved constructor-injection policy
WARNING src/OrderService.java:10:5 [spring.no-value; code] @Value is prohibited by approved policy
7 finding(s) · 4 files analyzed · 1 excluded by policy · 4 approved rules
```

The demo deliberately contains every kind of finding: two conflicting instruction sentences, a code example that teaches a prohibited pattern, a custom rule, code violations, and a legacy directory excluded by the policy scope. Its AGENTS.md also contains a ❌ counter-example, which is correctly **not** flagged. The demo files are analysis fixtures, not a runnable Spring application.

## Pull-request feedback

Compare two separate checkouts to focus on new conflicts while retaining existing
findings. The base checkout policy is used for both scans. The GitHub Action emits
file annotations and a grouped job summary. See the [PR setup and limitations](docs/pull-request-feedback.md).

## The local app

Finding cards show the matched source line, approved policy and scope, confidence
limitations, and suggested fix. They describe team-policy conflicts rather than
claiming that every match is a bug. JSON reports include a source excerpt (up to
500 characters) and the policy settings used for the finding.

```sh
.venv/bin/agentaccord serve examples/spring-demo
```

Open the complete URL the command prints; it carries a per-session token. Four screens walk through the workflow: repository overview, explicit policy approval, agent-guidance preview and update, and findings with search, filters and JSON/SARIF/HTML export.

The server binds only to `127.0.0.1` and to the repository chosen at startup; use `--port 0` for a free port and Ctrl+C to stop. `./run.sh examples/spring-demo` does the same after installation.

## Use it on your repository

```sh
agentaccord init /path/to/project    # proposes rules, all with approved: false
agentaccord serve /path/to/project   # approve the conventions your team wants
agentaccord check /path/to/project
```

Nothing becomes blocking just because it is available: a rule runs only after someone approves it, and the starter catalog is never inferred from your code. Then preview the generated guidance and write it into AGENTS.md's managed section. Handwritten instructions are preserved even when they conflict; findings point at those lines for a human to correct.

## Adopt on an existing codebase

A real repository usually has violations on day one. Record them once, and the check fails only on new ones:

```sh
agentaccord baseline .          # writes .agentaccord-baseline.json — commit it
agentaccord check .             # exit 0: existing findings are accepted, reported, not blocking
# …later, after fixing some of them:
agentaccord baseline . --prune  # removes fixed entries; never adds new ones
```

```text
0 finding(s) · 14 accepted by baseline · 127 files analyzed · 143 excluded by policy · 3 approved rules
```

- **Only new violations fail.** A finding is matched by its rule, file, and the text of its own line, so code moving around the file does not reset it, while editing the violating line makes it new: touched code must comply. Identical lines are counted, so a third copy of a twice-accepted violation is still new.
- **It can only shrink.** `baseline` refuses to overwrite an existing file and `--prune` never adds entries, so new violations are never silently absorbed.
- **Nothing is hidden.** Every report states how many findings the baseline accepted and how many entries were fixed; `check --no-baseline` shows everything. Incomplete analysis still exits 2.
- SARIF results carry `baselineState` (`new`/`unchanged`) and stable `partialFingerprints`, so code scanning tracks findings across line moves.

## Policy file

```yaml
version: 1

# Optional: keep teaching examples, generated or frozen code out of scope.
exclude:
  - "**/examples/**"
  - "legacy/**"

# Optional: your own prohibited Java annotations.
custom:
  custom.no-lombok-data:
    title: Explicit data classes
    annotation: lombok.Data             # fully qualified
    guidance: Do not use @Data. Use records or explicit accessors.
    remediation: Replace @Data with a record.   # optional, defaults to guidance
    target: any                         # or "field" to flag only field-level use

rules:
  spring.no-field-injection: {enabled: true, approved: true, severity: error}
  spring.no-webmvctest:      {enabled: true, approved: true, severity: error}
  spring.no-value:           {enabled: true, approved: false, severity: warning}  # proposed: does not run
  custom.no-lombok-data:     {enabled: true, approved: true, severity: warning}
```

| Key | Meaning |
| --- | --- |
| `rules` | Built-in or custom rule IDs with `enabled`, `approved`, and `severity` (`error` blocks, `warning` reports). |
| `exclude` | Repository-relative globs. `*` and `?` stay within one path segment, `**` spans segments. Every report states how many files were excluded, so a narrowed scope is never silent. |
| `custom` | Team-defined rules; IDs look like `custom.no-lombok-data`. They get the same import-aware code check, instruction-sentence check, code-example check, and generated guidance as built-in rules. |

### Teaching repositories and rule scopes

Ordinary Java files retain conservative import resolution and blocking policy checks.
For a skills library, explicitly mark standalone snippets as teaching examples:

```yaml
version: 1
examples:
  java:
    - "skills/**/examples/**/*.java"
    - "skills/**/templates/**/*.java"
  counter_examples:
    - "skills/**/examples/bad-*.java"
rules:
  spring.no-field-injection:
    approved: true
  spring.no-value:
    approved: true
    allow_job_parameters: true
  spring.no-webmvctest:
    approved: true
    exclude:
      - "skills/**/testing-pyramid/**"
```

Example findings always have severity `warning`, kind `example`, and confidence
`example`, even when the rule normally blocks application code. Missing imports
are matched heuristically; explicit unrelated imports and local annotation declarations
are respected. Unparseable standalone examples remain incomplete (exit 2).
Counter-example paths are omitted **only within `examples.java`**, and their paths
are listed in `counter_example_files`. Ordinary Java files never become examples
based on their filename or a comment.

Each rule accepts `include` and `exclude` globs. An empty include list means all
paths; exclude wins. Omitting one rule does not disable the others.
Reports list affected files and rules in `rule_scope_omissions`, separately from
global exclusions and unsupported files. Instruction files are also subject to
these scopes: include them explicitly when restricting a rule to particular paths.

Only `spring.no-value` accepts `allow_job_parameters: true`. It allows a whole,
literal lookup such as `@Value("#{jobParameters['status']}")` (also named
`value =`). Property placeholders, concatenated expressions, method calls,
and other SpEL remain checked. This does not verify Spring Batch bean scope
or runtime correctness. The default is false.

Configure these settings in YAML or in the local app. Expand **Paths and exceptions**
on a rule to edit its include/exclude paths. Shared controls set global exclusions,
Java teaching-example paths, and counter-example paths. **Preview draft scope**
runs the current draft without saving policy, guidance, or baseline files. It lists
file treatment and applicable rules (first 200 paths), including incomplete analysis.
Edit a path to invalidate the preview, then preview again before saving. Reports distinguish analyzed example files
(`example_files`), omitted counter-examples, rule-scope omissions, and skipped
files. Fenced documentation examples keep their existing non-blocking checks.

The schema is strict: unknown keys and rule IDs, invalid severities or globs (absolute paths, `..`, duplicates), duplicate YAML keys, anchors/aliases, and unsupported versions are rejected. Earlier policy files are still read: `.agentcontract.yml` (0.3) as is, and `.agentcontract.toml` (0.1/0.2) as approved rules. Saving writes `.agentaccord.yml`, which then takes precedence; the old file is retained. Policies represent team choices: neither `@WebMvcTest` nor `@Value` is universally wrong.

## Built-in rules

| Rule | What is checked |
| --- | --- |
| `spring.no-field-injection` | Field-level Spring `@Autowired` and Jakarta/Javax `@Inject`/`@Resource`. Constructor and setter injection pass, and **test classes are exempt** (a class annotated `@SpringBootTest`, `@WebMvcTest`, `@DataJpaTest`, `@ExtendWith`, … or with JUnit `@Test` methods), because field injection is idiomatic there. |
| `spring.no-webmvctest` | Spring Boot `@WebMvcTest`, for both the Boot 3 and Boot 4 packages. |
| `spring.no-value` | Spring `@Value`. Lombok's `@Value` is a different annotation and is not flagged. |
| `python.no-mutable-defaults` | List/dict/set literal defaults, using the Python AST. |
| `python.require-type-hints` | Missing parameter or return annotations, exempting `self`/`cls`. |

`agentaccord rules /path/to/project` lists built-in and custom rules.

## How the analysis works

**Java** is parsed with Tree-sitter, and annotations are resolved like the compiler does: explicit imports and qualified names; otherwise a simple name can only come from a wildcard import or the file's own package. So `@Value` with `import lombok.*;` is provably not Spring's, while genuinely ambiguous names, import-free snippets, and syntax errors are reported as **incomplete analysis** rather than a false clean result. Custom meta-annotations and cross-file resolution are not supported.

**Instruction files** (`AGENTS.md`, `CLAUDE.md`, `SKILL.md`, `copilot-instructions.md`, `*.instructions.md`) are checked two ways:

- **Sentences**: direct affirmative directives such as `Use @WebMvcTest…`, `Prefer field injection…`, `Always use @Data…`, including nested list items. Negative and conditional lines, block quotes, HTML comments, and indented code blocks are skipped. This is deterministic pattern matching, not natural-language understanding.
- **Code examples**: ```` ```java ```` and unlabelled fences are analyzed as Java, because examples teach agents as strongly as prose. A block counts as a counter-example, and is skipped, when its first lines or the two lines before it say ❌, *Bad*, *Wrong*, *Avoid*, *Don't*, *Before*, or *Without*; ✅ or *Good* wins. Example findings are always **warnings** with confidence `example`, so a heuristic never blocks a build on its own.

**Python** uses the standard-library AST; scanned modules are never imported.

Findings carry a `kind` (`code`, `instruction`, or `example`) and a `confidence` (`syntax`, `pattern`, or `example`). Policies apply within their configured path scopes; instruction precedence between files is not interpreted.

## Agent guidance stays in sync

`agentaccord guidance <path>` previews, and `--write` updates, only the block between these markers in AGENTS.md:

```text
<!-- agentaccord:begin -->
<!-- agentaccord:end -->
```

Text outside the block is preserved. A missing block is appended; malformed or duplicate markers and symlinked targets are refused. Updates are idempotent and atomic.

## In CI

Exit codes are a stable contract:

| Exit | Meaning |
| --- | --- |
| 0 | No blocking violations among configured, supported checks |
| 1 | Approved policy violations not accepted by the baseline |
| 2 | Tool or configuration failure, incomplete analysis, or no approved rules |

**GitHub Action**: checks the repository, shows findings as code scanning annotations on pull requests, and fails on blocking findings:

```yaml
name: AgentAccord
on: [pull_request]
permissions:
  contents: read
  security-events: write   # for the code scanning upload
jobs:
  policy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: rrezartprebreza/agentaccord@v0.4.1
```

| Input | Default | Meaning |
| --- | --- | --- |
| `path` | `.` | Repository path to check |
| `sarif` | `true` | Upload findings to GitHub code scanning |
| `python-version` | `3.13` | Python used to run AgentAccord |

The `exit-code` output (0/1/2) is available to later steps. The action installs its own tagged source, so a pinned tag always runs exactly that version. It is listed on the GitHub Marketplace as **AgentAccord Check**.

**pre-commit:**

```yaml
repos:
  - repo: https://github.com/rrezartprebreza/agentaccord
    rev: v0.4.1
    hooks:
      - id: agentaccord
```

Reports: `--format console|json|html|sarif`. `--output` never overwrites an existing file, and the exit code is preserved even when a report was written.

## Command line

```sh
agentaccord init [path]       # propose rules (unapproved)
agentaccord serve [path]      # local app; --port 0 picks a free port
agentaccord check [path]      # --format console|json|html|sarif, --output FILE, --no-baseline
agentaccord baseline [path]   # accept existing findings; --prune removes fixed ones
agentaccord guidance [path]   # preview; --write updates AGENTS.md's managed block
agentaccord rules [path]      # built-in and custom rules
agentaccord scan [path]       # languages, manifests and instruction files found
agentaccord doctor [path]     # versions and policy validity
```

## Trust, privacy, and limits

- **Never runs your code.** No project scripts are executed and scanned Python modules are never imported. No external service or AI model is involved.
- **Symlinks are not followed.** A link to an analyzed file inside the repository, such as `CLAUDE.md -> AGENTS.md`, loses nothing because the target is analyzed at its own path, and links the analysis would never read are ignored. A relevant link that leaves the repository or is broken makes the analysis incomplete.
- **Bounded.** Relevant files over 1 MB, non-UTF-8 files, and parse errors are reported as skipped; scanning stops after 10,000 file entries; build and vendor directories are excluded.
- **Hardened local app.** Per-session token, strict Host/Origin checks, content security policy, and loopback-only binding. It is a local development app, not a hosted multi-user service or a sandbox against hostile concurrent filesystem changes. Stop it when finished.
- Reports can include paths and short evidence; review them before sharing.

This is an early release. TypeScript and C#, convention inference, pull-request diff analysis, and a full plugin contract are future work; see the [roadmap](docs/ROADMAP.md).

## Development

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover the analyzers and their false positives, policy validation and migration, scopes, custom rules, code-example detection, baselines, guidance preservation, report escaping, SARIF structure, regressions found on real repositories, and real loopback HTTP flows. CI runs them on Linux and macOS with Python 3.12 and 3.13 and checks the CLI exit-code contract against the examples.

See [CONTRIBUTING.md](CONTRIBUTING.md): every rule needs a stable ID, explicit approval, actionable remediation, and positive, negative, and false-positive tests.

## Feedback

Try the demo, then a repository whose policies you know. Report false positives, missing rules, or installation problems in [GitHub Issues](https://github.com/rrezartprebreza/agentaccord/issues) with your OS, Python and AgentAccord versions, the relevant policy, a minimal example, and expected versus actual behavior; remove secrets and private code first. The most useful feedback is whether you would keep a check enabled in your daily workflow.

MIT licensed. Dependencies retain their own licenses.
