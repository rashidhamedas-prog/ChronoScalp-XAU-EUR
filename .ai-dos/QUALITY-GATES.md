# Quality Gates

Configure exact commands in `ai-dos.yaml`; `CONFIGURE_ME` is not a passing gate.

Required evidence for completion:

1. Formatting/lint/type checks applicable to changed files.
2. Unit tests for changed behavior and edge cases.
3. Integration/contract/migration tests when a boundary changes.
4. Reproducible build or packaging check.
5. Independent diff review against acceptance criteria.
6. Security review when any configured trigger applies.
7. No new exposed secret, unexplained warning, or silently skipped failure.

An exception must name the gate, reason, impact, compensating check, approver, and expiry/follow-up task. Critical security gates cannot be waived by the Implementer.

