"""Turns a previewable file into a page the app can show.

HTML is shown as written. Markdown is converted here, by hand: the two
libraries everyone reaches for are pure Python but 40-odd files each, and what
a phone-sized preview needs is headings, lists, code, links, emphasis, quotes,
tables and rules - which fits in one file with no dependency and no download.

CSS gets a demo page, because a stylesheet on its own renders as nothing at
all and "the preview is blank" is a worse answer than showing it applied to
something.
"""

from __future__ import annotations

import html as html_escape
import os
import re

PAGE_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 18px 16px 40px;
  background: #0B0F14;
  color: #DCE3EC;
  font: 15px/1.65 -apple-system, "Segoe UI", Roboto, sans-serif;
  overflow-wrap: break-word;
}
h1, h2, h3, h4 { line-height: 1.25; margin: 1.4em 0 0.5em; color: #F1F5FA; }
h1 { font-size: 1.7em; border-bottom: 1px solid #223041; padding-bottom: 0.3em; }
h2 { font-size: 1.35em; border-bottom: 1px solid #1B2532; padding-bottom: 0.25em; }
h3 { font-size: 1.13em; }
p, ul, ol, blockquote, pre, table { margin: 0.75em 0; }
a { color: #6FB3FF; }
code {
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: 0.9em;
  background: #151C26;
  border: 1px solid #223041;
  border-radius: 5px;
  padding: 1px 5px;
}
pre {
  background: #10161F;
  border: 1px solid #223041;
  border-radius: 10px;
  padding: 12px 14px;
  overflow-x: auto;
}
pre code { background: none; border: 0; padding: 0; font-size: 0.88em; }
blockquote {
  border-left: 3px solid #2E7DD1;
  margin-left: 0;
  padding: 2px 0 2px 14px;
  color: #9BA9BB;
}
hr { border: 0; border-top: 1px solid #223041; margin: 1.6em 0; }
table { border-collapse: collapse; width: 100%; display: block; overflow-x: auto; }
th, td { border: 1px solid #223041; padding: 7px 10px; text-align: left; }
th { background: #151C26; }
img { max-width: 100%; height: auto; border-radius: 8px; }
ul, ol { padding-left: 1.4em; }
li { margin: 0.25em 0; }
input[type=checkbox] { margin-right: 6px; }
.pycmd-art {
  display: flex; justify-content: center; padding: 12px;
  background:
    linear-gradient(45deg, #151C26 25%, transparent 25%, transparent 75%, #151C26 75%),
    linear-gradient(45deg, #151C26 25%, #0F141C 25%, #0F141C 75%, #151C26 75%);
  background-size: 24px 24px;
  background-position: 0 0, 12px 12px;
  border: 1px solid #223041; border-radius: 10px;
}
.pycmd-art svg, .pycmd-art img { max-width: 100%; height: auto; }
.pycmd-note {
  background: #151C26;
  border: 1px solid #223041;
  border-radius: 10px;
  padding: 12px 14px;
  color: #9BA9BB;
  font-size: 0.9em;
}
"""

CSS_DEMO_BODY = """
<h1>Heading one</h1>
<p>A paragraph of body text, so you can see what the stylesheet does to it.
It runs long enough to wrap onto a second line on a phone.</p>
<h2>Heading two</h2>
<ul><li>First item</li><li>Second item</li></ul>
<p><a href="#">A link</a>, some <strong>bold</strong> and some <em>italic</em>.</p>
<blockquote>A block quote.</blockquote>
<pre><code>a code block</code></pre>
<table><tr><th>Name</th><th>Value</th></tr><tr><td>one</td><td>1</td></tr></table>
<p><button>A button</button> <input placeholder="An input"></p>
"""


# Everything the preview can show, which is what decides whether a file gets a
# preview button. Anything not here is a file you edit, not a file you view.
EXTENSIONS = (
    ".html", ".htm", ".md", ".markdown", ".css", ".svg", ".js", ".mjs",
    ".json", ".csv", ".tsv", ".xml", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".conf", ".txt", ".log", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".bmp", ".ico",
)

IMAGES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico")


def can_preview(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in EXTENSIONS


def extensions() -> str:
    """The list, for the app's file list to key its preview button on."""
    return ",".join(EXTENSIONS)


def render(path: str) -> dict:
    """Returns the HTML to show, and the folder relative links resolve against."""
    extension = os.path.splitext(path)[1].lower()
    name = os.path.basename(path)
    folder = os.path.dirname(os.path.abspath(path))

    if extension in IMAGES:
        # Never read as text, and never inlined: the server next door can
        # serve the real bytes.
        try:
            size = os.path.getsize(path)
        except OSError as error:
            return {"ok": False, "error": f"cannot open {path}: {error}"}
        return {
            "ok": True,
            "html": _page(name, _image_body(name, size)),
            "base": folder + os.sep,
            "name": name,
        }

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            source = handle.read()
    except OSError as error:
        return {"ok": False, "error": f"cannot open {path}: {error}"}

    if extension in (".html", ".htm"):
        body = source
    elif extension in (".md", ".markdown"):
        body = _page(name, markdown_to_html(source))
    elif extension == ".css":
        body = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{html_escape.escape(name)}</title>"
            f"<link rel='stylesheet' href='{html_escape.escape(name)}'>"
            "</head><body>" + CSS_DEMO_BODY + "</body></html>"
        )
    elif extension in (".js", ".mjs"):
        body = _script_page(name)
    elif extension == ".json":
        body = _page(name, _json_body(source))
    elif extension in (".csv", ".tsv"):
        body = _page(name, _table_body(source, "\t" if extension == ".tsv" else ","))
    elif extension == ".svg":
        body = _page(name, f"<div class='pycmd-art'>{source}</div>")
    else:
        body = _page(name, f"<pre><code>{html_escape.escape(source)}</code></pre>")

    return {"ok": True, "html": body, "base": folder + os.sep, "name": name}


def _image_body(name: str, size: int) -> str:
    escaped = html_escape.escape(name)
    return (
        f"<div class='pycmd-art'><img src='{escaped}' alt='{escaped}'></div>"
        f"<p class='pycmd-note'>{escaped} - {size:,} bytes</p>"
    )


def _json_body(source: str) -> str:
    """Pretty-printed if it parses, and the parse error if it does not."""
    import json

    try:
        value = json.loads(source)
    except ValueError as error:
        return (
            "<div class='pycmd-note'>This is not valid JSON: "
            f"{html_escape.escape(str(error))}</div>"
            f"<pre><code>{html_escape.escape(source)}</code></pre>"
        )

    pretty = json.dumps(value, indent=2, ensure_ascii=False)
    if isinstance(value, dict):
        shape = f"an object with {len(value)} key{'' if len(value) == 1 else 's'}"
    elif isinstance(value, list):
        shape = f"an array of {len(value)}"
    else:
        shape = type(value).__name__
    return (
        f"<div class='pycmd-note'>Valid JSON - {shape}</div>"
        f"<pre><code>{html_escape.escape(pretty)}</code></pre>"
    )


def _table_body(source: str, separator: str) -> str:
    """Separated values as a table, which is the whole point of previewing one."""
    import csv
    import io as _io

    rows = list(csv.reader(_io.StringIO(source), delimiter=separator))
    if not rows:
        return "<p class='pycmd-note'>Empty.</p>"

    header, body = rows[0], rows[1:]
    out = ["<table><thead><tr>"]
    out += [f"<th>{html_escape.escape(cell)}</th>" for cell in header]
    out.append("</tr></thead><tbody>")
    for row in body[:500]:
        out.append("<tr>" + "".join(
            f"<td>{html_escape.escape(cell)}</td>" for cell in row
        ) + "</tr>")
    out.append("</tbody></table>")
    if len(body) > 500:
        out.append(f"<p class='pycmd-note'>Showing 500 of {len(body)} rows.</p>")
    else:
        out.append(f"<p class='pycmd-note'>{len(body)} rows, {len(header)} columns.</p>")
    return "".join(out)


def _script_page(name: str) -> str:
    """Runs a script in a page and shows what it logged.

    A .js file has no appearance of its own, so previewing one means running
    it: the page loads the script exactly as a browser would, and everything
    it logs or throws lands in a console underneath. Anything it draws into
    the document shows up above that.
    """
    escaped = html_escape.escape(name)
    return f"""<!doctype html>
<html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>{escaped}</title>{PAGE_CSS}
<style>
  #pycmd-console {{
    background: #10161F; border: 1px solid #223041; border-radius: 10px;
    padding: 10px 12px; font-family: ui-monospace, Menlo, monospace;
    font-size: 13px; white-space: pre-wrap; min-height: 60px;
  }}
  #pycmd-console .err {{ color: #FF8A8A; }}
  #pycmd-console .warn {{ color: #F5C77E; }}
  #pycmd-stage:empty::after {{
    content: 'Anything the script adds to the page appears here.';
    color: #64748B; font-size: 13px;
  }}
</style>
</head>
<body>
<h1>{escaped}</h1>
<div id='pycmd-stage'></div>
<h2>Console</h2>
<div id='pycmd-console'></div>
<script>
(function () {{
  var out = document.getElementById('pycmd-console');
  function write(text, kind) {{
    var line = document.createElement('div');
    if (kind) line.className = kind;
    line.textContent = text;
    out.appendChild(line);
  }}
  function show(args) {{
    return Array.prototype.map.call(args, function (value) {{
      if (typeof value === 'string') return value;
      try {{ return JSON.stringify(value); }} catch (e) {{ return String(value); }}
    }}).join(' ');
  }}
  var real = window.console;
  window.console = {{
    log: function () {{ write(show(arguments)); real.log.apply(real, arguments); }},
    info: function () {{ write(show(arguments)); real.info.apply(real, arguments); }},
    debug: function () {{ write(show(arguments)); real.debug.apply(real, arguments); }},
    warn: function () {{ write(show(arguments), 'warn'); real.warn.apply(real, arguments); }},
    error: function () {{ write(show(arguments), 'err'); real.error.apply(real, arguments); }},
    table: function (v) {{ write(show([v])); }},
    trace: function () {{ write(show(arguments), 'warn'); }},
    group: function () {{ write(show(arguments)); }},
    groupEnd: function () {{}},
    time: function () {{}},
    timeEnd: function () {{}}
  }};
  window.addEventListener('error', function (event) {{
    write((event.error && event.error.stack) || event.message, 'err');
  }});
  window.addEventListener('unhandledrejection', function (event) {{
    write('Unhandled promise rejection: ' + event.reason, 'err');
  }});
}})();
</script>
<script src='{escaped}'></script>
</body></html>"""


def render_text(text: str, name: str = "document.md") -> dict:
    """Renders text the app already has in memory - a doc shipped in assets.

    Same renderer as a file preview, so the plugin guide reads on the phone
    exactly as it does on GitHub.
    """
    extension = os.path.splitext(name)[1].lower()
    if extension in (".html", ".htm"):
        body = text
    elif extension in (".md", ".markdown", ""):
        body = _page(name, markdown_to_html(text))
    else:
        body = _page(name, f"<pre><code>{html_escape.escape(text)}</code></pre>")
    return {"ok": True, "html": body, "base": "", "name": name}


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html_escape.escape(title)}</title><style>{PAGE_CSS}</style>"
        f"</head><body>{body}</body></html>"
    )


# ------------------------------------------------------------------ markdown

INLINE_CODE = re.compile(r"`([^`]+)`")
IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)|(?<![_\w])_([^_\n]+)_(?!_)")
STRIKE = re.compile(r"~~([^~]+)~~")
AUTOLINK = re.compile(r"(?<![\"'(=])\bhttps?://[^\s<>\"')]+")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
UNORDERED = re.compile(r"^(\s*)[-*+]\s+(.*)$")
ORDERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
TASK = re.compile(r"^\[([ xX])\]\s+(.*)$")
RULE = re.compile(r"^(\s*)([-*_])(\s*\2){2,}\s*$")
TABLE_DIVIDER = re.compile(r"^\s*\|?[\s:-]+\|[\s|:-]*$")


def markdown_to_html(source: str) -> str:
    lines = source.replace("\r\n", "\n").split("\n")
    out = []
    index = 0
    total = len(lines)
    list_stack = []          # ("ul"|"ol", indent)

    def close_lists(to_indent=-1):
        while list_stack and list_stack[-1][1] > to_indent:
            out.append(f"</{list_stack.pop()[0]}>")
            # A nested list lives inside the item above it, so the item that
            # was left open when it started is closed now.
            if list_stack:
                out.append("</li>")

    while index < total:
        line = lines[index]

        # A fenced code block, kept verbatim.
        if line.strip().startswith("```") or line.strip().startswith("~~~"):
            fence = line.strip()[:3]
            language = line.strip()[3:].strip()
            index += 1
            body = []
            while index < total and not lines[index].strip().startswith(fence):
                body.append(lines[index])
                index += 1
            index += 1
            close_lists()
            classes = f' class="language-{html_escape.escape(language)}"' if language else ""
            out.append(f"<pre><code{classes}>" +
                       html_escape.escape("\n".join(body)) + "</code></pre>")
            continue

        if not line.strip():
            close_lists()
            index += 1
            continue

        if RULE.match(line):
            close_lists()
            out.append("<hr>")
            index += 1
            continue

        heading = HEADING.match(line)
        if heading:
            close_lists()
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            index += 1
            continue

        # A table needs its divider row on the next line to count as one.
        if "|" in line and index + 1 < total and TABLE_DIVIDER.match(lines[index + 1]):
            close_lists()
            header = _cells(line)
            out.append("<table><thead><tr>" +
                       "".join(f"<th>{inline(cell)}</th>" for cell in header) +
                       "</tr></thead><tbody>")
            index += 2
            while index < total and "|" in lines[index] and lines[index].strip():
                out.append("<tr>" + "".join(
                    f"<td>{inline(cell)}</td>" for cell in _cells(lines[index])
                ) + "</tr>")
                index += 1
            out.append("</tbody></table>")
            continue

        if line.lstrip().startswith(">"):
            close_lists()
            quoted = []
            while index < total and lines[index].lstrip().startswith(">"):
                quoted.append(lines[index].lstrip()[1:].lstrip())
                index += 1
            out.append("<blockquote>" + markdown_to_html("\n".join(quoted)) + "</blockquote>")
            continue

        unordered = UNORDERED.match(line)
        ordered = ORDERED.match(line)
        if unordered or ordered:
            match = unordered or ordered
            indent = len(match.group(1))
            kind = "ul" if unordered else "ol"
            text = match.group(2) if unordered else match.group(3)

            close_lists(indent)
            if not list_stack or list_stack[-1][1] < indent:
                # Reopen the parent item so the nested list sits inside it.
                if list_stack and out and out[-1].endswith("</li>"):
                    out[-1] = out[-1][:-len("</li>")]
                list_stack.append((kind, indent))
                out.append(f"<{kind}>")
            elif list_stack[-1][0] != kind:
                out.append(f"</{list_stack.pop()[0]}>")
                list_stack.append((kind, indent))
                out.append(f"<{kind}>")

            task = TASK.match(text)
            if task:
                checked = " checked" if task.group(1).lower() == "x" else ""
                out.append(f'<li><input type="checkbox" disabled{checked}>'
                           f"{inline(task.group(2))}</li>")
            else:
                out.append(f"<li>{inline(text)}</li>")
            index += 1
            continue

        # A plain paragraph runs until a blank line or a block that starts one.
        paragraph = [line.strip()]
        index += 1
        while index < total and lines[index].strip() and not _starts_block(lines[index]):
            paragraph.append(lines[index].strip())
            index += 1
        close_lists()
        out.append("<p>" + inline(" ".join(paragraph)) + "</p>")

    close_lists()
    return "\n".join(out)


def _starts_block(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith("#") or stripped.startswith(">") or
        stripped.startswith("```") or stripped.startswith("~~~") or
        bool(UNORDERED.match(line)) or bool(ORDERED.match(line)) or bool(RULE.match(line))
    )


def _cells(line: str) -> list:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in body.split("|")]


def inline(text: str) -> str:
    """Escapes first, then puts the markup back - never the other way round."""
    placeholders = []

    def stash(html_text):
        placeholders.append(html_text)
        return f"\x00{len(placeholders) - 1}\x00"

    def code(match):
        return stash("<code>" + html_escape.escape(match.group(1)) + "</code>")

    text = INLINE_CODE.sub(code, text)
    text = html_escape.escape(text)

    text = IMAGE.sub(
        lambda m: f'<img src="{m.group(2)}" alt="{m.group(1)}">', text
    )
    text = LINK.sub(
        lambda m: f'<a href="{m.group(2)}" target="_blank">{m.group(1)}</a>', text
    )
    text = AUTOLINK.sub(lambda m: f'<a href="{m.group(0)}" target="_blank">{m.group(0)}</a>', text)
    text = BOLD.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", text)
    text = ITALIC.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", text)
    text = STRIKE.sub(lambda m: f"<del>{m.group(1)}</del>", text)
    text = text.replace("  \n", "<br>")

    for position, value in enumerate(placeholders):
        text = text.replace(f"\x00{position}\x00", value)
    return text


# --------------------------------------------------------------- serving it

# A page loaded from a `file://` URL is a crippled page: no modules, no fetch,
# no XHR, and a browser that treats every file as its own origin. Serving the
# folder over loopback for the length of the preview costs one thread and
# makes the preview an actual browser view of the actual site.

_server = None
_server_thread = None
_server_root = ""
_generated = ""

MAGIC_PATH = "/__pycmd_preview__"


def serve(path: str) -> dict:
    """Serves the file's folder on loopback and says what URL to open."""
    import http.server
    import socketserver
    import threading

    global _server, _server_thread, _server_root, _generated

    rendered = render(path)
    if not rendered.get("ok"):
        return rendered

    folder = os.path.dirname(os.path.abspath(path))
    name = os.path.basename(path)
    extension = os.path.splitext(path)[1].lower()

    # HTML is served as itself; anything else is served through the magic
    # path, which hands back the page this module generated.
    _generated = rendered["html"]

    if _server is not None and _server_root == folder:
        port = _server.server_address[1]
        return _url(port, name, extension, rendered)

    stop()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=folder, **kwargs)

        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] == MAGIC_PATH:
                body = _generated.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def end_headers(self):
            # A preview that shows a cached copy of the page you just edited
            # is worse than no preview.
            self.send_header("Cache-Control", "no-store, must-revalidate")
            super().end_headers()

        def log_message(self, format, *args):  # noqa: A002
            pass

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    try:
        _server = Server(("127.0.0.1", 0), Handler)
    except OSError as error:
        # No loopback socket: fall back to the inline page, which still shows
        # something even if its scripts will be limited.
        return dict(rendered, served=False, error=str(error))

    _server_root = folder
    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()
    return _url(_server.server_address[1], name, extension, rendered)


def _url(port: int, name: str, extension: str, rendered: dict) -> dict:
    import urllib.parse

    if extension in (".html", ".htm"):
        target = f"http://127.0.0.1:{port}/{urllib.parse.quote(name)}"
    else:
        target = f"http://127.0.0.1:{port}{MAGIC_PATH}"
    return dict(rendered, served=True, url=target, port=port)


def stop() -> None:
    """Shuts the preview server down. Called when the preview closes."""
    global _server, _server_thread, _server_root

    if _server is not None:
        try:
            _server.shutdown()
            _server.server_close()
        except Exception:  # noqa: BLE001
            pass
    _server = None
    _server_thread = None
    _server_root = ""
