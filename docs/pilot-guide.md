# Try AgentAccord on one real team policy

The question for this pilot is: **does AgentAccord help your team keep agent
instructions and code aligned with a rule you already agreed on?**

Use an isolated checkout. Start with one actual team rule and choose its scope
before running a check. Record how long installation and the first useful review
take; do not count the number of findings as value.

## First use

1. Install the AgentAccord version or checkout being evaluated and record its version.
2. Run `agentaccord init /path/to/repository`, then `agentaccord serve /path/to/repository`.
3. Approve one supported rule that your team actually wants. Start at warning severity.
   For example, choose constructor injection only if that is an existing team policy.
4. In YAML, set any per-rule include/exclude paths needed for the agreed scope.
   The local app preserves these advanced settings when saving approval and severity.
5. Run checks. Review the actual source, skipped files, and scope omissions.
6. Review generated guidance in the app before choosing to write it into `AGENTS.md`.
   Keep a diff of the generated section for the team's review.

For a controlled test in the isolated checkout, add a temporary instruction that
contradicts the approved rule and a matching source violation with explicit imports.
Check that both appear. Fix both and check again, then remove the temporary changes.
Record this as a controlled detection test, separately from naturally occurring findings.

Example: for an approved constructor-injection policy, a temporary instruction can say
`Use field injection.`, paired with a Java class containing an explicitly imported
Spring `@Autowired` field. Do not run or deploy this temporary fixture.

## Review each finding

| Field | What to record |
| --- | --- |
| Location and rule | Path, line, and stable rule ID |
| Correct detection? | Does the source actually match the configured policy? |
| Policy applies here? | Did your team intend the rule to cover this file? |
| Useful recommendation? | Would the proposed change help, and is the remediation suitable? |
| Decision | Fix, change scope, document an exception, or report a tool defect |
| Effort | Minutes to understand the finding and decide |

A source match can be correct while the policy or remediation is inappropriate.
Keep these separate. Do not hide unsupported files just to obtain a passing result.

## Feedback to return

- Repository language/framework and AgentAccord version or commit.
- The one agreed policy and its scope.
- Installation and first-review time.
- Counts of reviewed findings: accurate matches, incorrect matches, scope mismatches,
  and useful recommendations.
- Any missed violations found independently.
- Whether both instruction and source conflicts were detected in the controlled test.
- One concrete change you made because the tool helped.
- Whether you would run it on the next pull request, and why.

Share only source excerpts you are permitted to share. No upload is needed to run the tool.

For an initial pilot, seek feedback from three teams with different repositories.
That target is a proposed next step, not completed user research. Use the feedback
to decide whether to add rules, improve onboarding, or address incorrect advice first.
