from pathlib import Path
import sys

required = [
    "ai-dos.yaml",
    "AGENTS.md",
    "docs/00-project-overview.md",
    "docs/02-architecture.md",
    "tasks/active-task.md",
    "tasks/handoff.md",
    ".cursor/rules/00-global-rules.mdc",
]

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
missing = [x for x in required if not (root / x).exists()]
if missing:
    print("Missing:")
    for x in missing:
        print("-", x)
    raise SystemExit(1)

print("AI-DOS structure is valid.")
