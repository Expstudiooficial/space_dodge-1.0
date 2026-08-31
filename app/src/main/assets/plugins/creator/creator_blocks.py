"""The blocks, and the thing that turns a stack of them into a file.

This is the whole of Creator that is worth testing, and none of it touches the
app: a catalogue of blocks, and a compiler that walks a tree of them and
writes out source. Feed it a project, get back text. That is the entire
contract, which is why it lives in its own module rather than inside the
plugin's `main.py` - a laptop can run it, and `tools/test_creator.py` does.

## What a block is

A dict, and a small one. `open` is the line it writes, with `@slot@` where a
value goes; `wrap` means it can hold other blocks, and `close` is the line
that comes after them - `}` in JavaScript, `</div>` in HTML, nothing at all in
Python, where the indentation is the closing.

`@slot@` rather than `{slot}` for one reason that decides it: three of the
five languages here use braces as syntax. `if (x) {` and `body { color: red }`
would both need escaping under `str.format`, every time, and one missed escape
is a block that crashes the compiler instead of writing a line. `@` is not
syntax in any of them. A literal `@` is written `@@`, which CSS at-rules and
Python decorators both need.

## What it is not

Not a parser. Blocks go one way - into source - and a file cannot be read back
into blocks. That is a deliberate line: a round trip would mean writing five
parsers and keeping them right, and the thing people want from a block editor
is the first direction, where the syntax errors live.

Not a sandbox, either. A slot takes what somebody types, and what they type
ends up in a file they then run. That is the same trust the editor has: this
is a tool for writing your own code, not for running anybody else's.
"""

from __future__ import annotations

import re

__all__ = [
    "LANGUAGES",
    "BLOCKS",
    "catalogue",
    "compile_project",
    "block",
    "MAX_BLOCKS",
    "MAX_DEPTH",
]

# What a project can be written in. `indent` is one step of nesting, and it is
# the language's own convention rather than a setting: Python code indented two
# spaces looks wrong to every Python programmer alive.
LANGUAGES = [
    {"id": "python", "name": "Python", "extension": ".py", "indent": "    ",
     "about": "Runs in the app. Everything the console can do."},
    {"id": "javascript", "name": "JavaScript", "extension": ".js", "indent": "  ",
     "about": "Runs in a page, or on its own in the Servers tab."},
    {"id": "html", "name": "HTML", "extension": ".html", "indent": "  ",
     "about": "A page. Serve the folder and it is a website."},
    {"id": "css", "name": "CSS", "extension": ".css", "indent": "  ",
     "about": "How the page looks."},
    {"id": "markdown", "name": "Markdown", "extension": ".md", "indent": "",
     "about": "Notes and documents. The preview renders it."},
]

LANGUAGE_IDS = [row["id"] for row in LANGUAGES]

PLACEHOLDER = re.compile(r"@([a-z_][a-z0-9_]*)@")

# A slot holds one line's worth of value. Anything longer is somebody pasting
# a program into a hole meant for a name.
MAX_VALUE = 400

# A project you can still scroll, and a nesting depth past which nobody knows
# what they are looking at.
MAX_BLOCKS = 2000
MAX_DEPTH = 24


def _slot(name: str, label: str, kind: str = "text", default: str = "",
          options=None) -> dict:
    """One hole in a block.

    `kind` decides how the panel asks for it and how it is written out:

    * `text` - an expression, written exactly as typed. The escape hatch:
      whatever goes in comes out.
    * `string` - a piece of text, made safe for where it lands. Python and
      JavaScript get quotes round it and their escapes; HTML gets its entities,
      so a quote in an attribute cannot end the attribute; CSS loses braces,
      which cannot appear in a declaration and can only end the rule early.
    * `inline` - text that is going *inside* something already quoted, like an
      f-string or a template literal. Escaped, but not quoted again.
    * `number` - a number field; a blank one is 0.
    * `name` - a variable, function or property name. Trimmed and used as
      typed: `data["k"]` is a perfectly good thing to append to, and refusing
      it would be a rule that only got in the way.
    * `choice` - one of `options`, and nothing else.
    """
    return {
        "name": name,
        "label": label,
        "kind": kind,
        "default": default,
        "options": list(options or []),
    }


def _block(bid: str, cat: str, label: str, open_: str, slots=(), close: str = "",
           wrap: bool = False, empty: str = "", about: str = "") -> dict:
    return {
        "id": bid,
        "cat": cat,
        "label": label,
        "open": open_,
        "close": close,
        "wrap": wrap,
        "empty": empty,
        "about": about,
        "slots": list(slots),
    }


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

