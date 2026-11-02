# Release status

## Delivered in 0.3

- Local browser workspace backed by the same engine as the CLI.
- Strict versioned YAML/Pydantic policy validation, explicit approval, legacy TOML reading.
- Syntax-aware Java annotation checks with conservative import resolution and field-injection checks.
- Python AST checks and narrow instruction-conflict detection that excludes common example formats.
- Managed guidance synchronization preserving handwritten content.
- Console, JSON, HTML, SARIF, local discovery, diagnostics, and packaged static assets.
- Regression tests and loopback HTTP integration tests.

## Next acceptance gates

1. Broader Java resolution, framework-version fixtures, configurable file scopes, and real-repository trials.
2. TypeScript analyzer and tested instruction precedence mappings.
3. Git diff/baseline analysis, complete SARIF schema validation, and pull-request integration.
4. C# adapter, plugin boundaries, stronger resource/process isolation, and release signing.

CLI remains argparse rather than Typer. Convention suggestions are a rule catalog, not inferred claims. The local UI intentionally selects the repository at server startup rather than exposing arbitrary filesystem browsing. No external AI service is involved.

## Parser reference

The Java analyzer uses the official Python Tree-sitter API: https://tree-sitter.github.io/py-tree-sitter/ and the tree-sitter-java grammar.
