# Contributing

Use Python 3.12+. Install with `python3 -m venv .venv` and `.venv/bin/python -m pip install .`. Run `.venv/bin/python -m unittest discover -s tests -v`; HTTP tests bind ephemeral loopback ports.

Every rule needs a stable ID, explicit configuration and approval, actionable remediation, positive/negative cases, and false-positive tests. Changes to instruction patterns require examples, negation, and conditional fixtures. Changes to code-example detection require labelled counter-example fixtures (❌/Bad/Avoid…) and must keep example findings non-blocking. Custom-rule changes need validation tests and must keep built-in and custom rules on the same analysis path. Never infer approval from code prevalence.

The engine is shared between the CLI and local app. Do not execute scanned repository code, follow symlinks, silently upload content, or downgrade incomplete analysis to a pass. Preserve exit codes: 0 clean supported checks, 1 violations, 2 incomplete/tool errors. A baseline may only accept findings that existed when it was created: never let `--prune` or any other path add entries.

Treat paths and source text as untrusted in reports/UI. Preserve the local app's session-token, Host/Origin, CSP, and fixed-root boundaries. Test policy and guidance write behavior before changing it. Label limitations precisely and keep documentation aligned with tested behavior.

## Releasing

1. Set the version in `agentaccord/__init__.py` (the only place it is defined) and add its section to `CHANGELOG.md`.
2. Merge to `main` with CI green.
3. Tag and push: `git tag v0.4.0 && git push origin v0.4.0`.

The `Release` workflow checks that the tag matches `__version__`, runs the tests, builds and verifies the distributions, publishes to PyPI with trusted publishing (no stored token), and creates the GitHub release from the changelog section. The tag also becomes the version users pin with `uses: rrezartprebreza/agentaccord@v0.4.0` and in pre-commit.