PYTHON = [
    # -- Basics ------------------------------------------------------------
    _block("py.print", "Basics", "print text", "print(@text@)",
           [_slot("text", "text", "string", "Hello")]),
    _block("py.print_value", "Basics", "print a value", "print(@value@)",
           [_slot("value", "value", "text", "total")]),
    _block("py.print_two", "Basics", "print two things", "print(@a@, @b@)",
           [_slot("a", "first", "text", "name"), _slot("b", "second", "text", "score")]),
    _block("py.print_labelled", "Basics", "print a label and a value",
           "print(@label@, @value@)",
           [_slot("label", "label", "string", "Total:"), _slot("value", "value", "text", "total")]),
    _block("py.print_f", "Basics", "print a sentence with values in it",
           'print(f"@text@")',
           [_slot("text", "text, with {name} in it", "inline",
                  "Hello {name}, you have {score}")]),
    _block("py.comment", "Basics", "a note to yourself", "# @text@",
           [_slot("text", "note", "text", "what this part does")]),
    _block("py.blank", "Basics", "an empty line", ""),
    _block("py.pass", "Basics", "do nothing", "pass"),
    _block("py.input", "Basics", "ask for text", "@name@ = input(@prompt@)",
           [_slot("name", "keep it in", "name", "answer"),
            _slot("prompt", "question", "string", "What is your name? ")]),
    _block("py.input_number", "Basics", "ask for a number",
           "@name@ = int(input(@prompt@))",
           [_slot("name", "keep it in", "name", "age"),
            _slot("prompt", "question", "string", "How old are you? ")]),
    _block("py.stop", "Basics", "stop the program", "raise SystemExit"),

    # -- Variables ---------------------------------------------------------
    _block("py.set", "Variables", "set to a value", "@name@ = @value@",
           [_slot("name", "name", "name", "total"), _slot("value", "value", "text", "0")]),
    _block("py.set_text", "Variables", "set to text", "@name@ = @text@",
           [_slot("name", "name", "name", "title"), _slot("text", "text", "string", "Hello")]),
    _block("py.set_number", "Variables", "set to a number", "@name@ = @number@",
           [_slot("name", "name", "name", "score"), _slot("number", "number", "number", "0")]),
    _block("py.set_bool", "Variables", "set to true or false", "@name@ = @value@",
           [_slot("name", "name", "name", "ready"),
            _slot("value", "value", "choice", "True", ["True", "False"])]),
    _block("py.set_none", "Variables", "set to nothing", "@name@ = None",
           [_slot("name", "name", "name", "found")]),
    _block("py.set_list", "Variables", "set to a list", "@name@ = [@items@]",
           [_slot("name", "name", "name", "items"),
            _slot("items", "items, comma separated", "text", '"a", "b", "c"')]),
    _block("py.set_dict", "Variables", "set to a dictionary", "@name@ = {@pairs@}",
           [_slot("name", "name", "name", "person"),
            _slot("pairs", "key: value pairs", "text", '"name": "Ada", "age": 36')]),
    _block("py.increase", "Variables", "add to a number", "@name@ += @amount@",
           [_slot("name", "name", "name", "score"), _slot("amount", "by", "number", "1")]),
    _block("py.decrease", "Variables", "take away from a number", "@name@ -= @amount@",
           [_slot("name", "name", "name", "lives"), _slot("amount", "by", "number", "1")]),
    _block("py.multiply_by", "Variables", "multiply a number", "@name@ *= @amount@",
           [_slot("name", "name", "name", "total"), _slot("amount", "by", "number", "2")]),
    _block("py.delete", "Variables", "forget a variable", "del @name@",
           [_slot("name", "name", "name", "temp")]),
    _block("py.global", "Variables", "use the outer variable", "global @name@",
           [_slot("name", "name", "name", "total")]),

    # -- Maths -------------------------------------------------------------
    _block("py.add", "Maths", "add", "@name@ = @a@ + @b@",
           [_slot("name", "keep it in", "name", "total"),
            _slot("a", "first", "text", "a"), _slot("b", "second", "text", "b")]),
    _block("py.subtract", "Maths", "subtract", "@name@ = @a@ - @b@",
           [_slot("name", "keep it in", "name", "left"),
            _slot("a", "from", "text", "a"), _slot("b", "take away", "text", "b")]),
    _block("py.multiply", "Maths", "multiply", "@name@ = @a@ * @b@",
           [_slot("name", "keep it in", "name", "product"),
            _slot("a", "first", "text", "a"), _slot("b", "second", "text", "b")]),
    _block("py.divide", "Maths", "divide", "@name@ = @a@ / @b@",
           [_slot("name", "keep it in", "name", "share"),
            _slot("a", "divide", "text", "a"), _slot("b", "by", "text", "b")]),
    _block("py.whole_divide", "Maths", "divide, whole numbers only",
           "@name@ = @a@ // @b@",
           [_slot("name", "keep it in", "name", "boxes"),
            _slot("a", "divide", "text", "items"), _slot("b", "by", "text", "10")]),
    _block("py.remainder", "Maths", "remainder", "@name@ = @a@ % @b@",
           [_slot("name", "keep it in", "name", "left"),
            _slot("a", "divide", "text", "n"), _slot("b", "by", "text", "2")]),
    _block("py.power", "Maths", "to the power of", "@name@ = @a@ ** @b@",
           [_slot("name", "keep it in", "name", "big"),
            _slot("a", "number", "text", "2"), _slot("b", "power", "text", "10")]),
    _block("py.maths", "Maths", "any sum", "@name@ = @a@ @op@ @b@",
           [_slot("name", "keep it in", "name", "answer"),
            _slot("a", "first", "text", "a"),
            _slot("op", "operator", "choice", "+", ["+", "-", "*", "/", "//", "%", "**"]),
            _slot("b", "second", "text", "b")]),
    _block("py.round", "Maths", "round a number", "@name@ = round(@value@, @places@)",
           [_slot("name", "keep it in", "name", "rounded"),
            _slot("value", "number", "text", "value"), _slot("places", "decimals", "number", "2")]),
    _block("py.absolute", "Maths", "size without the sign", "@name@ = abs(@value@)",
           [_slot("name", "keep it in", "name", "size"), _slot("value", "number", "text", "value")]),
    _block("py.to_int", "Maths", "as a whole number", "@name@ = int(@value@)",
           [_slot("name", "keep it in", "name", "count"), _slot("value", "value", "text", "text")]),
    _block("py.to_float", "Maths", "as a decimal", "@name@ = float(@value@)",
           [_slot("name", "keep it in", "name", "price"), _slot("value", "value", "text", "text")]),
    _block("py.smallest", "Maths", "the smaller of two", "@name@ = min(@a@, @b@)",
           [_slot("name", "keep it in", "name", "lowest"),
            _slot("a", "first", "text", "a"), _slot("b", "second", "text", "b")]),
    _block("py.largest", "Maths", "the larger of two", "@name@ = max(@a@, @b@)",
           [_slot("name", "keep it in", "name", "highest"),
            _slot("a", "first", "text", "a"), _slot("b", "second", "text", "b")]),
    _block("py.sum", "Maths", "add up a list", "@name@ = sum(@list@)",
           [_slot("name", "keep it in", "name", "total"), _slot("list", "list", "text", "scores")]),
    _block("py.average", "Maths", "the average of a list",
           "@name@ = sum(@list@) / len(@list@)",
           [_slot("name", "keep it in", "name", "average"),
            _slot("list", "list", "text", "scores")]),

    # -- Text --------------------------------------------------------------
    _block("py.join_text", "Text", "join two pieces of text", "@name@ = @a@ + @b@",
           [_slot("name", "keep it in", "name", "greeting"),
            _slot("a", "first", "text", '"Hello "'), _slot("b", "second", "text", "name")]),
    _block("py.format", "Text", "build a sentence", '@name@ = f"@text@"',
           [_slot("name", "keep it in", "name", "line"),
            _slot("text", "text, with {name} in it", "inline", "{name} scored {score}")]),
    _block("py.upper", "Text", "in capitals", "@name@ = @value@.upper()",
           [_slot("name", "keep it in", "name", "shout"), _slot("value", "text", "text", "line")]),
    _block("py.lower", "Text", "in lower case", "@name@ = @value@.lower()",
           [_slot("name", "keep it in", "name", "quiet"), _slot("value", "text", "text", "line")]),
    _block("py.title_case", "Text", "with each word capitalised",
           "@name@ = @value@.title()",
           [_slot("name", "keep it in", "name", "titled"), _slot("value", "text", "text", "line")]),
    _block("py.strip", "Text", "without the spaces around it",
           "@name@ = @value@.strip()",
           [_slot("name", "keep it in", "name", "clean"), _slot("value", "text", "text", "line")]),
    _block("py.replace", "Text", "with something swapped",
           "@name@ = @value@.replace(@old@, @new@)",
           [_slot("name", "keep it in", "name", "fixed"), _slot("value", "text", "text", "line"),
            _slot("old", "find", "string", "cat"), _slot("new", "replace with", "string", "dog")]),
    _block("py.split", "Text", "split into a list",
           "@name@ = @value@.split(@separator@)",
           [_slot("name", "keep it in", "name", "parts"), _slot("value", "text", "text", "line"),
            _slot("separator", "split on", "string", ",")]),
    _block("py.join_list", "Text", "join a list into text",
           "@name@ = @separator@.join(@list@)",
           [_slot("name", "keep it in", "name", "line"),
            _slot("separator", "between them", "string", ", "),
            _slot("list", "list", "text", "words")]),
    _block("py.length", "Text", "how long it is", "@name@ = len(@value@)",
           [_slot("name", "keep it in", "name", "count"), _slot("value", "text or list", "text", "line")]),
    _block("py.contains", "Text", "does it contain", "@name@ = @needle@ in @haystack@",
           [_slot("name", "keep it in", "name", "found"),
            _slot("needle", "look for", "string", "cat"),
            _slot("haystack", "in", "text", "line")]),
    _block("py.starts_with", "Text", "does it start with",
           "@name@ = @value@.startswith(@prefix@)",
           [_slot("name", "keep it in", "name", "starts"), _slot("value", "text", "text", "line"),
            _slot("prefix", "starts with", "string", "http")]),
    _block("py.ends_with", "Text", "does it end with",
           "@name@ = @value@.endswith(@suffix@)",
           [_slot("name", "keep it in", "name", "ends"), _slot("value", "text", "text", "name"),
            _slot("suffix", "ends with", "string", ".py")]),
    _block("py.find", "Text", "where something is",
           "@name@ = @value@.find(@needle@)",
           [_slot("name", "keep it in", "name", "at"), _slot("value", "text", "text", "line"),
            _slot("needle", "look for", "string", "=")]),
    _block("py.slice", "Text", "a piece of it", "@name@ = @value@[@start@:@end@]",
           [_slot("name", "keep it in", "name", "piece"), _slot("value", "text or list", "text", "line"),
            _slot("start", "from", "number", "0"), _slot("end", "to", "number", "5")]),
    _block("py.to_text", "Text", "as text", "@name@ = str(@value@)",
           [_slot("name", "keep it in", "name", "text"), _slot("value", "value", "text", "number")]),

    # -- Lists -------------------------------------------------------------
    _block("py.new_list", "Lists", "a new empty list", "@name@ = []",
           [_slot("name", "name", "name", "items")]),
    _block("py.append", "Lists", "add to the end", "@list@.append(@value@)",
           [_slot("list", "list", "name", "items"), _slot("value", "value", "text", "item")]),
    _block("py.insert", "Lists", "put in at a position",
           "@list@.insert(@index@, @value@)",
           [_slot("list", "list", "name", "items"), _slot("index", "at", "number", "0"),
            _slot("value", "value", "text", "item")]),
    _block("py.remove_value", "Lists", "take one out by value",
           "@list@.remove(@value@)",
           [_slot("list", "list", "name", "items"), _slot("value", "value", "text", "item")]),
    _block("py.pop", "Lists", "take one out by position",
           "@name@ = @list@.pop(@index@)",
           [_slot("name", "keep it in", "name", "item"), _slot("list", "list", "name", "items"),
            _slot("index", "at", "number", "0")]),
    _block("py.clear_list", "Lists", "empty it", "@list@.clear()",
           [_slot("list", "list", "name", "items")]),
    _block("py.sort", "Lists", "put in order", "@list@.sort()",
           [_slot("list", "list", "name", "items")]),
    _block("py.sort_by", "Lists", "put in order by something",
           "@list@.sort(key=@key@)",
           [_slot("list", "list", "name", "people"),
            _slot("key", "sort by", "text", 'lambda row: row["age"]')]),
    _block("py.reverse", "Lists", "turn it round", "@list@.reverse()",
           [_slot("list", "list", "name", "items")]),
    _block("py.list_length", "Lists", "how many", "@name@ = len(@list@)",
           [_slot("name", "keep it in", "name", "count"), _slot("list", "list", "name", "items")]),
    _block("py.item_at", "Lists", "the item at", "@name@ = @list@[@index@]",
           [_slot("name", "keep it in", "name", "item"), _slot("list", "list", "name", "items"),
            _slot("index", "position", "number", "0")]),
    _block("py.set_item", "Lists", "replace the item at", "@list@[@index@] = @value@",
           [_slot("list", "list", "name", "items"), _slot("index", "position", "number", "0"),
            _slot("value", "value", "text", "item")]),
    _block("py.in_list", "Lists", "is it in the list", "@name@ = @value@ in @list@",
           [_slot("name", "keep it in", "name", "found"), _slot("value", "value", "text", "item"),
            _slot("list", "list", "name", "items")]),
    _block("py.index_of", "Lists", "where it is in the list",
           "@name@ = @list@.index(@value@)",
           [_slot("name", "keep it in", "name", "at"), _slot("list", "list", "name", "items"),
            _slot("value", "value", "text", "item")]),
    _block("py.count_in", "Lists", "how many times it appears",
           "@name@ = @list@.count(@value@)",
           [_slot("name", "keep it in", "name", "times"), _slot("list", "list", "name", "items"),
            _slot("value", "value", "text", "item")]),
    _block("py.comprehension", "Lists", "a list built from another",
           "@name@ = [@expression@ for @item@ in @list@]",
           [_slot("name", "keep it in", "name", "doubled"),
            _slot("expression", "each one becomes", "text", "item * 2"),
            _slot("item", "each is called", "name", "item"),
            _slot("list", "from", "name", "items")]),

    # -- Dictionaries ------------------------------------------------------
    _block("py.new_dict", "Dictionaries", "a new empty dictionary", "@name@ = {}",
           [_slot("name", "name", "name", "data")]),
    _block("py.dict_set", "Dictionaries", "set a key",
           "@dict@[@key@] = @value@",
           [_slot("dict", "dictionary", "name", "data"), _slot("key", "key", "string", "name"),
            _slot("value", "value", "text", '"Ada"')]),
    _block("py.dict_get", "Dictionaries", "read a key",
           "@name@ = @dict@.get(@key@, @fallback@)",
           [_slot("name", "keep it in", "name", "value"), _slot("dict", "dictionary", "name", "data"),
            _slot("key", "key", "string", "name"), _slot("fallback", "if missing", "text", "None")]),
    _block("py.dict_has", "Dictionaries", "does it have a key",
           "@name@ = @key@ in @dict@",
           [_slot("name", "keep it in", "name", "found"), _slot("key", "key", "string", "name"),
            _slot("dict", "dictionary", "name", "data")]),
    _block("py.dict_remove", "Dictionaries", "remove a key", "del @dict@[@key@]",
           [_slot("dict", "dictionary", "name", "data"), _slot("key", "key", "string", "name")]),
    _block("py.dict_keys", "Dictionaries", "all the keys",
           "@name@ = list(@dict@.keys())",
           [_slot("name", "keep it in", "name", "keys"), _slot("dict", "dictionary", "name", "data")]),
    _block("py.dict_values", "Dictionaries", "all the values",
           "@name@ = list(@dict@.values())",
           [_slot("name", "keep it in", "name", "values"),
            _slot("dict", "dictionary", "name", "data")]),
    _block("py.dict_items", "Dictionaries", "for every key and value",
           "for @key@, @value@ in @dict@.items():",
           [_slot("key", "key is called", "name", "key"),
            _slot("value", "value is called", "name", "value"),
            _slot("dict", "dictionary", "name", "data")],
           wrap=True, empty="pass"),
    _block("py.dict_update", "Dictionaries", "merge another in",
           "@dict@.update(@other@)",
           [_slot("dict", "dictionary", "name", "data"), _slot("other", "merge in", "text", "extra")]),
    _block("py.dict_length", "Dictionaries", "how many keys",
           "@name@ = len(@dict@)",
           [_slot("name", "keep it in", "name", "count"),
            _slot("dict", "dictionary", "name", "data")]),

    # -- Logic -------------------------------------------------------------
    _block("py.if", "Logic", "if", "if @condition@:",
           [_slot("condition", "when", "text", "score > 10")], wrap=True, empty="pass"),
    _block("py.if_equals", "Logic", "if two things are the same", "if @a@ == @b@:",
           [_slot("a", "this", "text", "answer"), _slot("b", "is", "text", '"yes"')],
           wrap=True, empty="pass"),
    _block("py.if_not_equals", "Logic", "if two things are different",
           "if @a@ != @b@:",
           [_slot("a", "this", "text", "answer"), _slot("b", "is not", "text", '"yes"')],
           wrap=True, empty="pass"),
    _block("py.if_greater", "Logic", "if bigger than", "if @a@ > @b@:",
           [_slot("a", "this", "text", "score"), _slot("b", "is bigger than", "text", "10")],
           wrap=True, empty="pass"),
    _block("py.if_less", "Logic", "if smaller than", "if @a@ < @b@:",
           [_slot("a", "this", "text", "score"), _slot("b", "is smaller than", "text", "10")],
           wrap=True, empty="pass"),
    _block("py.if_in", "Logic", "if it contains", "if @needle@ in @haystack@:",
           [_slot("needle", "this", "text", '"cat"'), _slot("haystack", "is in", "text", "line")],
           wrap=True, empty="pass"),
    _block("py.elif", "Logic", "or else if", "elif @condition@:",
           [_slot("condition", "when", "text", "score > 5")], wrap=True, empty="pass"),
    _block("py.else", "Logic", "otherwise", "else:", wrap=True, empty="pass"),
    _block("py.and", "Logic", "both are true", "@name@ = @a@ and @b@",
           [_slot("name", "keep it in", "name", "both"), _slot("a", "this", "text", "ready"),
            _slot("b", "and", "text", "willing")]),
    _block("py.or", "Logic", "either is true", "@name@ = @a@ or @b@",
           [_slot("name", "keep it in", "name", "either"), _slot("a", "this", "text", "ready"),
            _slot("b", "or", "text", "waiting")]),
    _block("py.not", "Logic", "the opposite", "@name@ = not @value@",
           [_slot("name", "keep it in", "name", "missing"), _slot("value", "of", "text", "found")]),
    _block("py.compare", "Logic", "compare two things", "@name@ = @a@ @op@ @b@",
           [_slot("name", "keep it in", "name", "result"), _slot("a", "this", "text", "a"),
            _slot("op", "compared", "choice", "==", ["==", "!=", "<", ">", "<=", ">=", "in"]),
            _slot("b", "to", "text", "b")]),

    # -- Loops -------------------------------------------------------------
    _block("py.repeat", "Loops", "repeat this many times",
           "for @var@ in range(@times@):",
           [_slot("var", "counter", "name", "i"), _slot("times", "times", "number", "10")],
           wrap=True, empty="pass"),
    _block("py.count_from", "Loops", "count from one number to another",
           "for @var@ in range(@start@, @end@):",
           [_slot("var", "counter", "name", "i"), _slot("start", "from", "number", "1"),
            _slot("end", "up to", "number", "11")],
           wrap=True, empty="pass"),
    _block("py.for_each", "Loops", "for each item in a list",
           "for @item@ in @list@:",
           [_slot("item", "each is called", "name", "item"), _slot("list", "in", "name", "items")],
           wrap=True, empty="pass"),
    _block("py.for_each_index", "Loops", "for each item, with its position",
           "for @index@, @item@ in enumerate(@list@):",
           [_slot("index", "position is called", "name", "index"),
            _slot("item", "each is called", "name", "item"),
            _slot("list", "in", "name", "items")],
           wrap=True, empty="pass"),
    _block("py.for_two", "Loops", "for each pair from two lists",
           "for @a@, @b@ in zip(@first@, @second@):",
           [_slot("a", "first is called", "name", "name"),
            _slot("b", "second is called", "name", "score"),
            _slot("first", "first list", "name", "names"),
            _slot("second", "second list", "name", "scores")],
           wrap=True, empty="pass"),
    _block("py.while", "Loops", "keep going while", "while @condition@:",
           [_slot("condition", "while", "text", "running")], wrap=True, empty="pass"),
    _block("py.forever", "Loops", "keep going forever", "while True:",
           wrap=True, empty="pass"),
    _block("py.break", "Loops", "stop the loop", "break"),
    _block("py.continue", "Loops", "skip to the next time round", "continue"),

    # -- Functions ---------------------------------------------------------
    _block("py.def", "Functions", "define a function", "def @name@(@params@):",
           [_slot("name", "called", "name", "greet"),
            _slot("params", "taking", "text", "name")],
           wrap=True, empty="pass"),
    _block("py.def_plain", "Functions", "define a function with no inputs",
           "def @name@():",
           [_slot("name", "called", "name", "main")], wrap=True, empty="pass"),
    _block("py.return", "Functions", "give an answer back", "return @value@",
           [_slot("value", "answer", "text", "result")]),
    _block("py.return_none", "Functions", "give nothing back", "return"),
    _block("py.call", "Functions", "run a function", "@name@(@args@)",
           [_slot("name", "function", "name", "greet"), _slot("args", "with", "text", '"Ada"')]),
    _block("py.call_keep", "Functions", "run a function and keep the answer",
           "@result@ = @name@(@args@)",
           [_slot("result", "keep it in", "name", "answer"),
            _slot("name", "function", "name", "greet"), _slot("args", "with", "text", '"Ada"')]),
    _block("py.lambda", "Functions", "a one-line function",
           "@name@ = lambda @params@: @expression@",
           [_slot("name", "called", "name", "double"), _slot("params", "taking", "text", "n"),
            _slot("expression", "gives back", "text", "n * 2")]),
    _block("py.main_guard", "Functions", "only when this file is run",
           'if __name__ == "__main__":', wrap=True, empty="pass"),
    _block("py.docstring", "Functions", "explain what this does",
           '"""@text@"""',
           [_slot("text", "explanation", "inline", "What this does.")]),

    # -- Files -------------------------------------------------------------
    _block("py.read_file", "Files", "read a whole file",
           "@name@ = open(@path@).read()",
           [_slot("name", "keep it in", "name", "text"),
            _slot("path", "file", "string", "notes.txt")]),
    _block("py.write_file", "Files", "write a file",
           'open(@path@, "w").write(@text@)',
           [_slot("path", "file", "string", "notes.txt"),
            _slot("text", "text", "text", "text")]),
    _block("py.append_file", "Files", "add to the end of a file",
           'open(@path@, "a").write(@text@)',
           [_slot("path", "file", "string", "log.txt"),
            _slot("text", "text", "text", 'line + "\\n"')]),
    _block("py.with_read", "Files", "open a file to read",
           "with open(@path@) as @handle@:",
           [_slot("path", "file", "string", "notes.txt"),
            _slot("handle", "called", "name", "handle")],
           wrap=True, empty="pass"),
    _block("py.with_write", "Files", "open a file to write",
           'with open(@path@, "w") as @handle@:',
           [_slot("path", "file", "string", "notes.txt"),
            _slot("handle", "called", "name", "handle")],
           wrap=True, empty="pass"),
    _block("py.for_line", "Files", "for every line in a file",
           "for @line@ in open(@path@):",
           [_slot("line", "each is called", "name", "line"),
            _slot("path", "file", "string", "notes.txt")],
           wrap=True, empty="pass"),
    _block("py.file_exists", "Files", "does a file exist",
           "@name@ = os.path.exists(@path@)",
           [_slot("name", "keep it in", "name", "there"),
            _slot("path", "file", "string", "notes.txt")]),
    _block("py.list_folder", "Files", "everything in a folder",
           "@name@ = os.listdir(@path@)",
           [_slot("name", "keep it in", "name", "names"), _slot("path", "folder", "string", ".")]),
    _block("py.make_folder", "Files", "make a folder",
           "os.makedirs(@path@, exist_ok=True)",
           [_slot("path", "folder", "string", "output")]),
    _block("py.delete_file", "Files", "delete a file", "os.remove(@path@)",
           [_slot("path", "file", "string", "temp.txt")]),

    # -- Bringing things in ------------------------------------------------
    _block("py.import", "Modules", "use a library", "import @module@",
           [_slot("module", "library", "name", "random")]),
    _block("py.from_import", "Modules", "use part of a library",
           "from @module@ import @names@",
           [_slot("module", "library", "name", "datetime"),
            _slot("names", "the parts", "text", "datetime")]),
    _block("py.import_as", "Modules", "use a library under a shorter name",
           "import @module@ as @alias@",
           [_slot("module", "library", "name", "numpy"), _slot("alias", "as", "name", "np")]),
    _block("py.run_command", "Modules", "run a shell command",
           "os.system(@command@)",
           [_slot("command", "command", "string", "ls")]),
    _block("py.argument", "Modules", "an argument this file was run with",
           "@name@ = sys.argv[@index@]",
           [_slot("name", "keep it in", "name", "first"), _slot("index", "number", "number", "1")]),
    _block("py.env", "Modules", "an environment setting",
           "@name@ = os.environ.get(@key@, @fallback@)",
           [_slot("name", "keep it in", "name", "home"), _slot("key", "setting", "string", "HOME"),
            _slot("fallback", "if missing", "text", '""')]),
    _block("py.now", "Modules", "the time right now",
           "@name@ = datetime.datetime.now()",
           [_slot("name", "keep it in", "name", "now")]),
    _block("py.sleep", "Modules", "wait for a moment", "time.sleep(@seconds@)",
           [_slot("seconds", "seconds", "number", "1")]),

    # -- Random ------------------------------------------------------------
    _block("py.random_int", "Random", "a random whole number",
           "@name@ = random.randint(@low@, @high@)",
           [_slot("name", "keep it in", "name", "roll"), _slot("low", "from", "number", "1"),
            _slot("high", "to", "number", "6")]),
    _block("py.random_choice", "Random", "a random item from a list",
           "@name@ = random.choice(@list@)",
           [_slot("name", "keep it in", "name", "picked"), _slot("list", "list", "name", "items")]),
    _block("py.shuffle", "Random", "shuffle a list", "random.shuffle(@list@)",
           [_slot("list", "list", "name", "items")]),
    _block("py.random_float", "Random", "a random number between 0 and 1",
           "@name@ = random.random()",
           [_slot("name", "keep it in", "name", "chance")]),
    _block("py.random_sample", "Random", "several random items",
           "@name@ = random.sample(@list@, @count@)",
           [_slot("name", "keep it in", "name", "picked"), _slot("list", "list", "name", "items"),
            _slot("count", "how many", "number", "3")]),

    # -- The web -----------------------------------------------------------
    _block("py.fetch_text", "Web", "fetch a page",
           "@name@ = requests.get(@url@).text",
           [_slot("name", "keep it in", "name", "page"),
            _slot("url", "address", "string", "https://example.com")]),
    _block("py.fetch_json", "Web", "fetch JSON",
           "@name@ = requests.get(@url@).json()",
           [_slot("name", "keep it in", "name", "data"),
            _slot("url", "address", "string", "https://example.com/api")]),
    _block("py.post_json", "Web", "send JSON",
           "@name@ = requests.post(@url@, json=@data@).json()",
           [_slot("name", "keep it in", "name", "reply"),
            _slot("url", "address", "string", "https://example.com/api"),
            _slot("data", "send", "text", "payload")]),
    _block("py.to_json", "Web", "turn into JSON text",
           "@name@ = json.dumps(@value@, indent=2)",
           [_slot("name", "keep it in", "name", "text"), _slot("value", "value", "text", "data")]),
    _block("py.from_json", "Web", "read JSON text",
           "@name@ = json.loads(@text@)",
           [_slot("name", "keep it in", "name", "data"), _slot("text", "text", "text", "body")]),
    _block("py.flask_app", "Web", "a Flask app", "@name@ = Flask(__name__)",
           [_slot("name", "called", "name", "app")]),
    _block("py.flask_route", "Web", "answer a web address",
           "@@app.route(@path@)",
           [_slot("path", "address", "string", "/")]),
    _block("py.flask_run", "Web", "start the Flask app", "app.run()"),

    # -- When things go wrong ----------------------------------------------
    _block("py.try", "Errors", "try this", "try:", wrap=True, empty="pass"),
    _block("py.except", "Errors", "if it went wrong",
           "except @error@ as @name@:",
           [_slot("error", "the problem", "text", "Exception"),
            _slot("name", "called", "name", "error")],
           wrap=True, empty="pass"),
    _block("py.finally", "Errors", "either way, do this", "finally:",
           wrap=True, empty="pass"),
    _block("py.raise", "Errors", "report a problem",
           "raise @error@(@message@)",
           [_slot("error", "kind", "text", "ValueError"),
            _slot("message", "message", "string", "that will not do")]),
    _block("py.assert", "Errors", "insist something is true",
           "assert @condition@, @message@",
           [_slot("condition", "must be true", "text", "count > 0"),
            _slot("message", "or say", "string", "there is nothing to do")]),

    # -- Classes -----------------------------------------------------------
    _block("py.class", "Classes", "define a kind of thing", "class @name@:",
           [_slot("name", "called", "name", "Player")], wrap=True, empty="pass"),
    _block("py.init", "Classes", "how one is made",
           "def __init__(self, @params@):",
           [_slot("params", "taking", "text", "name")], wrap=True, empty="pass"),
    _block("py.method", "Classes", "something it can do",
           "def @name@(self):",
           [_slot("name", "called", "name", "speak")], wrap=True, empty="pass"),
    _block("py.method_args", "Classes", "something it can do, with inputs",
           "def @name@(self, @params@):",
           [_slot("name", "called", "name", "move"), _slot("params", "taking", "text", "steps")],
           wrap=True, empty="pass"),
    _block("py.set_attribute", "Classes", "remember something on it",
           "self.@name@ = @value@",
           [_slot("name", "called", "name", "name"), _slot("value", "value", "text", "name")]),
    _block("py.get_attribute", "Classes", "read something off it",
           "@name@ = self.@attribute@",
           [_slot("name", "keep it in", "name", "value"),
            _slot("attribute", "attribute", "name", "name")]),
    _block("py.new_object", "Classes", "make one", "@name@ = @kind@(@args@)",
           [_slot("name", "called", "name", "player"), _slot("kind", "kind", "name", "Player"),
            _slot("args", "with", "text", '"Ada"')]),
]


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

