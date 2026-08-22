"""Execution engine that the Kotlin layer drives.

Everything the user types goes through :func:`run_source`. Output is pushed to a
Java/Kotlin sink object as it is produced, so the console can stream instead of
waiting for the script to finish.
"""

from __future__ import annotations

import ast
import builtins
import io
import os
import sys
import threading
import time
import traceback
import types

__all__ = [
    "configure",
    "run_source",
    "run_file",
    "request_stop",
    "reset_namespace",
    "completions",
    "runtime_info",
]

# ---------------------------------------------------------------------------
# Streams
# ---------------------------------------------------------------------------


class _SinkStream(io.TextIOBase):
    """A text stream that forwards everything to the Kotlin output sink."""

    def __init__(self, sink, stream_name: str) -> None:
        self._sink = sink
        self._name = stream_name

    # io.TextIOBase plumbing -------------------------------------------------
    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def isatty(self) -> bool:
        # Makes libraries such as rich emit colour rather than plain text.
        return True

    @property
    def encoding(self) -> str:
        return "utf-8"

    @property
    def name(self) -> str:
        return f"<{self._name}>"

    def write(self, text) -> int:
        if not isinstance(text, str):
            raise TypeError(f"write() argument must be str, not {type(text).__name__}")
        if text:
            self._sink.onOutput(self._name, text)
        return len(text)

    def flush(self) -> None:  # pragma: no cover - nothing is buffered
        return None


class _SinkInput(io.TextIOBase):
    """stdin backed by the console's input box.

    ``readline`` blocks the Python worker thread until the UI supplies a line,
    which is exactly the semantics ``input()`` expects.
    """

    def __init__(self, sink) -> None:
        self._sink = sink
        self._buffer = ""

    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def isatty(self) -> bool:
        return True

    @property
    def encoding(self) -> str:
        return "utf-8"

    def readline(self, size: int = -1) -> str:
        if not self._buffer:
            line = self._sink.onReadLine()
            if line is None:
                # The only reason the sink refuses a line is that the run was
                # stopped, so report it the same way any other stop is.
                raise KeyboardInterrupt("execution stopped")
            self._buffer = line
        if size is not None and size >= 0:
            chunk, self._buffer = self._buffer[:size], self._buffer[size:]
            return chunk
        chunk, self._buffer = self._buffer, ""
        return chunk

    def read(self, size: int = -1) -> str:
        if size is not None and size >= 0:
            out = []
            remaining = size
            while remaining > 0:
                piece = self.readline(remaining)
                if not piece:
                    break
                out.append(piece)
                remaining -= len(piece)
            return "".join(out)
        out = []
        while True:
            piece = self.readline()
            if not piece:
                break
            out.append(piece)
        return "".join(out)


# ---------------------------------------------------------------------------
# Engine state
# ---------------------------------------------------------------------------

_sink = None
_workspace = None
_state_lock = threading.RLock()
_stop_flag = threading.Event()
_namespace: dict = {}
_run_counter = 0
_active_thread_id: int | None = None

# Interrupt machinery, decided once by _select_interrupt().
_set_async_exc = None
_use_async_exc = False


def _resolve_async_exc():
    """The CPython entry point for raising an exception in another thread."""
    try:
        import ctypes

        set_async = ctypes.pythonapi.PyThreadState_SetAsyncExc
        set_async.argtypes = (ctypes.c_ulong, ctypes.py_object)
        set_async.restype = ctypes.c_int
        return set_async
    except Exception:  # noqa: BLE001 - ctypes may be unavailable or restricted
        return None


