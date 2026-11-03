# Public repository trial — 2026-11-03

AgentAccord checked three public repositories at pinned commits. This is a small,
purposefully selected compatibility trial, not an adoption study or accuracy benchmark
with independently labelled ground truth.

The trial uses the local work on branch `codex/example-policy-precision`, based on
`b416b1586d8d7b6eb9734816c3c776b3fdcfa10f`. The package still reports 0.4.1;
the changes are unreleased. Each run records analyzer source hashes to distinguish it
from the published package.

## Results

| Repository | Diagnostic policy | Analyzed files | Findings | Skipped |
| --- | --- | ---: | ---: | ---: |
| Spring Petclinic | Three Spring rules, repository-wide | 50 | 6 | 0 |
| Spring Batch guide | Three Spring rules, repository-wide | 7 | 0 | 0 |
| Flask | Both Python rules, repository-wide | 83 | 1,012 | 0 |
| Flask | Mutable defaults everywhere; explicit type hints under `src/**` | 83 | 3 | 0 |

There are 140 distinct analyzed files across the three repositories; Flask's two
profiles scan the same files. No baseline, global exclusion, example-path override,
or Batch exception was enabled. The profiles are hypothetical evaluator choices,
**not policies approved by the upstream maintainers**. The scoped Flask run still
checks mutable defaults in all Python files.

No supported instruction files were found in these checkouts. These results therefore
exercise code checks, not real-world instruction/code drift. Spring Boot Skills remains
our separate instructional-content trial.

## Manual review

All six Petclinic findings and all three source-scoped Flask findings were inspected
at the reported location, including Java imports and complete Python signatures.

- Five Petclinic findings resolve to Spring's `@WebMvcTest`. These accurately match a
  hypothetical ban, but controller slices are an intentional testing choice. Their
  presence is not a defect.
- One Petclinic finding resolves to Spring's `@Value` for `local.server.port` in an
  integration test. The annotation matches the rule. However, the generic advice to
  move it into configuration properties is poorly suited to this runtime test value.
  Spring documents [`@LocalServerPort` for this purpose](https://docs.spring.io/spring-boot/reference/testing/spring-boot-applications.html).
  The subsequent pilot preparation adds this specific recommendation for literal
  test-field injection, without suppressing the policy finding. The original
  review ledger preserves the assessment of the initial run.
- Three Flask findings are `__init__` methods with annotated parameters and no explicit
  return annotation. They match AgentAccord's strict requirement, but
  [mypy permits this constructor convention](https://mypy.readthedocs.io/en/latest/class_basics.html).
  They are policy differences, not demonstrated typing bugs.

Thus **0 of the 9 reviewed findings were syntactic mismatches against the configured
rules**. This is not a general false-positive rate: usefulness was not established
by maintainers, the remaining global Flask findings were not individually reviewed,
and missed violations were not independently enumerated. Recall is unknown.
A clean Batch guide result does not establish that every possible violation would
be detected. The guide does not exercise the new jobParameters exception.

The global Flask type-hint policy generates 1,009 additional findings outside
`src/**`. Scoping makes the review smaller; it does not automatically make the
remaining findings actionable.

## Pinned sources and reviewed locations

| Repository | Revision |
| --- | --- |
| [Spring Petclinic](https://github.com/spring-projects/spring-petclinic) | `500158f732419217507c7656904b8e6aa1bcc0d6` |
| [Spring Batch guide](https://github.com/spring-guides/gs-batch-processing) | `8432843d2be2c50a473541887d5f96f27581d667` |
| [Flask](https://github.com/pallets/flask) | `49943b5a94413a530761350f04e896f76e8d620e` |

The companion [review ledger](public-repository-review.json) records each reviewed
finding, a source permalink, and its assessment.

## Reproduce

Use Python 3.12+ and install this AgentAccord checkout into a virtual environment.
Clone each linked source repository into a parent directory using the names above,
then detach each checkout at the exact revision in the table. Keep all checkouts clean.

From the AgentAccord root:

```sh
.venv/bin/python scripts/evaluate_public_repos.py /path/to/checkouts /path/to/new-results
```

The output directory must not exist. The evaluator verifies the commits and clean
working trees before scanning, records policies and analyzer hashes, and writes JSON
and HTML reports. It never installs, imports, builds, or runs the target projects.
It exits successfully when the evaluation completes; individual check exit codes
are recorded in the summary.

## Product decisions

1. Keep every rule opt-in and describe findings as policy conflicts.
2. Explain path scope before encouraging users to enable more rules.
3. Improve context-sensitive remediation, starting with runtime test values.
4. Gather developer feedback before claiming the tool saves time or prevents defects.
5. Run a pilot with real instruction files and code changes to evaluate the central
   instruction/code alignment claim, not merely annotation detection.

See the [pilot guide](pilot-guide.md) for a reproducible first-use exercise and a
feedback form. No upstream maintainers were contacted during this trial.
