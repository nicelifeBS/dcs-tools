"""PyInstaller entry point (the package itself is imported, not run as a script)."""

import sys

from replay_helper.app import main

sys.exit(main())
