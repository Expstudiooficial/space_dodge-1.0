#!/usr/bin/env python3
"""Checks the Creator plugin: the catalogue, the compiler, and saving a file.

Two halves, and they are checked differently.

The catalogue and the compiler are `creator_blocks.py`, which knows nothing about the
app: it is imported directly here and driven with projects, and the source it
writes is compared against what a person would have typed. Python's own
compiler is then handed the result, which is the only check that really
matters for the Python blocks - a block editor whose output does not parse is
worse than no block editor.

The rest - the projects drawer, saving into the workspace, the console command
- is the plugin, so it is installed and loaded for real through the same
machinery the app uses, and its exports are called the way the panel calls
them.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREATOR = os.path.join(ROOT, "app", "src", "main", "assets", "plugins", "creator")
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))
sys.path.insert(0, CREATOR)

import creator_blocks as blocks  # noqa: E402
import pycmd_plugins as plugins  # noqa: E402
import pycmd_runtime  # noqa: E402

FAILURES = []
REAL = sys.__stdout__


def say(text=""):
    REAL.write(str(text) + "\n")
    REAL.flush()


def check(name, condition, detail=""):
    if condition:
        say(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        say(f"  FAIL  {name}  {detail}")


# ---------------------------------------------------------------------------
say("== the catalogue holds together ==")

check("there are enough blocks to be worth having", len(blocks.BY_ID) >= 300,
      len(blocks.BY_ID))
check("every language has some",
      all(len(rows) >= 15 for rows in blocks.BLOCKS.values()),
      {name: len(rows) for name, rows in blocks.BLOCKS.items()})

ids = [row["id"] for rows in blocks.BLOCKS.values() for row in rows]
check("no two blocks share an id", len(ids) == len(set(ids)),
      [i for i in ids if ids.count(i) > 1][:5])

check("every language in the list has blocks",
      all(row["id"] in blocks.BLOCKS for row in blocks.LANGUAGES),
      [row["id"] for row in blocks.LANGUAGES])

bad_slots = []
bad_placeholders = []
unused_slots = []
bad_choices = []
for language, rows in blocks.BLOCKS.items():
    for row in rows:
        names = {slot["name"] for slot in row["slots"]}
        if len(names) != len(row["slots"]):
            bad_slots.append(row["id"])
        wanted = set(blocks.PLACEHOLDER.findall(row["open"] or "")) | \
            set(blocks.PLACEHOLDER.findall(row["close"] or ""))
        if wanted - names:
            bad_placeholders.append((row["id"], sorted(wanted - names)))
        if names - wanted:
            unused_slots.append((row["id"], sorted(names - wanted)))
        for slot in row["slots"]:
            if slot["kind"] == "choice" and slot["default"] not in slot["options"]:
                bad_choices.append((row["id"], slot["name"]))

check("no block declares the same slot twice", not bad_slots, bad_slots[:5])
check("every @hole@ in a template has a slot behind it",
      not bad_placeholders, bad_placeholders[:5])
check("and every slot is used by its template", not unused_slots, unused_slots[:5])
check("every choice's default is one of its options", not bad_choices, bad_choices[:5])

no_close = [row["id"] for rows in blocks.BLOCKS.values() for row in rows
            if row["wrap"] and not row["close"] and not row["empty"]
            and row["id"].split(".")[0] not in ("html", "css", "md", "js")]
check("every Python container can be left empty without breaking",
      not no_close, no_close[:5])

say()
say("== the catalogue is served the way the panel asks for it ==")
everything = blocks.catalogue()
check("it can be asked for all of it", everything["ok"] and everything["count"] == len(ids),
      everything.get("count"))
one = blocks.catalogue("python")
check("or for one language", one["ok"] and len(one["groups"]) == 1, len(one["groups"]))
check("grouped into categories",
      len(one["groups"][0]["categories"]) >= 8, len(one["groups"][0]["categories"]))
check("a language that does not exist is refused",
      not blocks.catalogue("cobol")["ok"], blocks.catalogue("cobol"))

say()
say("== Python comes out as Python ==")
project = {
    "language": "python",
    "blocks": [
        {"block": "py.import", "values": {"module": "random"}},
        {"block": "py.blank"},
        {"block": "py.def", "values": {"name": "roll", "params": "sides"}, "children": [
            {"block": "py.random_int",
             "values": {"name": "value", "low": "1", "high": "sides"}},
            {"block": "py.return", "values": {"value": "value"}},
        ]},
        {"block": "py.blank"},
        {"block": "py.main_guard", "children": [
            {"block": "py.repeat", "values": {"var": "i", "times": "3"}, "children": [
                {"block": "py.print_value", "values": {"value": "roll(6)"}},
            ]},
        ]},
    ],
}
built = blocks.compile_project(project)
check("it builds", built["ok"] and not built["problems"], built.get("problems"))
expected = (
    "import random\n"
    "\n"
    "def roll(sides):\n"
    "    value = random.randint(1, sides)\n"
    "    return value\n"
    "\n"
    'if __name__ == "__main__":\n'
    "    for i in range(3):\n"
    "        print(roll(6))\n"
)
check("and it is exactly the code somebody would have typed",
      built["code"] == expected, repr(built["code"]))
try:
    compile(built["code"], "built.py", "exec")
    parsed = True
except SyntaxError as error:
    parsed = False
    say(f"        {error}")
check("Python itself accepts it", parsed)

say()
say("== an empty container still writes something that runs ==")
empty = blocks.compile_project({
    "language": "python",
    "blocks": [{"block": "py.if", "values": {"condition": "True"}}],
})
check("an if with nothing in it gets a pass", empty["code"] == "if True:\n    pass\n",
      repr(empty["code"]))
try:
    compile(empty["code"], "built.py", "exec")
    empty_parsed = True
except SyntaxError:
    empty_parsed = False
check("and it parses", empty_parsed)

say()
say("== every Python block on its own produces valid syntax ==")
# A handful of blocks are halves of something: `elif` needs an `if` before it,
# `return` needs to be inside a function, `try` needs an `except` after it.
# Each is checked inside the smallest thing that makes it legal.
#   (what goes before, how far to indent the block, what goes after)
AROUND = {
    "py.elif": ("if False:\n    pass\n", 0, ""),
    "py.else": ("if False:\n    pass\n", 0, ""),
    "py.except": ("try:\n    pass\n", 0, ""),
    "py.finally": ("try:\n    pass\n", 0, ""),
    "py.try": ("", 0, "except Exception:\n    pass\n"),
    "py.flask_route": ("", 0, "def view():\n    pass\n"),
    "py.return": ("def f():\n", 1, ""),
    "py.return_none": ("def f():\n", 1, ""),
    "py.global": ("def f():\n", 1, ""),
    "py.break": ("while True:\n", 1, ""),
    "py.continue": ("while True:\n", 1, ""),
    "py.init": ("class C:\n", 1, ""),
    "py.method": ("class C:\n", 1, ""),
    "py.method_args": ("class C:\n", 1, ""),
    "py.set_attribute": ("class C:\n    def f(self):\n", 2, ""),
    "py.get_attribute": ("class C:\n    def f(self):\n", 2, ""),
}

broken = []
for row in blocks.BLOCKS["python"]:
    node = {"block": row["id"], "values": {}}
    if row["wrap"]:
        node["children"] = [{"block": "py.pass", "values": {}}]
    code = blocks.compile_project({"language": "python", "blocks": [node]})["code"]
    before, depth, after = AROUND.get(row["id"], ("", 0, ""))
    if depth:
        pad = "    " * depth
        code = "".join((pad + line + "\n") if line.strip() else "\n"
                       for line in code.split("\n")[:-1])
    code = before + code + after
    try:
        compile(code, row["id"], "exec")
    except SyntaxError as error:
        broken.append((row["id"], str(error)))
check(f"all {len(blocks.BLOCKS['python'])} of them", not broken, broken[:6])

say()
say("== the other four languages ==")
html = blocks.compile_project({
    "language": "html",
    "blocks": [
        {"block": "html.doctype"},
        {"block": "html.page", "values": {"lang": "en"}, "children": [
            {"block": "html.body", "children": [
                {"block": "html.h1", "values": {"text": "Hello"}},
            ]},
        ]},
    ],
})
check("HTML nests and closes its tags",
      html["code"] == '<!doctype html>\n<html lang="en">\n  <body>\n'
                      "    <h1>Hello</h1>\n  </body>\n</html>\n",
      repr(html["code"]))

css = blocks.compile_project({
    "language": "css",
    "blocks": [
        {"block": "css.media", "values": {"width": "600"}, "children": [
            {"block": "css.class", "values": {"name": "card"}, "children": [
                {"block": "css.padding", "values": {"value": "10px"}},
            ]},
        ]},
    ],
})
check("CSS keeps its at-rule's single @",
      css["code"] == "@media (max-width: 600px) {\n  .card {\n    padding: 10px;\n  }\n}\n",
      repr(css["code"]))

js = blocks.compile_project({
    "language": "javascript",
    "blocks": [
        {"block": "js.function", "values": {"name": "greet", "params": "name"},
         "children": [{"block": "js.log_value", "values": {"value": "name"}}]},
    ],
})
check("JavaScript closes its braces",
      js["code"] == "function greet(name) {\n  console.log(name);\n}\n", repr(js["code"]))

md = blocks.compile_project({
    "language": "markdown",
    "blocks": [
        {"block": "md.h1", "values": {"text": "Notes"}},
        {"block": "md.blank"},
        {"block": "md.bullet", "values": {"text": "one"}},
    ],
})
check("Markdown does not indent anything",
      md["code"] == "# Notes\n\n- one\n", repr(md["code"]))

say()
say("== what somebody types into a hole cannot break the line ==")
quoted = blocks.compile_project({
    "language": "python",
    "blocks": [{"block": "py.print", "values": {"text": 'he said "no" \\ then left'}}],
})
check("quotes and backslashes are escaped",
      quoted["code"] == 'print("he said \\"no\\" \\\\ then left")\n', repr(quoted["code"]))
try:
    compile(quoted["code"], "built.py", "exec")
    quoted_parsed = True
except SyntaxError:
    quoted_parsed = False
check("and it still parses", quoted_parsed)

inside = blocks.compile_project({
    "language": "python",
    "blocks": [{"block": "py.print_f", "values": {"text": 'he said "no"'}}],
})
check("text going inside an f-string is escaped but not quoted again",
      inside["code"] == 'print(f"he said \\"no\\"")\n', repr(inside["code"]))
try:
    compile(inside["code"], "built.py", "exec")
    inside_parsed = True
except SyntaxError:
    inside_parsed = False
check("and that parses too", inside_parsed)

attribute = blocks.compile_project({
    "language": "html",
    "blocks": [{"block": "html.link",
                "values": {"href": "go?a=1&b=2", "text": '<script>"'}}],
})
check("HTML entities are written for what lands in a tag",
      attribute["code"] ==
      '<a href="go?a=1&amp;b=2">&lt;script&gt;&quot;</a>\n', repr(attribute["code"]))

rule = blocks.compile_project({
    "language": "css",
    "blocks": [{"block": "css.color", "values": {"value": "red} body {display:none"}}],
})
check("a brace typed into a CSS value cannot close the rule",
      "{" not in rule["code"] and "}" not in rule["code"], repr(rule["code"]))

literal = blocks.compile_project({
    "language": "javascript",
    "blocks": [{"block": "js.template", "values": {"name": "s", "text": "a `b` ${n}"}}],
})
check("a backtick cannot end a template literal, and ${} still works",
      literal["code"] == "const s = `a \\`b\\` ${n}`;\n", repr(literal["code"]))

newlines = blocks.compile_project({
    "language": "python",
    "blocks": [{"block": "py.comment", "values": {"text": "one\ntwo\nthree"}}],
})
check("a value cannot smuggle in extra lines",
      newlines["code"].count("\n") == 1, repr(newlines["code"]))

long_value = blocks.compile_project({
    "language": "python",
    "blocks": [{"block": "py.set", "values": {"name": "x", "value": "9" * 5000}}],
})
check("and it cannot be a whole file long",
      len(long_value["code"]) < blocks.MAX_VALUE + 40, len(long_value["code"]))

say()
say("== a project that is wrong says so, and builds the rest ==")
mixed = blocks.compile_project({
    "language": "python",
    "blocks": [
        {"block": "py.print", "values": {"text": "fine"}},
        {"block": "css.padding", "values": {"value": "10px"}},
        {"block": "nothing.at.all"},
        {"block": "py.print", "values": {"text": "also fine"}},
    ],
})
check("the good blocks are still built", mixed["blocks"] == 2, mixed["blocks"])
check("and both problems are named", len(mixed["problems"]) == 2, mixed["problems"])
check("a language that does not exist is refused",
      not blocks.compile_project({"language": "cobol", "blocks": []})["ok"])
check("an empty project builds to nothing, not to a crash",
      blocks.compile_project({"language": "python", "blocks": []})["code"] == "")

deep = {"block": "py.if", "values": {"condition": "True"}, "children": []}
node = deep
for _ in range(blocks.MAX_DEPTH + 4):
    child = {"block": "py.if", "values": {"condition": "True"}, "children": []}
    node["children"].append(child)
    node = child
nested = blocks.compile_project({"language": "python", "blocks": [deep]})
check("nesting past the limit stops rather than running away",
      any("deeper" in problem for problem in nested["problems"]), nested["problems"][:2])

say()
say("== the plugin itself ==")


class Sink:
    def onOutput(self, stream, text, channel):  # noqa: N802
        pass

    def onReadLine(self, channel):  # noqa: N802
        return None

    def onFinished(self, run_id, status, millis):  # noqa: N802
        pass


class Host:
    def __init__(self):
        self.actions = []

    def onPluginLog(self, level, message, detail):  # noqa: N802
        pass

    def onToast(self, message):  # noqa: N802
        pass

    def onPluginMessage(self, plugin_id, body):  # noqa: N802
        pass

    def onPluginAction(self, plugin_id, action, detail):  # noqa: N802
        self.actions.append((action, detail))
        return True


workspace = tempfile.mkdtemp(prefix="pycmd-creator-ws-")
pycmd_runtime.configure(Sink(), workspace, tempfile.mkdtemp())
host = Host()
plugins.configure(tempfile.mkdtemp(prefix="pycmd-creator-"), workspace, host)

installed = json.loads(plugins.install(CREATOR, "creator", "1"))
check("it installs", installed.get("ok"), installed.get("error"))
loaded = json.loads(plugins.load("pycmd.creator"))
check("and loads", loaded.get("ok"), loaded.get("error"))
check("registering the command it promises",
      "blocks" in loaded.get("commands", []), loaded.get("commands"))

panel = plugins.panel_html("pycmd.creator", "ui.html")
check("its panel renders", "__pycmd_panel" in panel and "<html" in panel.lower(),
      panel[:100])


def call(name, payload=None):
    return json.loads(plugins.call_export("pycmd.creator", name, json.dumps(payload)))


languages = call("languages")
check("the panel can ask what languages there are",
      languages["result"]["total"] == len(blocks.BY_ID), languages)

starter = call("starter", {"language": "python"})
check("and for something to start with",
      starter["result"]["project"]["blocks"], starter)

saved = call("save_project", {"project": {
    "name": "demo", "language": "python",
    "blocks": [{"block": "py.print", "values": {"text": "hi"}}],
}})
check("a project is kept", saved["result"]["ok"], saved)
project_id = saved["result"]["id"]

listed = call("projects")
check("and listed back", len(listed["result"]["projects"]) == 1, listed)
check("with its block count",
      listed["result"]["projects"][0]["blocks"] == 1, listed["result"]["projects"])

reopened = call("open_project", {"id": project_id})
check("and can be opened whole",
      reopened["result"]["project"]["blocks"][0]["block"] == "py.print", reopened)

written = call("save_file", {
    "project": {"name": "demo", "language": "python",
                "blocks": [{"block": "py.print", "values": {"text": "hi"}}]},
    "name": "demo", "folder": "built",
})
check("a build lands in the workspace", written["result"]["ok"], written)
target = os.path.join(workspace, "built", "demo.py")
check("as a real file with the right name", os.path.isfile(target), target)
check("holding the code", open(target, encoding="utf-8").read() == 'print("hi")\n',
      open(target, encoding="utf-8").read())

escaped = call("save_file", {
    "project": {"name": "x", "language": "python",
                "blocks": [{"block": "py.print", "values": {"text": "hi"}}]},
    "name": "escape", "folder": "../../outside",
})
check("a folder cannot climb out of the workspace",
      escaped["result"]["ok"] and
      os.path.isfile(os.path.join(workspace, "outside", "escape.py")),
      escaped)

nothing = call("save_file", {"project": {"name": "empty", "language": "python",
                                         "blocks": []}})
check("an empty project is not saved as an empty file",
      not nothing["result"]["ok"], nothing)

named = call("save_file", {
    "project": {"name": "page", "language": "html",
                "blocks": [{"block": "html.doctype"}]},
    "name": "page",
})
check("a bare name gets the language's extension",
      os.path.isfile(os.path.join(workspace, "page.html")), named)

kept = call("save_file", {
    "project": {"name": "readme", "language": "markdown",
                "blocks": [{"block": "md.h1", "values": {"text": "Hi"}}]},
    "name": "readme.txt",
})
check("and a name that already has one is left as typed",
      os.path.isfile(os.path.join(workspace, "readme.txt")) and
      not os.path.isfile(os.path.join(workspace, "readme.txt.md")), kept)

deleted = call("delete_project", {"id": project_id})
check("a project can be thrown away", deleted["result"]["ok"], deleted)
check("and then it is gone", not call("projects")["result"]["projects"])

say()
say("== the console command ==")
langs = json.loads(plugins.run_command("blocks", "langs"))
check("blocks langs answers", langs.get("handled") and "Python" in langs.get("result", ""),
      langs)
empty_list = json.loads(plugins.run_command("blocks", "list"))
check("blocks list answers when there is nothing",
      "No projects" in empty_list.get("result", ""), empty_list)
call("save_project", {"project": {
    "name": "again", "language": "python",
    "blocks": [{"block": "py.print", "values": {"text": "again"}}],
}})
built_one = json.loads(plugins.run_command("blocks", "build again"))
check("blocks build prints the code",
      'print("again")' in built_one.get("result", ""), built_one)
missing = json.loads(plugins.run_command("blocks", "build nope"))
check("and says so when there is no such project",
      "No project" in missing.get("result", ""), missing)

say()
if FAILURES:
    say(f"{len(FAILURES)} creator checks failed")
    sys.exit(1)
say("all creator checks passed")
