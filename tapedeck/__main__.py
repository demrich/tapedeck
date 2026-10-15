import sys

from . import look

look.prepare()       # before Gtk is imported (see look.py)

from .deck import main  # noqa: E402

sys.exit(main())
