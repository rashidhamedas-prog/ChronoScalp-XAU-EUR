"""Allow ``python -m chronoscalp.validation``."""

from __future__ import annotations

import sys

from chronoscalp.validation.run import main

if __name__ == "__main__":
    sys.exit(main())