JAVASCRIPT = [
    # -- Basics ------------------------------------------------------------
    _block("js.log", "Basics", "log text", "console.log(@text@);",
           [_slot("text", "text", "string", "Hello")]),
    _block("js.log_value", "Basics", "log a value", "console.log(@value@);",
           [_slot("value", "value", "text", "total")]),
    _block("js.log_labelled", "Basics", "log a label and a value",
           "console.log(@label@, @value@);",
           [_slot("label", "label", "string", "total:"), _slot("value", "value", "text", "total")]),
    _block("js.comment", "Basics", "a note to yourself", "// @text@",
           [_slot("text", "note", "text", "what this part does")]),
    _block("js.blank", "Basics", "an empty line", ""),
    _block("js.alert", "Basics", "show a message box", "alert(@text@);",
           [_slot("text", "message", "string", "Done")]),
    _block("js.confirm", "Basics", "ask yes or no",
           "const @name@ = confirm(@text@);",
           [_slot("name", "keep it in", "name", "sure"),
            _slot("text", "question", "string", "Are you sure?")]),
    _block("js.prompt", "Basics", "ask for text",
           "const @name@ = prompt(@text@);",
           [_slot("name", "keep it in", "name", "answer"),
            _slot("text", "question", "string", "Your name?")]),
    _block("js.use_strict", "Basics", "strict mode", "'use strict';"),

    # -- Variables ---------------------------------------------------------
    _block("js.const", "Variables", "a value that never changes",
           "const @name@ = @value@;",
           [_slot("name", "name", "name", "total"), _slot("value", "value", "text", "0")]),
    _block("js.let", "Variables", "a value that changes",
           "let @name@ = @value@;",
           [_slot("name", "name", "name", "count"), _slot("value", "value", "text", "0")]),
    _block("js.const_text", "Variables", "text", "const @name@ = @text@;",
           [_slot("name", "name", "name", "title"), _slot("text", "text", "string", "Hello")]),
    _block("js.const_number", "Variables", "a number", "const @name@ = @number@;",
           [_slot("name", "name", "name", "score"), _slot("number", "number", "number", "0")]),
    _block("js.const_bool", "Variables", "true or false", "let @name@ = @value@;",
           [_slot("name", "name", "name", "ready"),
            _slot("value", "value", "choice", "true", ["true", "false"])]),
    _block("js.assign", "Variables", "change a value", "@name@ = @value@;",
           [_slot("name", "name", "name", "count"), _slot("value", "value", "text", "1")]),
    _block("js.increase", "Variables", "add to a number", "@name@ += @amount@;",
           [_slot("name", "name", "name", "score"), _slot("amount", "by", "number", "1")]),
    _block("js.decrease", "Variables", "take away from a number",
           "@name@ -= @amount@;",
           [_slot("name", "name", "name", "lives"), _slot("amount", "by", "number", "1")]),
    _block("js.plus_plus", "Variables", "add one", "@name@++;",
           [_slot("name", "name", "name", "count")]),

    # -- Maths -------------------------------------------------------------
    _block("js.add", "Maths", "add", "const @name@ = @a@ + @b@;",
           [_slot("name", "keep it in", "name", "total"), _slot("a", "first", "text", "a"),
            _slot("b", "second", "text", "b")]),
    _block("js.maths", "Maths", "any sum", "const @name@ = @a@ @op@ @b@;",
           [_slot("name", "keep it in", "name", "answer"), _slot("a", "first", "text", "a"),
            _slot("op", "operator", "choice", "+", ["+", "-", "*", "/", "%", "**"]),
            _slot("b", "second", "text", "b")]),
    _block("js.round", "Maths", "round a number",
           "const @name@ = Math.round(@value@);",
           [_slot("name", "keep it in", "name", "rounded"), _slot("value", "number", "text", "value")]),
    _block("js.floor", "Maths", "round down",
           "const @name@ = Math.floor(@value@);",
           [_slot("name", "keep it in", "name", "whole"), _slot("value", "number", "text", "value")]),
    _block("js.random", "Maths", "a random whole number",
           "const @name@ = Math.floor(Math.random() * @range@) + @low@;",
           [_slot("name", "keep it in", "name", "roll"), _slot("range", "how many", "number", "6"),
            _slot("low", "starting at", "number", "1")]),
    _block("js.min_max", "Maths", "the smallest or largest",
           "const @name@ = Math.@which@(@a@, @b@);",
           [_slot("name", "keep it in", "name", "picked"),
            _slot("which", "which", "choice", "min", ["min", "max"]),
            _slot("a", "first", "text", "a"), _slot("b", "second", "text", "b")]),
    _block("js.to_number", "Maths", "as a number", "const @name@ = Number(@value@);",
           [_slot("name", "keep it in", "name", "count"), _slot("value", "value", "text", "text")]),
    _block("js.fixed", "Maths", "with a set number of decimals",
           "const @name@ = @value@.toFixed(@places@);",
           [_slot("name", "keep it in", "name", "price"), _slot("value", "number", "text", "value"),
            _slot("places", "decimals", "number", "2")]),

    # -- Text --------------------------------------------------------------
    _block("js.template", "Text", "build a sentence",
           "const @name@ = `@text@`;",
           [_slot("name", "keep it in", "name", "line"),
            _slot("text", "text, with ${name} in it", "inline", "Hello ${name}")]),
    _block("js.upper", "Text", "in capitals",
           "const @name@ = @value@.toUpperCase();",
           [_slot("name", "keep it in", "name", "shout"), _slot("value", "text", "text", "line")]),
    _block("js.lower", "Text", "in lower case",
           "const @name@ = @value@.toLowerCase();",
           [_slot("name", "keep it in", "name", "quiet"), _slot("value", "text", "text", "line")]),
    _block("js.trim", "Text", "without the spaces around it",
           "const @name@ = @value@.trim();",
           [_slot("name", "keep it in", "name", "clean"), _slot("value", "text", "text", "line")]),
    _block("js.replace", "Text", "with something swapped",
           "const @name@ = @value@.replaceAll(@old@, @new@);",
           [_slot("name", "keep it in", "name", "fixed"), _slot("value", "text", "text", "line"),
            _slot("old", "find", "string", "cat"), _slot("new", "replace with", "string", "dog")]),
    _block("js.split", "Text", "split into a list",
           "const @name@ = @value@.split(@separator@);",
           [_slot("name", "keep it in", "name", "parts"), _slot("value", "text", "text", "line"),
            _slot("separator", "split on", "string", ",")]),
    _block("js.join", "Text", "join a list into text",
           "const @name@ = @list@.join(@separator@);",
           [_slot("name", "keep it in", "name", "line"), _slot("list", "list", "name", "items"),
            _slot("separator", "between them", "string", ", ")]),
    _block("js.length", "Text", "how long it is",
           "const @name@ = @value@.length;",
           [_slot("name", "keep it in", "name", "count"),
            _slot("value", "text or list", "text", "line")]),
    _block("js.includes", "Text", "does it contain",
           "const @name@ = @value@.includes(@needle@);",
           [_slot("name", "keep it in", "name", "found"), _slot("value", "text or list", "text", "line"),
            _slot("needle", "look for", "string", "cat")]),
    _block("js.slice", "Text", "a piece of it",
           "const @name@ = @value@.slice(@start@, @end@);",
           [_slot("name", "keep it in", "name", "piece"), _slot("value", "text or list", "text", "line"),
            _slot("start", "from", "number", "0"), _slot("end", "to", "number", "5")]),
    _block("js.to_string", "Text", "as text", "const @name@ = String(@value@);",
           [_slot("name", "keep it in", "name", "text"), _slot("value", "value", "text", "number")]),

    # -- Arrays ------------------------------------------------------------
    _block("js.new_array", "Arrays", "a new list", "const @name@ = [@items@];",
           [_slot("name", "name", "name", "items"),
            _slot("items", "items, comma separated", "text", "")]),
    _block("js.push", "Arrays", "add to the end", "@list@.push(@value@);",
           [_slot("list", "list", "name", "items"), _slot("value", "value", "text", "item")]),
    _block("js.pop", "Arrays", "take the last one off",
           "const @name@ = @list@.pop();",
           [_slot("name", "keep it in", "name", "last"), _slot("list", "list", "name", "items")]),
    _block("js.shift", "Arrays", "take the first one off",
           "const @name@ = @list@.shift();",
           [_slot("name", "keep it in", "name", "first"), _slot("list", "list", "name", "items")]),
    _block("js.at", "Arrays", "the item at", "const @name@ = @list@[@index@];",
           [_slot("name", "keep it in", "name", "item"), _slot("list", "list", "name", "items"),
            _slot("index", "position", "number", "0")]),
    _block("js.set_at", "Arrays", "replace the item at",
           "@list@[@index@] = @value@;",
           [_slot("list", "list", "name", "items"), _slot("index", "position", "number", "0"),
            _slot("value", "value", "text", "item")]),
    _block("js.index_of", "Arrays", "where it is",
           "const @name@ = @list@.indexOf(@value@);",
           [_slot("name", "keep it in", "name", "at"), _slot("list", "list", "name", "items"),
            _slot("value", "value", "text", "item")]),
    _block("js.map", "Arrays", "a list built from another",
           "const @name@ = @list@.map((@item@) => @expression@);",
           [_slot("name", "keep it in", "name", "doubled"), _slot("list", "from", "name", "items"),
            _slot("item", "each is called", "name", "item"),
            _slot("expression", "each becomes", "text", "item * 2")]),
    _block("js.filter", "Arrays", "only the ones that match",
           "const @name@ = @list@.filter((@item@) => @condition@);",
           [_slot("name", "keep it in", "name", "big"), _slot("list", "from", "name", "items"),
            _slot("item", "each is called", "name", "item"),
            _slot("condition", "keep when", "text", "item > 10")]),
    _block("js.reduce", "Arrays", "add a list up",
           "const @name@ = @list@.reduce((a, b) => a + b, 0);",
           [_slot("name", "keep it in", "name", "total"), _slot("list", "list", "name", "items")]),
    _block("js.sort", "Arrays", "put in order", "@list@.sort();",
           [_slot("list", "list", "name", "items")]),
    _block("js.reverse", "Arrays", "turn it round", "@list@.reverse();",
           [_slot("list", "list", "name", "items")]),

    # -- Objects -----------------------------------------------------------
    _block("js.object", "Objects", "a new object",
           "const @name@ = {@pairs@};",
           [_slot("name", "name", "name", "person"),
            _slot("pairs", "key: value pairs", "text", "name: 'Ada', age: 36")]),
    _block("js.object_set", "Objects", "set a key",
           "@object@.@key@ = @value@;",
           [_slot("object", "object", "name", "person"), _slot("key", "key", "name", "name"),
            _slot("value", "value", "text", "'Ada'")]),
    _block("js.object_get", "Objects", "read a key",
           "const @name@ = @object@.@key@;",
           [_slot("name", "keep it in", "name", "value"), _slot("object", "object", "name", "person"),
            _slot("key", "key", "name", "name")]),
    _block("js.object_keys", "Objects", "all the keys",
           "const @name@ = Object.keys(@object@);",
           [_slot("name", "keep it in", "name", "keys"), _slot("object", "object", "name", "person")]),
    _block("js.json_stringify", "Objects", "turn into JSON text",
           "const @name@ = JSON.stringify(@value@, null, 2);",
           [_slot("name", "keep it in", "name", "text"), _slot("value", "value", "text", "data")]),
    _block("js.json_parse", "Objects", "read JSON text",
           "const @name@ = JSON.parse(@text@);",
           [_slot("name", "keep it in", "name", "data"), _slot("text", "text", "text", "body")]),

    # -- Logic -------------------------------------------------------------
    _block("js.if", "Logic", "if", "if (@condition@) {",
           [_slot("condition", "when", "text", "score > 10")], close="}", wrap=True),
    _block("js.if_equals", "Logic", "if two things are the same",
           "if (@a@ === @b@) {",
           [_slot("a", "this", "text", "answer"), _slot("b", "is", "text", "'yes'")],
           close="}", wrap=True),
    _block("js.if_compare", "Logic", "if, comparing two things",
           "if (@a@ @op@ @b@) {",
           [_slot("a", "this", "text", "score"),
            _slot("op", "compared", "choice", ">", ["===", "!==", "<", ">", "<=", ">="]),
            _slot("b", "to", "text", "10")],
           close="}", wrap=True),
    _block("js.else", "Logic", "otherwise", "} else {", close="}", wrap=True,
           about="Put this straight after an if block."),
    _block("js.else_if", "Logic", "or else if", "} else if (@condition@) {",
           [_slot("condition", "when", "text", "score > 5")], close="}", wrap=True),
    _block("js.ternary", "Logic", "one thing or the other",
           "const @name@ = @condition@ ? @yes@ : @no@;",
           [_slot("name", "keep it in", "name", "label"),
            _slot("condition", "when", "text", "score > 10"),
            _slot("yes", "then", "text", "'high'"), _slot("no", "otherwise", "text", "'low'")]),
    _block("js.not", "Logic", "the opposite", "const @name@ = !@value@;",
           [_slot("name", "keep it in", "name", "missing"), _slot("value", "of", "text", "found")]),

    # -- Loops -------------------------------------------------------------
    _block("js.repeat", "Loops", "repeat this many times",
           "for (let @var@ = 0; @var@ < @times@; @var@++) {",
           [_slot("var", "counter", "name", "i"), _slot("times", "times", "number", "10")],
           close="}", wrap=True),
    _block("js.for_of", "Loops", "for each item in a list",
           "for (const @item@ of @list@) {",
           [_slot("item", "each is called", "name", "item"), _slot("list", "in", "name", "items")],
           close="}", wrap=True),
    _block("js.for_each", "Loops", "for each item, with its position",
           "@list@.forEach((@item@, @index@) => {",
           [_slot("list", "list", "name", "items"), _slot("item", "each is called", "name", "item"),
            _slot("index", "position is called", "name", "index")],
           close="});", wrap=True),
    _block("js.while", "Loops", "keep going while", "while (@condition@) {",
           [_slot("condition", "while", "text", "running")], close="}", wrap=True),
    _block("js.break", "Loops", "stop the loop", "break;"),
    _block("js.continue", "Loops", "skip to the next time round", "continue;"),

    # -- Functions ---------------------------------------------------------
    _block("js.function", "Functions", "define a function",
           "function @name@(@params@) {",
           [_slot("name", "called", "name", "greet"), _slot("params", "taking", "text", "name")],
           close="}", wrap=True),
    _block("js.arrow", "Functions", "define a short function",
           "const @name@ = (@params@) => {",
           [_slot("name", "called", "name", "greet"), _slot("params", "taking", "text", "name")],
           close="};", wrap=True),
    _block("js.async", "Functions", "define a function that waits",
           "async function @name@(@params@) {",
           [_slot("name", "called", "name", "load"), _slot("params", "taking", "text", "")],
           close="}", wrap=True),
    _block("js.return", "Functions", "give an answer back", "return @value@;",
           [_slot("value", "answer", "text", "result")]),
    _block("js.call", "Functions", "run a function", "@name@(@args@);",
           [_slot("name", "function", "name", "greet"), _slot("args", "with", "text", "'Ada'")]),
    _block("js.call_keep", "Functions", "run a function and keep the answer",
           "const @result@ = @name@(@args@);",
           [_slot("result", "keep it in", "name", "answer"),
            _slot("name", "function", "name", "greet"), _slot("args", "with", "text", "'Ada'")]),
    _block("js.await", "Functions", "wait for an answer",
           "const @name@ = await @call@;",
           [_slot("name", "keep it in", "name", "data"),
            _slot("call", "waiting for", "text", "load()")]),

    # -- The page ----------------------------------------------------------
    _block("js.find", "Page", "find an element",
           "const @name@ = document.querySelector(@selector@);",
           [_slot("name", "keep it in", "name", "box"),
            _slot("selector", "selector", "string", "#out")]),
    _block("js.find_all", "Page", "find every matching element",
           "const @name@ = document.querySelectorAll(@selector@);",
           [_slot("name", "keep it in", "name", "boxes"),
            _slot("selector", "selector", "string", ".item")]),
    _block("js.set_text", "Page", "set an element's text",
           "@element@.textContent = @text@;",
           [_slot("element", "element", "name", "box"), _slot("text", "text", "text", "message")]),
    _block("js.set_html", "Page", "set an element's contents",
           "@element@.innerHTML = @html@;",
           [_slot("element", "element", "name", "box"), _slot("html", "html", "text", "markup")]),
    _block("js.set_style", "Page", "change how an element looks",
           "@element@.style.@property@ = @value@;",
           [_slot("element", "element", "name", "box"),
            _slot("property", "property", "name", "color"),
            _slot("value", "value", "string", "red")]),
    _block("js.add_class", "Page", "add a class",
           "@element@.classList.add(@name@);",
           [_slot("element", "element", "name", "box"), _slot("name", "class", "string", "active")]),
    _block("js.remove_class", "Page", "remove a class",
           "@element@.classList.remove(@name@);",
           [_slot("element", "element", "name", "box"), _slot("name", "class", "string", "active")]),
    _block("js.toggle_class", "Page", "turn a class on or off",
           "@element@.classList.toggle(@name@);",
           [_slot("element", "element", "name", "box"), _slot("name", "class", "string", "active")]),
    _block("js.create", "Page", "make an element",
           "const @name@ = document.createElement(@tag@);",
           [_slot("name", "keep it in", "name", "row"), _slot("tag", "tag", "string", "div")]),
    _block("js.append", "Page", "put it inside another",
           "@parent@.appendChild(@child@);",
           [_slot("parent", "inside", "name", "list"), _slot("child", "put in", "name", "row")]),
    _block("js.remove_element", "Page", "take an element out",
           "@element@.remove();",
           [_slot("element", "element", "name", "row")]),
    _block("js.value_of", "Page", "read an input",
           "const @name@ = @element@.value;",
           [_slot("name", "keep it in", "name", "typed"), _slot("element", "input", "name", "box")]),

    # -- Events and time ---------------------------------------------------
    _block("js.on_click", "Events", "when this is clicked",
           "@element@.addEventListener('click', () => {",
           [_slot("element", "element", "name", "button")], close="});", wrap=True),
    _block("js.on_event", "Events", "when something happens",
           "@element@.addEventListener(@event@, (event) => {",
           [_slot("element", "element", "name", "box"),
            _slot("event", "event", "choice", "'input'",
                  ["'input'", "'change'", "'submit'", "'keydown'", "'mouseover'", "'scroll'"])],
           close="});", wrap=True),
    _block("js.on_load", "Events", "when the page is ready",
           "window.addEventListener('DOMContentLoaded', () => {",
           close="});", wrap=True),
    _block("js.prevent", "Events", "stop the usual behaviour",
           "event.preventDefault();"),
    _block("js.after", "Events", "after a delay",
           "setTimeout(() => {",
           [_slot("delay", "milliseconds", "number", "1000")],
           close="}, @delay@);", wrap=True),
    _block("js.every", "Events", "over and over",
           "setInterval(() => {",
           [_slot("delay", "milliseconds", "number", "1000")],
           close="}, @delay@);", wrap=True),

    # -- Fetching ----------------------------------------------------------
    _block("js.fetch", "Fetch", "fetch JSON",
           "const @name@ = await (await fetch(@url@)).json();",
           [_slot("name", "keep it in", "name", "data"),
            _slot("url", "address", "string", "/api")]),
    _block("js.fetch_text", "Fetch", "fetch text",
           "const @name@ = await (await fetch(@url@)).text();",
           [_slot("name", "keep it in", "name", "body"),
            _slot("url", "address", "string", "/page")]),
    _block("js.post", "Fetch", "send JSON",
           "const @name@ = await fetch(@url@, { method: 'POST', "
           "headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(@data@) });",
           [_slot("name", "keep it in", "name", "reply"),
            _slot("url", "address", "string", "/api"), _slot("data", "send", "text", "payload")]),
    _block("js.try", "Fetch", "try this", "try {", close="} catch (error) {", wrap=True,
           about="Follow it with a catch block."),
    _block("js.catch", "Fetch", "if it went wrong", "} catch (error) {", close="}", wrap=True),
]


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

