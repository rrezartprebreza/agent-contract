# Changelog

All notable changes to AgentAccord are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.4.0] - 2026-11-02

### Renamed

- **AgentContract is now AgentAccord.** `agentcontract` is already published on PyPI by another AI-agent project. Package, CLI command, module, and new files use `agentaccord`. Existing repositories keep working: `.agentcontract.yml`, `.agentcontract.toml`, `.agentcontract-baseline.json`, and `agentcontract:begin/end` markers are still read, and the next `guidance --write` migrates the markers in place.

### Added

- **Code examples in instruction files.** Fenced Java in `SKILL.md`, `AGENTS.md`, and other instruction files is checked as guidance. Labelled counter-examples (❌, Bad, Wrong, Avoid, Don't, Before, Without) are skipped, and ✅/Good wins. Example findings are always non-blocking warnings.
- **Custom rules** (`custom.*` in the policy): team-defined prohibited Java annotations with the same code, instruction-sentence, code-example, and guidance support as built-in rules.
- **Baselines.** `agentaccord baseline` accepts existing findings so checks fail only on new ones; `--prune` removes fixed entries and never adds new ones; `check --no-baseline` shows everything. Findings match by rule, file, and their own line text, so moved code stays accepted and edited lines become new.
- **Policy scopes.** `exclude:` globs remove paths from analysis; every report states how many files were excluded.
- SARIF `baselineState` and stable `partialFingerprints` for GitHub code scanning.
- A GitHub Action (`uses: rrezartprebreza/agentaccord@v0.4.0`) and a pre-commit hook.
- CI on Linux and macOS with Python 3.12 and 3.13, and a tag-triggered release workflow publishing to PyPI.

### Changed

- Java annotation resolution follows Java scoping rules: an unimported simple name can only come from a wildcard import or the file's own package, so Lombok's `@Value` via `import lombok.*` is no longer reported as incomplete.
- `spring.no-field-injection` exempts test classes (Spring test annotations or JUnit `@Test` methods), where field injection is idiomatic.
- Symlinks the analysis never reads no longer make checks incomplete; a link to an analyzed file inside the repository, such as `CLAUDE.md -> AGENTS.md`, is covered.
- Indented text inside Markdown lists is treated as instructions, not as an indented code block.
- Unexpected crashes exit 2 (tool failure) instead of 1 (violations).
- The version is defined once, in `agentaccord.__version__`.

### Fixed

- The local app no longer drops policy fields it does not render when saving.
- Python finding columns are correct after form feeds and other non-newline line breaks.
- Clearer syntax-error reasons for skipped Python files.
- Correct singular/plural wording in the app's result summary.

## [0.3.0] - 2026-11-02

First public release, as AgentContract.

- Local browser workspace backed by the same engine as the CLI.
- Strict versioned YAML policy validation with explicit approval; legacy TOML policies are read.
- Tree-sitter Java annotation checks with conservative import resolution; Python AST checks.
- Narrow instruction-conflict detection that excludes common example formats.
- Managed guidance synchronization that preserves handwritten content.
- Console, JSON, HTML, and SARIF reports.

[0.4.0]: https://github.com/rrezartprebreza/agentaccord/releases/tag/v0.4.0
[0.3.0]: https://github.com/rrezartprebreza/agentaccord/commit/efa87d5
