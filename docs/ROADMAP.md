# Release status

## Delivered in 0.3

- Local browser workspace backed by the same engine as the CLI.
- Strict versioned YAML/Pydantic policy validation, explicit approval, legacy TOML reading.
- Syntax-aware Java annotation checks with conservative import resolution and field-injection checks.
- Python AST checks and narrow instruction-conflict detection that excludes common example formats.
- Managed guidance synchronization preserving handwritten content.
- Console, JSON, HTML, SARIF, local discovery, diagnostics, and packaged static assets.
- Regression tests and loopback HTTP integration tests.

## Delivered after 0.3.0

- Code examples in instruction files: fenced Java is checked as guidance, labelled counter-examples (❌/Bad/Avoid…) are skipped, and findings are non-blocking warnings.
- Custom annotation rules (`custom.*`) with the same code, instruction, example, and guidance support as built-ins.
- Policy `exclude` scopes, reported in every output format.
- Wildcard-aware Java resolution (Lombok `@Value` is no longer ambiguous) and test-class exemption for field injection.
- Symlink handling that no longer makes unrelated links (or `CLAUDE.md -> AGENTS.md`) incomplete.
- Baselines: accept existing findings, fail only on new ones; the baseline can only shrink. SARIF `baselineState` and `partialFingerprints`.
- First real-repository trial (a 66-skill Spring Boot skills repository), CI on Linux/macOS with Python 3.12/3.13, and a pre-commit hook.

## Next acceptance gates

1. Broader Java resolution, framework-version fixtures, per-rule scopes (e.g. different rules for `src/test/**`), and more real-repository trials.
1a. Section headings as guidance (e.g. `## Controller tests (@WebMvcTest)`), and custom rules for Python.
2. TypeScript analyzer and tested instruction precedence mappings.
3. Inline suppressions with a required reason, `--changed-since` diff analysis, complete SARIF schema validation, and pull-request integration.
4. C# adapter, plugin boundaries, stronger resource/process isolation, and release signing.

CLI remains argparse rather than Typer. Convention suggestions are a rule catalog, not inferred claims. The local UI intentionally selects the repository at server startup rather than exposing arbitrary filesystem browsing. No external AI service is involved.

## Parser reference

The Java analyzer uses the official Python Tree-sitter API: https://tree-sitter.github.io/py-tree-sitter/ and the tree-sitter-java grammar.
