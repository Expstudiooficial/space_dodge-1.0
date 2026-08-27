"""Execution engine that the Kotlin layer drives.

Everything the user types goes through :func:`run_source`. Output is pushed to a
Java/Kotlin sink object as it is produced, so the console can stream instead of
waiting for the script to finish.

Output is *channelled*. `sys.stdout` is a single global object, but a server
running on its own thread needs its output to land in its own console rather
than the main one, so every write is tagged with the channel registered for the
writing thread. Threads with no registration write to ``"console"``.
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
    "run_any",
    "answer_fix",
    "language_catalogue",
    "language_for",
    "template_for",
    "register_channel",
    "unregister_channel",
    "current_channel",
    "interrupt_thread",
    "emit",
]

CONSOLE = "console"

# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

_channels: dict[int, str] = {}
_channel_lock = threading.RLock()


def register_channel(channel: str) -> None:
    """Route this thread's output to `channel`. Called from the thread itself."""
    with _channel_lock:
        _channels[threading.get_ident()] = channel


def unregister_channel() -> None:
    with _channel_lock:
        _channels.pop(threading.get_ident(), None)


def current_channel() -> str:
    with _channel_lock:
        return _channels.get(threading.get_ident(), CONSOLE)


# Someone who wants a copy of everything written to a channel. The servers
# module uses it to keep each server's own log, so that reopening a server's
# console shows what the script printed rather than only the two lines the
# server module wrote itself.
_observer = None


def set_observer(observer) -> None:
    """Registers one callable, `observer(stream, text, channel)`."""
    global _observer

    _observer = observer if callable(observer) else None


def _observe(stream: str, text: str, channel: str) -> None:
    if _observer is None:
        return
    try:
        _observer(stream, text, channel)
    except Exception:  # noqa: BLE001 - an observer must never break output
        pass


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
            channel = current_channel()
            self._sink.onOutput(self._name, text, channel)
            _observe(self._name, text, channel)
        return len(text)

    def flush(self) -> None:  # pragma: no cover - nothing is buffered
        return None


class _SinkInput(io.TextIOBase):
    """stdin backed by the console's input box.

    ``readline`` blocks the calling thread until the UI supplies a line, which
    is exactly the semantics ``input()`` expects. Each channel has its own
    input queue on the Kotlin side, so a server prompting for input does not
    steal what the user typed into the main console.
    """

    def __init__(self, sink) -> None:
        self._sink = sink
        self._buffers: dict[int, str] = {}

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
        key = threading.get_ident()
        buffered = self._buffers.get(key, "")
        if not buffered:
            line = self._sink.onReadLine(current_channel())
            if line is None:
                # The only reason the sink refuses a line is that the run was
                # stopped, so report it the same way any other stop is.
                raise KeyboardInterrupt("execution stopped")
            buffered = line
        if size is not None and size >= 0:
            chunk, rest = buffered[:size], buffered[size:]
        else:
            chunk, rest = buffered, ""
        if rest:
            self._buffers[key] = rest
        else:
            self._buffers.pop(key, None)
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

# The same flag as a bare boolean.
#
# The trace-hook fallback reads it from inside a trace function, and
# `Event.is_set` is written in Python: calling it there means a `call` event
# fires from inside the tracer, on every traced line, for the whole run. A
# module global costs one dict lookup and cannot re-enter anything.
_stop_requested = False
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
        # BaseException, not KeyboardInterrupt: the interrupt is delivered at an
        # arbitrary bytecode boundary and must not escape into threading's
        # excepthook, which would print a traceback to stderr on every startup.
        try:
            while not keep_spinning.is_set():
                pass
        except BaseException:  # noqa: BLE001
            pass

    thread = threading.Thread(target=spin, name="pycmd-probe", daemon=True)

    # Belt and braces: if the exception still lands outside spin()'s try - during
    # thread teardown, say - swallow it here rather than let it be reported.
    previous_hook = threading.excepthook

    def quiet_hook(args):
        if args.thread is thread:
            return
        previous_hook(args)

    threading.excepthook = quiet_hook
    try:
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
    finally:
        threading.excepthook = previous_hook


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