HTML = [
    # -- The document ------------------------------------------------------
    _block("html.doctype", "Document", "start of an HTML file", "<!doctype html>"),
    _block("html.page", "Document", "a whole page",
           '<html lang="@lang@">',
           [_slot("lang", "language", "string", "en")], close="</html>", wrap=True),
    _block("html.head", "Document", "the head", "<head>", close="</head>", wrap=True),
    _block("html.body", "Document", "the body", "<body>", close="</body>", wrap=True),
    _block("html.title", "Document", "the page title", "<title>@text@</title>",
           [_slot("text", "title", "string", "My page")]),
    _block("html.charset", "Document", "character set", '<meta charset="utf-8">'),
    _block("html.viewport", "Document", "fit the phone screen",
           '<meta name="viewport" content="width=device-width, initial-scale=1">'),
    _block("html.stylesheet", "Document", "use a stylesheet",
           '<link rel="stylesheet" href="@href@">',
           [_slot("href", "file", "string", "style.css")]),
    _block("html.script_src", "Document", "use a script",
           '<script src="@src@"></script>',
           [_slot("src", "file", "string", "app.js")]),
    _block("html.comment", "Document", "a note to yourself", "<!-- @text@ -->",
           [_slot("text", "note", "text", "what this part is")]),
    _block("html.blank", "Document", "an empty line", ""),

    # -- Text --------------------------------------------------------------
    _block("html.h1", "Text", "big heading", "<h1>@text@</h1>",
           [_slot("text", "text", "string", "Hello")]),
    _block("html.h2", "Text", "heading", "<h2>@text@</h2>",
           [_slot("text", "text", "string", "A section")]),
    _block("html.h3", "Text", "small heading", "<h3>@text@</h3>",
           [_slot("text", "text", "string", "A part")]),
    _block("html.p", "Text", "a paragraph", "<p>@text@</p>",
           [_slot("text", "text", "string", "Some words.")]),
    _block("html.span", "Text", "a piece of text with a name",
           '<span id="@id@">@text@</span>',
           [_slot("id", "id", "string", "out"), _slot("text", "text", "string", "")]),
    _block("html.strong", "Text", "bold", "<strong>@text@</strong>",
           [_slot("text", "text", "string", "important")]),
    _block("html.em", "Text", "italic", "<em>@text@</em>",
           [_slot("text", "text", "string", "gently")]),
    _block("html.br", "Text", "a line break", "<br>"),
    _block("html.hr", "Text", "a dividing line", "<hr>"),
    _block("html.pre", "Text", "code, kept as typed",
           '<pre id="@id@">@text@</pre>',
           [_slot("id", "id", "string", "out"), _slot("text", "text", "string", "")]),

    # -- Structure ---------------------------------------------------------
    _block("html.div", "Structure", "a box", '<div class="@class@">',
           [_slot("class", "class", "string", "card")], close="</div>", wrap=True),
    _block("html.div_id", "Structure", "a box with an id", '<div id="@id@">',
           [_slot("id", "id", "string", "app")], close="</div>", wrap=True),
    _block("html.section", "Structure", "a section", "<section>", close="</section>",
           wrap=True),
    _block("html.header", "Structure", "a header", "<header>", close="</header>", wrap=True),
    _block("html.footer", "Structure", "a footer", "<footer>", close="</footer>", wrap=True),
    _block("html.nav", "Structure", "navigation", "<nav>", close="</nav>", wrap=True),
    _block("html.main", "Structure", "the main part", "<main>", close="</main>", wrap=True),
    _block("html.style", "Structure", "styles, written here",
           "<style>", close="</style>", wrap=True),
    _block("html.script", "Structure", "a script, written here",
           "<script>", close="</script>", wrap=True),

    # -- Links, media and lists --------------------------------------------
    _block("html.link", "Links", "a link", '<a href="@href@">@text@</a>',
           [_slot("href", "address", "string", "https://example.com"),
            _slot("text", "text", "string", "Go there")]),
    _block("html.image", "Links", "an image", '<img src="@src@" alt="@alt@">',
           [_slot("src", "file", "string", "picture.png"),
            _slot("alt", "description", "string", "a picture")]),
    _block("html.audio", "Links", "a sound player",
           '<audio controls src="@src@"></audio>',
           [_slot("src", "file", "string", "song.mp3")]),
    _block("html.video", "Links", "a video player",
           '<video controls width="100%" src="@src@"></video>',
           [_slot("src", "file", "string", "clip.mp4")]),
    _block("html.ul", "Links", "a bullet list", "<ul>", close="</ul>", wrap=True),
    _block("html.ol", "Links", "a numbered list", "<ol>", close="</ol>", wrap=True),
    _block("html.li", "Links", "a list item", "<li>@text@</li>",
           [_slot("text", "text", "string", "an item")]),
    _block("html.table", "Links", "a table", "<table>", close="</table>", wrap=True),
    _block("html.tr", "Links", "a table row", "<tr>", close="</tr>", wrap=True),
    _block("html.td", "Links", "a table cell", "<td>@text@</td>",
           [_slot("text", "text", "string", "value")]),
    _block("html.th", "Links", "a table heading cell", "<th>@text@</th>",
           [_slot("text", "text", "string", "Name")]),

    # -- Forms -------------------------------------------------------------
    _block("html.button", "Forms", "a button",
           '<button id="@id@">@text@</button>',
           [_slot("id", "id", "string", "go"), _slot("text", "text", "string", "Press me")]),
    _block("html.input", "Forms", "a text box",
           '<input id="@id@" type="@type@" placeholder="@placeholder@">',
           [_slot("id", "id", "string", "name"),
            _slot("type", "kind", "choice", "text",
                  ["text", "number", "email", "password", "search", "date", "color", "range"]),
            _slot("placeholder", "hint", "string", "Type here")]),
    _block("html.textarea", "Forms", "a big text box",
           '<textarea id="@id@" rows="@rows@"></textarea>',
           [_slot("id", "id", "string", "notes"), _slot("rows", "lines", "number", "5")]),
    _block("html.checkbox", "Forms", "a tick box",
           '<label><input id="@id@" type="checkbox"> @text@</label>',
           [_slot("id", "id", "string", "agree"), _slot("text", "label", "string", "I agree")]),
    _block("html.select", "Forms", "a drop-down", '<select id="@id@">',
           [_slot("id", "id", "string", "choice")], close="</select>", wrap=True),
    _block("html.option", "Forms", "a drop-down choice",
           '<option value="@value@">@text@</option>',
           [_slot("value", "value", "string", "one"), _slot("text", "text", "string", "One")]),
    _block("html.label", "Forms", "a label for a box",
           '<label for="@for@">@text@</label>',
           [_slot("for", "for id", "string", "name"), _slot("text", "text", "string", "Your name")]),
    _block("html.form", "Forms", "a form", '<form id="@id@">',
           [_slot("id", "id", "string", "form")], close="</form>", wrap=True),
]


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

