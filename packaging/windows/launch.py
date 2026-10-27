"""Entry point for the frozen (PyInstaller) Windows build."""

import sys

from openmine.app import main

if __name__ == "__main__":
    sys.exit(main())