def _probe_async_exc(set_async) -> bool:
    """Prove the call actually interrupts a thread before relying on it.

    ctypes can import cleanly and still be unable to reach the interpreter's
    symbols. Stopping a runaway loop is not something to find out about later,
    so it is tested here, once, against a throwaway thread.
    """
    import ctypes

    keep_spinning = threading.Event()

    def spin() -> None:
        try:
            while not keep_spinning.is_set():
                pass
        except KeyboardInterrupt:
            pass

    thread = threading.Thread(target=spin, name="pycmd-probe", daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        set_async(ctypes.c_ulong(thread.ident), ctypes.py_object(KeyboardInterrupt))
    except Exception:  # noqa: BLE001
        keep_spinning.set()
        return False
    thread.join(timeout=1.0)
    interrupted = not thread.is_alive()
    keep_spinning.set()  # Release the thread if the interrupt never landed.
    return interrupted


def _select_interrupt() -> str:
    """Pick the interrupt mechanism and report which one is in use.

    Async exceptions cost nothing while code runs. The trace-hook fallback
    works everywhere but makes every line of Python roughly twice as slow, so
    it is only used when the fast path cannot be verified.
    """
    global _set_async_exc, _use_async_exc

    _set_async_exc = _resolve_async_exc()
    _use_async_exc = _set_async_exc is not None and _probe_async_exc(_set_async_exc)
    return "async-exc" if _use_async_exc else "trace-hook"


def _clear_pending_async_exc(thread_id: int) -> None:
    """Drop an interrupt that was requested after the run already finished."""
    if not _use_async_exc or _set_async_exc is None:
        return
    import ctypes

    try:
        _set_async_exc(ctypes.c_ulong(thread_id), ctypes.py_object())
    except Exception:  # noqa: BLE001
        pass


def _fresh_namespace() -> dict:
    module = types.ModuleType("__main__")
    ns = module.__dict__
    ns["__builtins__"] = builtins
    ns["__name__"] = "__main__"
    ns["__doc__"] = None
    ns["__package__"] = None
    ns["__spec__"] = None
    # Keep the module alive so pickle/dataclasses can resolve __main__.
    sys.modules["__main__"] = module
    return ns


def configure(sink, workspace_dir: str, site_packages_dir: str) -> str:
    """Install streams and search paths. Called once from Kotlin at startup."""
    global _sink, _workspace, _namespace

    with _state_lock:
        _sink = sink
        _workspace = workspace_dir

        sys.stdout = _SinkStream(sink, "stdout")
        sys.stderr = _SinkStream(sink, "stderr")
        sys.stdin = _SinkInput(sink)
        sys.argv = ["<pycmd>"]

        for path in (site_packages_dir, workspace_dir):
            os.makedirs(path, exist_ok=True)
            if path not in sys.path:
                sys.path.insert(0, path)

        os.environ.setdefault("HOME", workspace_dir)
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        os.environ.setdefault("TERM", "xterm-256color")
        # rich/click look at these to decide on colour and wrapping.
        os.environ.setdefault("FORCE_COLOR", "1")
        os.environ.setdefault("COLUMNS", "80")

        try:
            os.chdir(workspace_dir)
        except OSError:
            pass

        _namespace = _fresh_namespace()

    _select_interrupt()
    return sys.version


def reset_namespace() -> None:
    """Throw away every variable the user defined."""
    global _namespace
    with _state_lock:
        _namespace = _fresh_namespace()


def request_stop() -> None:
    """Ask the running code to stop at its next bytecode boundary."""
    _stop_flag.set()

    thread_id = _active_thread_id
    if thread_id is None or not _use_async_exc or _set_async_exc is None:
        return  # The trace hook will pick the flag up instead.

    import ctypes

    try:
        _set_async_exc(ctypes.c_ulong(thread_id), ctypes.py_object(KeyboardInterrupt))
    except Exception:  # noqa: BLE001
        pass


def _make_tracer():
    """Cooperative interrupt.

    CPython cannot kill a thread outright, so a trace hook raises
    KeyboardInterrupt in the user's code the moment the stop flag is set.
    """

    def tracer(frame, event, arg):
        if _stop_flag.is_set():
            raise KeyboardInterrupt("execution stopped")
        return tracer

    return tracer


def _format_exception(exc: BaseException, source_name: str) -> str:
    """Traceback without the engine's own frames, so errors point at user code."""
    tb = exc.__traceback__
    # Drop frames belonging to this module.
    while tb is not None and tb.tb_frame.f_globals.get("__name__") == __name__:
        tb = tb.tb_next
    lines = traceback.format_exception(type(exc), exc, tb)
    text = "".join(lines)
    return text.replace('File "<string>"', f'File "{source_name}"')


def _split_last_expression(source: str, filename: str):
    """Compile REPL-style: run the body, then echo the value of a final expression."""
    tree = ast.parse(source, filename=filename, mode="exec")
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        body = ast.Module(body=tree.body[:-1], type_ignores=tree.type_ignores)
        tail = ast.Expression(body=tree.body[-1].value)
        ast.fix_missing_locations(body)
        ast.fix_missing_locations(tail)
        return (
            compile(body, filename, "exec"),
            compile(tail, filename, "eval"),
        )
    return compile(tree, filename, "exec"), None


def run_source(source: str, source_name: str = "<console>", echo_result: bool = True) -> str:
    """Execute a chunk of code. Returns "ok", "error" or "stopped"."""
    global _run_counter, _active_thread_id

    if _sink is None:
        raise RuntimeError("pycmd_runtime.configure() has not been called")

    with _state_lock:
        namespace = _namespace
        _run_counter += 1
        run_id = _run_counter

    _stop_flag.clear()
    started = time.monotonic()
    status = "ok"

    thread_id = threading.get_ident()
    _active_thread_id = thread_id
    if not _use_async_exc:
        sys.settrace(_make_tracer())
        threading.settrace(_make_tracer())
    try:
        try:
            body, tail = _split_last_expression(source, source_name)
        except SyntaxError as exc:
            sys.stderr.write(_format_exception(exc, source_name))
            return "error"

        try:
            exec(body, namespace)
            if tail is not None:
                value = eval(tail, namespace)
                if value is not None:
                    namespace["_"] = value
                    if echo_result:
                        try:
                            sys.stdout.write(repr(value) + "\n")
                        except Exception:  # repr can raise; never let it kill the run
                            sys.stdout.write("<unprintable object>\n")
        except KeyboardInterrupt:
            status = "stopped"
            sys.stderr.write("\nKeyboardInterrupt: execution stopped\n")
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
            if code not in (0, None):
                status = "error"
                sys.stderr.write(f"SystemExit: {code}\n")
        except BaseException as exc:  # noqa: BLE001 - the console reports everything
            status = "error"
            sys.stderr.write(_format_exception(exc, source_name))
    finally:
        if not _use_async_exc:
            sys.settrace(None)
            threading.settrace(None)
        # A stop requested in the last instants of a run must not land on the
        # next one.
        _clear_pending_async_exc(thread_id)
        _active_thread_id = None
        _stop_flag.clear()
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass

    _sink.onFinished(run_id, status, int((time.monotonic() - started) * 1000))
    return status


def run_file(path: str, args=None) -> str:
    """Execute a file as ``__main__`` with its directory on sys.path."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
    except OSError as exc:
        sys.stderr.write(f"cannot open {path}: {exc}\n")
        return "error"

    directory = os.path.dirname(os.path.abspath(path))
    previous_argv = sys.argv
    added_path = False
    if directory and directory not in sys.path:
        sys.path.insert(0, directory)
        added_path = True

    sys.argv = [path] + [str(a) for a in (args or [])]
    reset_namespace()
    with _state_lock:
        _namespace["__file__"] = path
    try:
        return run_source(source, source_name=os.path.basename(path), echo_result=False)
    finally:
        sys.argv = previous_argv
        if added_path:
            try:
                sys.path.remove(directory)
            except ValueError:
                pass


# ---------------------------------------------------------------------------
# Editor / console helpers
# ---------------------------------------------------------------------------

_KEYWORDS = sorted(
    set(dir(builtins))
    | {
        "and", "as", "assert", "async", "await", "break", "class", "continue",
        "def", "del", "elif", "else", "except", "finally", "for", "from",
        "global", "if", "import", "in", "is", "lambda", "nonlocal", "not", "or",
        "pass", "raise", "return", "try", "while", "with", "yield",
    }
)


def completions(prefix: str, limit: int = 40):
    """Name completions for the editor's suggestion bar."""
    if not prefix:
        return []

    if "." in prefix:
        head, _, tail = prefix.rpartition(".")
        try:
            obj = eval(head, dict(_namespace))  # noqa: S307 - user's own namespace
        except Exception:
            return []
        names = [n for n in dir(obj) if n.startswith(tail) and not n.startswith("__")]
        return [f"{head}.{n}" for n in sorted(names)[:limit]]

    pool = set(_KEYWORDS) | set(_namespace)
    return sorted(n for n in pool if n.startswith(prefix) and not n.startswith("__"))[:limit]


def runtime_info() -> dict:
    """Everything the About card shows."""
    return {
        "version": sys.version.split()[0],
        "full_version": sys.version.replace("\n", " "),
        "implementation": sys.implementation.name,
        "platform": sys.platform,
        "executable": sys.executable or "(embedded)",
        "path": list(sys.path),
        "cwd": os.getcwd(),
        "interrupt": "async-exc" if _use_async_exc else "trace-hook",
    }