CSS = [
    # -- Rules -------------------------------------------------------------
    _block("css.rule", "Rules", "style an element", "@selector@ {",
           [_slot("selector", "selector", "string", "body")], close="}", wrap=True),
    _block("css.class", "Rules", "style a class", ".@name@ {",
           [_slot("name", "class", "string", "card")], close="}", wrap=True),
    _block("css.id", "Rules", "style one element", "#@name@ {",
           [_slot("name", "id", "string", "app")], close="}", wrap=True),
    _block("css.hover", "Rules", "style it when touched", "@selector@:hover {",
           [_slot("selector", "selector", "string", "button")], close="}", wrap=True),
    _block("css.media", "Rules", "style it on small screens",
           "@@media (max-width: @width@px) {",
           [_slot("width", "up to", "number", "600")], close="}", wrap=True),
    _block("css.root", "Rules", "colours used everywhere", ":root {", close="}", wrap=True),
    _block("css.variable", "Rules", "name a value", "--@name@: @value@;",
           [_slot("name", "name", "string", "accent"), _slot("value", "value", "string", "#2E7DD1")]),
    _block("css.comment", "Rules", "a note to yourself", "/* @text@ */",
           [_slot("text", "note", "text", "what this part does")]),
    _block("css.blank", "Rules", "an empty line", ""),

    # -- Text --------------------------------------------------------------
    _block("css.color", "Text", "text colour", "color: @value@;",
           [_slot("value", "colour", "string", "#DCE3EC")]),
    _block("css.font_size", "Text", "text size", "font-size: @value@;",
           [_slot("value", "size", "string", "16px")]),
    _block("css.font_family", "Text", "typeface", "font-family: @value@;",
           [_slot("value", "fonts", "string", "system-ui, sans-serif")]),
    _block("css.font_weight", "Text", "how bold", "font-weight: @value@;",
           [_slot("value", "weight", "choice", "600",
                  ["400", "500", "600", "700", "bold", "normal"])]),
    _block("css.text_align", "Text", "line up the text", "text-align: @value@;",
           [_slot("value", "align", "choice", "center",
                  ["left", "center", "right", "justify"])]),
    _block("css.line_height", "Text", "space between lines", "line-height: @value@;",
           [_slot("value", "height", "string", "1.6")]),
    _block("css.text_decoration", "Text", "underline or not",
           "text-decoration: @value@;",
           [_slot("value", "decoration", "choice", "none", ["none", "underline", "line-through"])]),
    _block("css.letter_spacing", "Text", "space between letters",
           "letter-spacing: @value@;",
           [_slot("value", "spacing", "string", "0.02em")]),

    # -- The box -----------------------------------------------------------
    _block("css.margin", "Box", "space outside", "margin: @value@;",
           [_slot("value", "space", "string", "0 auto")]),
    _block("css.padding", "Box", "space inside", "padding: @value@;",
           [_slot("value", "space", "string", "16px")]),
    _block("css.width", "Box", "width", "width: @value@;",
           [_slot("value", "width", "string", "100%")]),
    _block("css.max_width", "Box", "widest it gets", "max-width: @value@;",
           [_slot("value", "width", "string", "720px")]),
    _block("css.height", "Box", "height", "height: @value@;",
           [_slot("value", "height", "string", "auto")]),
    _block("css.border", "Box", "a border", "border: @value@;",
           [_slot("value", "border", "string", "1px solid #223041")]),
    _block("css.radius", "Box", "rounded corners", "border-radius: @value@;",
           [_slot("value", "radius", "string", "12px")]),
    _block("css.box_shadow", "Box", "a shadow", "box-shadow: @value@;",
           [_slot("value", "shadow", "string", "0 2px 12px rgba(0,0,0,.35)")]),
    _block("css.overflow", "Box", "what happens when it does not fit",
           "overflow: @value@;",
           [_slot("value", "overflow", "choice", "auto", ["auto", "hidden", "scroll", "visible"])]),

    # -- Colour ------------------------------------------------------------
    _block("css.background", "Colour", "background colour", "background: @value@;",
           [_slot("value", "colour", "string", "#0B0F14")]),
    _block("css.gradient", "Colour", "a colour fade",
           "background: linear-gradient(@angle@, @from@, @to@);",
           [_slot("angle", "direction", "string", "180deg"),
            _slot("from", "from", "string", "#16324D"), _slot("to", "to", "string", "#0B0F14")]),
    _block("css.opacity", "Colour", "how see-through", "opacity: @value@;",
           [_slot("value", "0 to 1", "string", "0.8")]),
    _block("css.background_image", "Colour", "a background picture",
           'background-image: url("@src@");',
           [_slot("src", "file", "string", "picture.png")]),

    # -- Layout ------------------------------------------------------------
    _block("css.display", "Layout", "how it lays out", "display: @value@;",
           [_slot("value", "display", "choice", "flex",
                  ["flex", "grid", "block", "inline-block", "none"])]),
    _block("css.flex_direction", "Layout", "which way things stack",
           "flex-direction: @value@;",
           [_slot("value", "direction", "choice", "column", ["row", "column"])]),
    _block("css.justify", "Layout", "line up along the row",
           "justify-content: @value@;",
           [_slot("value", "align", "choice", "center",
                  ["flex-start", "center", "flex-end", "space-between", "space-around"])]),
    _block("css.align", "Layout", "line up across the row", "align-items: @value@;",
           [_slot("value", "align", "choice", "center",
                  ["flex-start", "center", "flex-end", "stretch"])]),
    _block("css.gap", "Layout", "space between things", "gap: @value@;",
           [_slot("value", "gap", "string", "12px")]),
    _block("css.grid_columns", "Layout", "columns in a grid",
           "grid-template-columns: repeat(@count@, 1fr);",
           [_slot("count", "how many", "number", "3")]),
    _block("css.position", "Layout", "how it is placed", "position: @value@;",
           [_slot("value", "position", "choice", "relative",
                  ["static", "relative", "absolute", "fixed", "sticky"])]),
    _block("css.z_index", "Layout", "what sits on top", "z-index: @value@;",
           [_slot("value", "layer", "number", "10")]),

    # -- Effects -----------------------------------------------------------
    _block("css.transition", "Effects", "make changes smooth",
           "transition: @value@;",
           [_slot("value", "transition", "string", "all .2s ease")]),
    _block("css.transform", "Effects", "move, turn or scale",
           "transform: @value@;",
           [_slot("value", "transform", "string", "scale(1.05)")]),
    _block("css.cursor", "Effects", "the pointer over it", "cursor: @value@;",
           [_slot("value", "cursor", "choice", "pointer", ["pointer", "default", "text", "grab"])]),
    _block("css.property", "Effects", "any property at all", "@property@: @value@;",
           [_slot("property", "property", "string", "filter"),
            _slot("value", "value", "string", "blur(2px)")]),
]


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

