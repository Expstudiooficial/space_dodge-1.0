"""PyCmd for Windows.

The shell around the engine PyCmd already had. Everything under
``app/src/main/python`` is shared with the Android build unchanged - the
interpreters, the plugin runtime, the servers, pages, music and cloud - and
this package is what a Windows machine needs that a phone did not:

* :mod:`~pycmd_win.store`      where files live, under %LOCALAPPDATA%
* :mod:`~pycmd_win.toolchains` the compilers actually installed on the machine
* :mod:`~pycmd_win.langs`      the language table, with Android's caveats lifted
* :mod:`~pycmd_win.runner`     pressing Run, with real toolchains
* :mod:`~pycmd_win.host`       the one object the window's JavaScript calls
* :mod:`~pycmd_win.updates`    where new versions come from
* :mod:`~pycmd_win.app`        the window itself
"""

__version__ = "1.0.0"
