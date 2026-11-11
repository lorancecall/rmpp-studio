#!/usr/bin/env python3
"""rmpp-ctl: command line front end of rmpp_ctl.py (see there, or `python rmpp-ctl.py -h`)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rmpp_ctl import main  # noqa: E402

if __name__ == "__main__":
    main()