MARKDOWN = [
    _block("md.h1", "Headings", "title", "# @text@",
           [_slot("text", "text", "string", "My notes")]),
    _block("md.h2", "Headings", "heading", "## @text@",
           [_slot("text", "text", "string", "A section")]),
    _block("md.h3", "Headings", "small heading", "### @text@",
           [_slot("text", "text", "string", "A part")]),
    _block("md.text", "Text", "a paragraph", "@text@",
           [_slot("text", "text", "string", "Some words.")]),
    _block("md.blank", "Text", "an empty line", ""),
    _block("md.bold", "Text", "bold text", "**@text@**",
           [_slot("text", "text", "string", "important")]),
    _block("md.italic", "Text", "italic text", "*@text@*",
           [_slot("text", "text", "string", "gently")]),
    _block("md.quote", "Text", "a quote", "> @text@",
           [_slot("text", "text", "string", "somebody said this")]),
    _block("md.rule", "Text", "a dividing line", "---"),
    _block("md.bullet", "Lists", "a bullet", "- @text@",
           [_slot("text", "text", "string", "an item")]),
    _block("md.numbered", "Lists", "a numbered item", "@number@. @text@",
           [_slot("number", "number", "number", "1"),
            _slot("text", "text", "string", "an item")]),
    _block("md.task", "Lists", "a thing to do", "- [ ] @text@",
           [_slot("text", "text", "string", "something to do")]),
    _block("md.task_done", "Lists", "a thing already done", "- [x] @text@",
           [_slot("text", "text", "string", "something finished")]),
    _block("md.link", "Links", "a link", "[@text@](@href@)",
           [_slot("text", "text", "string", "Go there"),
            _slot("href", "address", "string", "https://example.com")]),
    _block("md.image", "Links", "an image", "![@alt@](@src@)",
           [_slot("alt", "description", "string", "a picture"),
            _slot("src", "file", "string", "picture.png")]),
    _block("md.code_inline", "Code", "a bit of code", "`@text@`",
           [_slot("text", "code", "string", "print()")]),
    _block("md.code_open", "Code", "a block of code", "```@language@",
           [_slot("language", "language", "string", "python")], close="```", wrap=True),
    _block("md.table_head", "Code", "a table heading row",
           "| @a@ | @b@ |",
           [_slot("a", "first column", "string", "Name"),
            _slot("b", "second column", "string", "Value")]),
    _block("md.table_divider", "Code", "the line under a table heading",
           "|---|---|"),
    _block("md.table_row", "Code", "a table row", "| @a@ | @b@ |",
           [_slot("a", "first", "string", "one"), _slot("b", "second", "string", "1")]),
]


