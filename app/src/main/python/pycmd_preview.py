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


def render(path: str) -> dict:
    """Returns the HTML to show, and the folder relative links resolve against."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            source = handle.read()
    except OSError as error:
        return {"ok": False, "error": f"cannot open {path}: {error}"}

    extension = os.path.splitext(path)[1].lower()
    name = os.path.basename(path)
    folder = os.path.dirname(os.path.abspath(path))

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
    elif extension == ".svg":
        body = _page(name, source)
    else:
        body = _page(name, f"<pre><code>{html_escape.escape(source)}</code></pre>")

    return {"ok": True, "html": body, "base": folder + os.sep, "name": name}


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
