#!/usr/bin/env python3
"""rmpp-studio: record, edit and export reMarkable Paper Pro tutorials (PySide6)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from studio.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