BLOCKS = {
    "python": PYTHON,
    "javascript": JAVASCRIPT,
    "html": HTML,
    "css": CSS,
    "markdown": MARKDOWN,
}

BY_ID = {row["id"]: row for rows in BLOCKS.values() for row in rows}

# Which language each block belongs to, so a project cannot quietly use a
# Python block in a CSS file and produce something that is neither.
LANGUAGE_OF = {
    row["id"]: language for language, rows in BLOCKS.items() for row in rows
}


# ---------------------------------------------------------------------------
# Reading the catalogue
# ---------------------------------------------------------------------------


def block(block_id: str):
    """One block by id, or None."""
    return BY_ID.get(str(block_id))


def catalogue(language: str = "") -> dict:
    """The blocks for one language, grouped the way the palette shows them.

    Called once when the panel opens. Three hundred and sixty blocks is a lot
    of JSON to hand across a bridge, so the panel asks for one language at a
    time - which is also all it can show at once, since a project is written
    in one language.
    """
    language = str(language or "").strip().lower()
    if language and language not in BLOCKS:
        return {"ok": False, "error": f"no blocks for {language}", "languages": LANGUAGES}

    wanted = [language] if language else LANGUAGE_IDS
    groups = []
    total = 0
    for name in wanted:
        rows = BLOCKS[name]
        total += len(rows)
        categories = []
        for row in rows:
            if not categories or categories[-1]["name"] != row["cat"]:
                categories.append({"name": row["cat"], "blocks": []})
            categories[-1]["blocks"].append(row)
        groups.append({"language": name, "categories": categories, "count": len(rows)})

    return {
        "ok": True,
        "languages": LANGUAGES,
        "groups": groups,
        "count": total,
        "limits": {"blocks": MAX_BLOCKS, "depth": MAX_DEPTH},
    }


