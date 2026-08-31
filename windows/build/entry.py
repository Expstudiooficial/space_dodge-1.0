"""What PyInstaller starts.

A one-line file on purpose. The spec names this as the entry point, and
everything it needs to do is already in the package - so there is nothing here
to drift out of step with `python -m pycmd_win.app`, which is how the app is
run from a checkout.
"""

import os
import sys

# In a packed build the package rides along inside the exe; from a checkout it
# is one folder up. Both work, and neither needs an installed copy.
_here = os.path.dirname(os.path.abspath(__file__))
_windows = os.path.dirname(_here)
if os.path.isdir(os.path.join(_windows, "pycmd_win")) and _windows not in sys.path:
    sys.path.insert(0, _windows)

from pycmd_win.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
