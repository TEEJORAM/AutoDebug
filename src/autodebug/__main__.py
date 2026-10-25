if not __package__:  # run as `python <checkout>/src/autodebug`: no install or PYTHONPATH needed
    import os
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != here]
    sys.path.insert(0, os.path.dirname(here))

from autodebug.cli import main

raise SystemExit(main())