def interrupt_thread(thread_id: int, exception=KeyboardInterrupt) -> bool:
    """Raise `exception` inside another thread. Used by the server kill switch.

    Returns False when the fast path is unavailable, in which case the caller
    has to fall back on closing whatever the thread is blocked on.
    """
    if not _use_async_exc or _set_async_exc is None or thread_id is None:
        return False

    import ctypes

    try:
        raised = _set_async_exc(ctypes.c_ulong(thread_id), ctypes.py_object(exception))
        return raised > 0
    except Exception:  # noqa: BLE001
        return False


class _DiscardedInterrupt(BaseException):
    """A stop that arrived too late to belong to any run."""


def _clear_pending_async_exc(thread_id: int) -> None:
    """Consume an interrupt requested after the run had already finished.

    Passing NULL to ``PyThreadState_SetAsyncExc`` looks like the way to cancel
    a queued interrupt, and it does drop the thread's exception - but the
    interpreter only clears its own "an async exception is waiting" signal when
    one is actually *delivered*. A NULL therefore leaves that signal set for
    the life of the process, and the eval loop keeps taking the slow path it
    guards. With a trace function installed the two together stop a thread
    making progress at all, which is how this was found.

    Delivering a harmless exception instead clears both. It lands on the next
    instruction that checks, which is why the loop below exists: it gives the
    interpreter a check point, and then swallows what it asked for.
    """
    if not _use_async_exc or _set_async_exc is None or thread_id is None:
        return
    import ctypes

    try:
        queued = _set_async_exc(
            ctypes.c_ulong(thread_id), ctypes.py_object(_DiscardedInterrupt)
        )
    except _DiscardedInterrupt:
        # Usually it lands right here, on the return from the C call, and
        # there is nothing further to do.
        return
    except Exception:  # noqa: BLE001
        return

    if queued <= 0:
        return
    try:
        for _ in range(64):
            _check_point()
    except _DiscardedInterrupt:
        pass


def _check_point() -> None:
    """A call, which is where the interpreter looks for a pending exception."""


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


def emit(stream: str, text: str, channel: str = CONSOLE) -> None:
    """Push a line to a channel without going through Python's streams."""
    if _sink is not None and text:
        _sink.onOutput(stream, text, channel)
        _observe(stream, text, channel)


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
    """Ask the console's running code to stop at its next bytecode boundary."""
    global _stop_requested

    _stop_requested = True
    _stop_flag.set()

    thread_id = _active_thread_id
    if thread_id is None:
        return
    if not interrupt_thread(thread_id, KeyboardInterrupt):
        pass  # The trace hook will pick the flag up instead.


def _make_tracer():
    """Cooperative interrupt used when async exceptions are unavailable."""

    def tracer(frame, event, arg):
        if _stop_requested:
            raise KeyboardInterrupt("execution stopped")
        return tracer

    return tracer


def _offer_fix(report: str, source_name: str) -> None:
    """Lets the doctor look at an error and offer to fix it.

    Never raises and never acts: the most it does is print an offer, which the
    user answers with yes or no. An error that gets quietly "fixed" is an error
    nobody learns from.
    """
    try:
        import pycmd_doctor

        offer = pycmd_doctor.diagnose(report, {
            "kind": "console",
            "channel": current_channel(),
            "path": source_name,
            "directory": os.path.dirname(source_name) if os.path.sep in source_name else "",
        })
        if offer is not None:
            sys.stdout.write(pycmd_doctor.describe(offer))
    except Exception:  # noqa: BLE001
        pass


def answer_fix(channel: str, text: str) -> dict:
    """Applies or dismisses whatever the doctor offered on `channel`.

    Returns immediately. A fix that takes real time - installing a package -
    runs on its own thread and reports through `emit`, so the thread the app
    called in on is free the whole time. It has to be: that same thread
    carries Stop and Kill.
    """
    try:
        import pycmd_doctor
    except Exception as exc:  # noqa: BLE001
        return {"handled": False, "error": str(exc)}

    def say(line: str) -> None:
        # emit(), not sys.stdout: this runs on a helper thread, and stdout is
        # bound to whichever channel *that* thread belongs to.
        emit("system", line, channel)

    try:
        result = pycmd_doctor.answer(channel, text, emit=say)
    except Exception as exc:  # noqa: BLE001
        return {"handled": False, "error": str(exc)}

    if result.get("handled") and result.get("done"):
        say(result.get("message", "") + "\n")
    elif not result.get("handled") and result.get("hint"):
        say(result["hint"] + "\n")
    return result


