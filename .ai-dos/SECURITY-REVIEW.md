# Security Review Checklist

- Identify assets, trust boundaries, actors, entry points, and abuse cases.
- Confirm authentication and authorization at every protected operation.
- Validate and bound untrusted input; avoid command/query/template injection.
- Keep secrets out of code, logs, errors, prompts, fixtures, and commits.
- Review cryptography, TLS, CORS/CSRF, session/cookie, upload and path handling.
- Apply least privilege to filesystem, database, cloud, CI, and tokens.
- Review new/updated dependencies, lockfiles, licenses, provenance, and advisories.
- Check sensitive data collection, retention, encryption, redaction, and deletion.
- Test failure modes, rate limits, replay, concurrency, and rollback.
- Record findings as Critical/High/Medium/Low with evidence, impact, fix, and owner.

