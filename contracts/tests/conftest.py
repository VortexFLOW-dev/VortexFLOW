# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import os
import secrets
import sys
from pathlib import Path

# A throwaway key so importing the backend app (settings require one) works.
os.environ.setdefault("VORTEXFLOW_SECRET_KEY", secrets.token_hex(32))

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)
