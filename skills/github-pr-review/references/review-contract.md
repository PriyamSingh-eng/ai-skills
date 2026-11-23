# Review output contract

Use this contract for each stack pass and for the final merged review. The human-readable section and JSON must describe the same findings.

## Severity

| Level | Meaning |
| --- | --- |
| P0 — Critical | Credible severe security exposure, data loss, or a production outage affecting core behavior. |
| P1 — Important | A concrete correctness or reliability defect with significant user or operational impact. |
| P2 — Moderate | A material edge-case, resilience, compatibility, or maintainability issue introduced by the change. |
| P3 — Minor | A low-impact issue. Usually omit style-only observations; report them only when a repeated pattern creates a real cost. |

Severity describes impact, not confidence. State uncertainty and evidence in the finding body. Do not inflate severity to make a review sound useful.

## Human-readable review

Present:

```text
**Diff stats:** files changed, additions, deletions, and inferred change type

**Summary:** what the PR changes and its risk level

**Requirements coverage:** coverage of the PR description and linked Jira requirements, if available

**Findings:** group by P0 → P3 and omit empty groups
> **[P{N}] Short title** — `path:line`
> Explain the concrete impact and why the changed code causes it.
> Include a small suggested fix only when it is clear and useful.

**Questions for the author:** omit if there are none

**Recommendation:** APPROVE | REQUEST CHANGES | NEEDS DISCUSSION — with a brief rationale
```

The recommendation is the reviewer's assessment. It does not submit a GitHub approval or request-changes event.

## Machine-readable JSON

After the prose, provide one fenced `json` block matching this shape:

```json
{
  "summary": "One paragraph describing the change",
  "risk_level": "Low | Medium | High | Critical",
  "requirements_coverage": "What requirements are covered, or why coverage could not be checked",
  "change_type": "new feature | refactor | bug fix | config | mixed",
  "verdict": "APPROVE | REQUEST CHANGES | NEEDS DISCUSSION",
  "verdict_rationale": "One sentence",
  "findings": [
    {
      "id": 1,
      "severity": "P1",
      "type": "inline",
      "path": "src/example.py",
      "line": 42,
      "side": "RIGHT",
      "comment_body": "Explain the issue and its impact."
    },
    {
      "id": 2,
      "severity": "P2",
      "type": "general",
      "path": null,
      "line": null,
      "side": null,
      "comment_body": "Explain a review concern that is not anchored to one changed line."
    }
  ],
  "questions_comment": "Questions for the author, or an empty string"
}
```

## Finding rules

- Assign IDs unique within the current stack result; the merger assigns IDs unique across the final review. Sort findings by severity, then by path and line.
- Use `inline` only when a specific changed line demonstrates the issue. `path` and `line` must match the PR's changed file and diff; `side` is `RIGHT` for the new/changed side. Use `general` with null location fields when no changed line is a valid anchor.
- Never invent a line number, file path, requirement, test result, API response, or author intent.
- Keep findings self-contained: identify the condition, impact, and the relevant reason. Prefer a concrete fix over vague advice.
- Do not duplicate the same defect across stack passes. If no actionable findings exist, return an empty `findings` array and say so in the prose.
- Keep `questions_comment` empty when no clarification is needed.
- If a diff is truncated or omitted by GitHub, disclose that review coverage is incomplete. Do not claim the unseen part was reviewed.
