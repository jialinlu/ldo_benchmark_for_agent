#!/usr/bin/env python3
import sys
from evoldo_bench.cli import main

raise SystemExit(main(["aggregate"] + sys.argv[1:]))
