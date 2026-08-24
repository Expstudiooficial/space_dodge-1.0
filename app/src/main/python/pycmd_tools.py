"""The plugin tools, implemented where the batteries already are.

Everything the Tools plugins do - JSON, encodings, hashes, regexes, workspace
search, HTTP - is one call into the standard library that is already on the
device. Doing it here rather than in Kotlin means Regex Lab tests a pattern
with the same ``re`` module the user's script will use, which is the only way
the tool is worth having.

One entry point, ``invoke``, takes a tool name and a JSON argument object and
returns a JSON result. Keeping the bridge to a single function keeps the
Kotlin side small, and JSON keeps the two languages from having to agree on
anything more complicated than text.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_SEARCH_BYTES = 2 * 1024 * 1024
MAX_RESULTS = 300
MAX_RESPONSE = 512 * 1024

SKIP_DIRECTORIES = {"__pycache__", ".git", "node_modules", ".venv"}
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".gz", ".pdf", ".so",
    ".apk", ".mp3", ".mp4", ".ttf", ".otf", ".woff", ".woff2", ".ico", ".bin",
}


def invoke(name: str, payload: str) -> str:
    """Runs one tool. Never raises: a failure comes back as ``ok: false``."""
    try:
        arguments = json.loads(payload) if payload else {}
    except ValueError as error:
        return json.dumps({"ok": False, "error": f"bad arguments: {error}"})

    handler = TOOLS.get(name)
    if handler is None:
        return json.dumps({"ok": False, "error": f"unknown tool {name}"})

    try:
        result = handler(arguments)
    except Exception as error:  # noqa: BLE001
        result = {"ok": False, "error": f"{type(error).__name__}: {error}"}

    try:
        return json.dumps(result)
    except (TypeError, ValueError) as error:
        return json.dumps({"ok": False, "error": f"result could not be encoded: {error}"})


# -------------------------------------------------------------------- JSON

def json_tool(arguments) -> dict:
    text = arguments.get("text", "")
    action = arguments.get("action", "format")
    sort_keys = bool(arguments.get("sort", False))

    if not text.strip():
        return {"ok": False, "error": "nothing to work on"}

    try:
        value = json.loads(text)
    except ValueError as error:
        line = getattr(error, "lineno", 0)
        column = getattr(error, "colno", 0)
        where = f" at line {line}, column {column}" if line else ""
        return {"ok": False, "error": f"{error.msg}{where}" if hasattr(error, "msg")
                else str(error), "line": line, "column": column}

    if action == "minify":
        return {"ok": True, "text": json.dumps(value, separators=(",", ":"),
                                               ensure_ascii=False)}
    if action == "python":
        return {"ok": True, "text": _as_python(value, 0)}
    if action == "keys":
        return {"ok": True, "text": "\n".join(_walk_keys(value, ""))}

    return {
        "ok": True,
        "text": json.dumps(value, indent=2, sort_keys=sort_keys, ensure_ascii=False),
        "summary": _describe(value),
    }


def _describe(value) -> str:
    if isinstance(value, dict):
        return f"object with {len(value)} key{'' if len(value) == 1 else 's'}"
    if isinstance(value, list):
        return f"array of {len(value)}"
    return type(value).__name__


def _walk_keys(value, prefix):
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            yield path
            yield from _walk_keys(item, path)
    elif isinstance(value, list) and value:
        yield from _walk_keys(value[0], f"{prefix}[]")


def _as_python(value, depth) -> str:
    """JSON is nearly Python; the three literals that differ are the point."""
    pad = "    " * (depth + 1)
    closing = "    " * depth
    if value is None:
        return "None"
    if value is True:
        return "True"
    if value is False:
        return "False"
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        items = [pad + _as_python(item, depth + 1) for item in value]
        return "[\n" + ",\n".join(items) + "\n" + closing + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [f"{pad}{key!r}: {_as_python(item, depth + 1)}" for key, item in value.items()]
        return "{\n" + ",\n".join(items) + "\n" + closing + "}"
    return repr(value)


# ------------------------------------------------------------------- text

def text_tool(arguments) -> dict:
    text = arguments.get("text", "")
    action = arguments.get("action", "base64_encode")

    try:
        if action == "base64_encode":
            return _ok(base64.b64encode(text.encode("utf-8")).decode("ascii"))
        if action == "base64_decode":
            return _ok(base64.b64decode(_pad_base64(text.strip())).decode("utf-8", "replace"))
        if action == "url_encode":
            return _ok(urllib.parse.quote(text, safe=""))
        if action == "url_decode":
            return _ok(urllib.parse.unquote(text))
        if action == "hex_encode":
            return _ok(text.encode("utf-8").hex())
        if action == "hex_decode":
            return _ok(bytes.fromhex(text.strip().replace(" ", "")).decode("utf-8", "replace"))
        if action in ("md5", "sha1", "sha256", "sha512"):
            digest = hashlib.new(action, text.encode("utf-8")).hexdigest()
            return _ok(digest)
        if action == "upper":
            return _ok(text.upper())
        if action == "lower":
            return _ok(text.lower())
        if action == "title":
            return _ok(text.title())
        if action == "snake":
            return _ok(_to_snake(text))
        if action == "camel":
            return _ok(_to_camel(text))
        if action == "kebab":
            return _ok(_to_snake(text).replace("_", "-"))
        if action == "rot13":
            return _ok(text.translate(_ROT13))
        if action == "reverse":
            return _ok(text[::-1])
        if action == "sort_lines":
            return _ok("\n".join(sorted(text.splitlines())))
        if action == "unique_lines":
            seen = []
            for line in text.splitlines():
                if line not in seen:
                    seen.append(line)
            return _ok("\n".join(seen))
        if action == "strip_blank":
            return _ok("\n".join(line for line in text.splitlines() if line.strip()))
        if action == "escape":
            return _ok(json.dumps(text)[1:-1])
        if action == "count":
            words = len(text.split())
            lines = len(text.splitlines()) or (1 if text else 0)
            return _ok(
                f"characters: {len(text)}\n"
                f"characters without spaces: {len(text.replace(' ', ''))}\n"
                f"words: {words}\n"
                f"lines: {lines}\n"
                f"bytes (utf-8): {len(text.encode('utf-8'))}"
            )
    except (binascii.Error, ValueError, UnicodeDecodeError) as error:
        return {"ok": False, "error": f"that is not valid input for this: {error}"}

    return {"ok": False, "error": f"unknown conversion {action}"}


_ROT13 = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "nopqrstuvwxyzabcdefghijklmNOPQRSTUVWXYZABCDEFGHIJKLM",
)


def _pad_base64(text: str) -> str:
    return text + "=" * (-len(text) % 4)


def _to_snake(text: str) -> str:
    spaced = re.sub(r"[\s\-]+", "_", text.strip())
    spaced = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", spaced)
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", spaced)
    return re.sub(r"_+", "_", spaced).lower()


def _to_camel(text: str) -> str:
    parts = [part for part in re.split(r"[\s_\-]+", text.strip()) if part]
    if not parts:
        return ""
    return parts[0].lower() + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _ok(text) -> dict:
    return {"ok": True, "text": text}


# ------------------------------------------------------------------ regex

def regex_tool(arguments) -> dict:
    pattern = arguments.get("pattern", "")
    text = arguments.get("text", "")
    replacement = arguments.get("replacement")

    flags = 0
    if arguments.get("ignore_case"):
        flags |= re.IGNORECASE
    if arguments.get("multiline"):
        flags |= re.MULTILINE
    if arguments.get("dotall"):
        flags |= re.DOTALL

    if not pattern:
        return {"ok": True, "matches": [], "count": 0, "text": ""}

    try:
        compiled = re.compile(pattern, flags)
    except re.error as error:
        return {"ok": False, "error": f"bad pattern: {error}"}

    matches = []
    for found in compiled.finditer(text):
        if len(matches) >= 200:
            break
        matches.append({
            "start": found.start(),
            "end": found.end(),
            "text": found.group(0),
            "groups": [g if g is not None else "" for g in found.groups()],
            "named": {k: (v or "") for k, v in (found.groupdict() or {}).items()},
        })

    result = {
        "ok": True,
        "matches": matches,
        "count": len(matches),
        "groups": compiled.groups,
        "names": list(compiled.groupindex.keys()),
    }
    if replacement is not None:
        try:
            result["substituted"] = compiled.sub(replacement, text)
        except re.error as error:
            result["substituted"] = f"bad replacement: {error}"
    return result


# ----------------------------------------------------------------- search

def search_tool(arguments) -> dict:
    root = arguments.get("root", "")
    query = arguments.get("query", "")
    if not query:
        return {"ok": True, "hits": [], "files": 0, "truncated": False}

    use_regex = bool(arguments.get("regex"))
    case_sensitive = bool(arguments.get("case_sensitive"))
    whole_word = bool(arguments.get("whole_word"))

    if use_regex:
        try:
            pattern = re.compile(query, 0 if case_sensitive else re.IGNORECASE)
        except re.error as error:
            return {"ok": False, "error": f"bad pattern: {error}"}
    else:
        escaped = re.escape(query)
        if whole_word:
            escaped = rf"\b{escaped}\b"
        pattern = re.compile(escaped, 0 if case_sensitive else re.IGNORECASE)

    hits = []
    searched = 0
    truncated = False

    for directory, folders, names in os.walk(root):
        folders[:] = [name for name in folders if name not in SKIP_DIRECTORIES]
        for name in sorted(names):
            if os.path.splitext(name)[1].lower() in BINARY_EXTENSIONS:
                continue
            path = os.path.join(directory, name)
            try:
                if os.path.getsize(path) > MAX_SEARCH_BYTES:
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    lines = handle.read().splitlines()
            except OSError:
                continue

            searched += 1
            for number, line in enumerate(lines, start=1):
                if pattern.search(line):
                    hits.append({
                        "path": path,
                        "name": os.path.relpath(path, root),
                        "line": number,
                        "text": line.strip()[:200],
                    })
                    if len(hits) >= MAX_RESULTS:
                        truncated = True
                        return {"ok": True, "hits": hits, "files": searched,
                                "truncated": truncated}

    return {"ok": True, "hits": hits, "files": searched, "truncated": truncated}


# ------------------------------------------------------------------- HTTP

def http_tool(arguments) -> dict:
    url = (arguments.get("url") or "").strip()
    method = (arguments.get("method") or "GET").upper()
    body = arguments.get("body") or ""
    header_text = arguments.get("headers") or ""
    timeout = float(arguments.get("timeout") or 20)

    if not url:
        return {"ok": False, "error": "no URL"}
    if "://" not in url:
        url = "http://" + url

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"ok": False, "error": f"{parsed.scheme}:// is not supported"}

    headers = {}
    for line in header_text.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip()] = value.strip()

    data = body.encode("utf-8") if body and method not in ("GET", "HEAD") else None
    if data is not None and not any(k.lower() == "content-type" for k in headers):
        headers["Content-Type"] = "application/json" if body.lstrip()[:1] in "{[" \
            else "text/plain; charset=utf-8"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_RESPONSE)
            return _response(response.status, response.reason, response.headers,
                             payload, started)
    except urllib.error.HTTPError as error:
        payload = error.read(MAX_RESPONSE)
        return _response(error.code, error.reason, error.headers, payload, started)
    except urllib.error.URLError as error:
        return {"ok": False, "error": f"could not reach it: {error.reason}"}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}


def _response(status, reason, headers, payload, started) -> dict:
    text = payload.decode("utf-8", "replace")
    content_type = ""
    header_lines = []
    for key, value in (headers.items() if headers else []):
        header_lines.append(f"{key}: {value}")
        if key.lower() == "content-type":
            content_type = value

    if "json" in content_type.lower():
        try:
            text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except ValueError:
            pass

    return {
        "ok": True,
        "status": status,
        "reason": reason or "",
        "headers": "\n".join(header_lines),
        "body": text,
        "bytes": len(payload),
        "millis": int((time.monotonic() - started) * 1000),
    }


TOOLS = {
    "json": json_tool,
    "text": text_tool,
    "regex": regex_tool,
    "search": search_tool,
    "http": http_tool,
}
