"""Language engines that run on the device.

Android forbids an app from making memory executable or loading a library it
wrote itself, so a compiler could emit correct machine code and never be able
to run it. These are interpreters instead: they walk the parsed program, which
is exactly how CPython runs here too.
"""

__all__ = ["c_interp", "c_lexer", "c_parser", "c_stdlib", "registry"]