# ---------------------------------------------------------------------------
# Turning a project into a file
# ---------------------------------------------------------------------------

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Languages where a `string` slot is written with quotes round it. In HTML and
# CSS the template already carries whatever quoting the syntax needs.
QUOTED = {"python", "javascript"}


def _clean(value) -> str:
    """One line, no control characters, and not a whole file long."""
    text = "" if value is None else str(value)
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return _CONTROL.sub("", text)[:MAX_VALUE]


def _escaped(raw: str, language: str) -> str:
    """Makes a piece of text safe for the syntax it is about to land in.

    Every one of these is a line that would otherwise break the moment
    somebody typed a quote into a hole, which is a thing people do constantly:
    names have apostrophes, sentences have quotation marks, and Windows paths
    are made of backslashes.
    """
    if language == "python":
        return raw.replace("\\", "\\\\").replace('"', '\\"')
    if language == "javascript":
        # Template literals and quoted strings both take these two; a `${` is
        # left alone because a block whose label says "with ${name} in it"
        # means it.
        return raw.replace("\\", "\\\\").replace("`", "\\`").replace('"', '\\"')
    if language == "html":
        return (raw.replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;").replace('"', "&quot;"))
    if language == "css":
        # A brace cannot appear in a declaration, and one typed into a value
        # would close the rule and leave the rest of the file inside nothing.
        return raw.replace("{", "").replace("}", "")
    return raw


def _value_for(slot: dict, given, language: str) -> str:
    kind = slot.get("kind", "text")
    raw = _clean(given if given is not None else slot.get("default", ""))

    if kind == "choice":
        options = slot.get("options") or []
        if raw not in options:
            raw = str(slot.get("default") or (options[0] if options else ""))
        return raw

    if kind == "number":
        stripped = raw.strip()
        if not stripped:
            return "0"
        return stripped

    if kind in ("string", "inline"):
        body = _escaped(raw, language)
        if kind == "string" and language in QUOTED:
            return f'"{body}"'
        return body

    if kind == "name":
        stripped = raw.strip()
        return stripped or str(slot.get("default") or "value")

    return raw.strip()


def _render(template: str, slots: list, values: dict, language: str,
            problems: list, label: str) -> str:
    """Fills one line's holes, then puts literal `@`s back."""
    by_name = {slot["name"]: slot for slot in slots}

    def swap(match):
        name = match.group(1)
        slot = by_name.get(name)
        if slot is None:
            # A template asking for a slot the block does not declare is a bug
            # in the catalogue, and the test suite fails on it - but at
            # runtime the honest thing is to leave the text alone and say so.
            problems.append(f"{label}: no slot called {name}")
            return match.group(0)
        return _value_for(slot, values.get(name), language)

    filled = PLACEHOLDER.sub(swap, template or "")
    return filled.replace("@@", "@")


def compile_project(project: dict) -> dict:
    """Walks a project's blocks and writes the file they describe.

    Every failure here is reported rather than raised: a project with one bad
    block should still build the other ninety, because the person looking at
    the result is the person who can fix the one.
    """
    project = project if isinstance(project, dict) else {}
    language = str(project.get("language") or "python").strip().lower()
    if language not in BLOCKS:
        return {"ok": False, "error": f"'{language}' is not one of the languages here."}

    meta = next(row for row in LANGUAGES if row["id"] == language)
    indent = meta["indent"]
    lines: list = []
    problems: list = []
    used = 0

    def emit(nodes, depth: int) -> None:
        nonlocal used
        if depth > MAX_DEPTH:
            problems.append(f"nested deeper than {MAX_DEPTH}; stopped there")
            return
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            if used >= MAX_BLOCKS:
                problems.append(f"a project stops at {MAX_BLOCKS} blocks")
                return
            spec = BY_ID.get(str(node.get("block")))
            if spec is None:
                problems.append(f"no block called {node.get('block')}")
                continue
            if LANGUAGE_OF[spec["id"]] != language:
                problems.append(
                    f"{spec['id']} is a {LANGUAGE_OF[spec['id']]} block, not {language}"
                )
                continue

            used += 1
            values = node.get("values") if isinstance(node.get("values"), dict) else {}
            head = _render(spec["open"], spec["slots"], values, language,
                           problems, spec["id"])
            # A block whose whole line is empty is the blank-line block, and a
            # blank line with eight spaces of indentation on it is trailing
            # whitespace nobody asked for.
            lines.append(indent * depth + head if head.strip() else "")

            children = node.get("children") or []
            if spec["wrap"]:
                if children:
                    emit(children, depth + 1)
                elif spec["empty"]:
                    lines.append(indent * (depth + 1) + spec["empty"])
                if spec["close"]:
                    close = _render(spec["close"], spec["slots"], values, language,
                                    problems, spec["id"])
                    lines.append(indent * depth + close if close.strip() else "")
            elif children:
                problems.append(f"{spec['id']} cannot hold blocks; its children were skipped")

    emit(project.get("blocks"), 0)

    code = "\n".join(lines).rstrip("\n")
    if code:
        code += "\n"
    return {
        "ok": True,
        "code": code,
        "language": language,
        "extension": meta["extension"],
        "lines": len(lines),
        "blocks": used,
        "problems": problems,
    }
