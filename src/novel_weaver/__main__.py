# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

import sys
from pathlib import Path

# Allow `python -m novel_weaver` without installing
if __name__ == "__main__" and __package__ is None:
    src = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(src))

from novel_weaver.cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