def _format_exception(exc: BaseException, source_name: str) -> str:
    """Traceback without the engine's own frames, so errors point at user code."""
    tb = exc.__traceback__
    # Drop frames belonging to this module.
    while tb is not None and tb.tb_frame.f_globals.get("__name__") == __name__:
        tb = tb.tb_next
    lines = traceback.format_exception(type(exc), exc, tb)
    text = "".join(lines)
    return text.replace('File "<string>"', f'File "{source_name}"')


def format_exception(exc: BaseException, source_name: str = "<script>") -> str:
    """Public wrapper so other modules report errors the same way."""
    return _format_exception(exc, source_name)


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
    global _run_counter, _active_thread_id, _stop_requested

    if _sink is None:
        raise RuntimeError("pycmd_runtime.configure() has not been called")

    with _state_lock:
        namespace = _namespace
        _run_counter += 1
        run_id = _run_counter

    _stop_requested = False
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
            report = _format_exception(exc, source_name)
            sys.stderr.write(report)
            _offer_fix(report, source_name)
    finally:
        if not _use_async_exc:
            sys.settrace(None)
            threading.settrace(None)
        # A stop requested in the last instants of a run must not land on the
        # next one. Nothing is queued unless one was asked for, so the common
        # path does not touch the interrupt machinery at all.
        if _stop_requested or _stop_flag.is_set():
            _clear_pending_async_exc(thread_id)
        _active_thread_id = None
        _stop_requested = False
        _stop_flag.clear()
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass

    _sink.onFinished(run_id, status, int((time.monotonic() - started) * 1000))
    return status


def run_any(path: str) -> str:
    """Runs a file with whichever engine its extension calls for.

    Python still goes through run_file so it keeps the console's namespace and
    the REPL behaviour. Anything else is handed to the language registry, which
    either runs it or explains why it cannot.
    """
    import os

    if _sink is None:
        raise RuntimeError("pycmd_runtime.configure() has not been called")

    if path.lower().endswith((".py", ".pyw")):
        return run_file(path)

    try:
        from pycmd_langs import registry
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"language support failed to load: {exc}\n")
        return "error"

    language = registry.for_path(path)
    name = os.path.basename(path)
    _sink.onOutput("system", f"Running {name} as {language['name']}\n", CONSOLE)

    started = time.monotonic()
    try:
        result = registry.run_file(path, stdout=sys.stdout, stdin=sys.stdin)
    except KeyboardInterrupt:
        sys.stderr.write("\nKeyboardInterrupt: execution stopped\n")
        return "stopped"
    except BaseException as exc:  # noqa: BLE001
        report = _format_exception(exc, name)
        sys.stderr.write(report)
        _offer_fix(report, path)
        return "error"

    millis = int((time.monotonic() - started) * 1000)
    if result.get("ok"):
        code = result.get("exit", 0)
        if code:
            sys.stderr.write(f"{language['name']} exited with status {code}\n")
            _sink.onFinished(0, "error", millis)
            return "error"
        _sink.onFinished(0, "ok", millis)
        return "ok"

    problem = result.get("error", "could not run this file")
    sys.stderr.write(problem + "\n")
    _offer_fix(problem, path)
    _sink.onFinished(0, "error", millis)
    return "error"


def language_catalogue(include_all: bool = True) -> list:
    """Every file type the new-file menu offers."""
    from pycmd_langs import registry

    return registry.catalogue(include_all)


def language_for(path: str) -> dict:
    from pycmd_langs import registry

    return registry.for_path(path)


def template_for(name: str) -> str:
    from pycmd_langs import registry

    return registry.template_for(name)


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


def exec_isolated(path: str, args=None, channel: str = CONSOLE) -> None:
    """Run a file in a fresh namespace, without touching the console's state.

    Servers use this: a background script must not reset the variables the user
    is working with in the console, and its traceback belongs in its own log.
    """
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()

    module = types.ModuleType("__main__")
    namespace = module.__dict__
    namespace["__builtins__"] = builtins
    namespace["__name__"] = "__main__"
    namespace["__file__"] = path

    directory = os.path.dirname(os.path.abspath(path))
    added_path = False
    if directory and directory not in sys.path:
        sys.path.insert(0, directory)
        added_path = True

    previous_argv = sys.argv
    sys.argv = [path] + [str(a) for a in (args or [])]
    try:
        code = compile(source, os.path.basename(path), "exec")
        exec(code, namespace)
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
