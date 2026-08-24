"""Rust's values, and the two ways Rust prints them.

`{}` and `{:?}` are genuinely different - `2.0` prints as `2` under Display and
`2.0` under Debug, a string prints bare under one and quoted under the other -
so both are implemented rather than approximated with one.
"""

from __future__ import annotations

import math


class RustError(Exception):
    """A failure in the program, reported the way the interpreter sees it."""

    def __init__(self, message: str, line: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.line = line

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}" if self.line else self.message


class RustPanic(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Unit:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "()"

    def __eq__(self, other) -> bool:
        return isinstance(other, Unit)

    def __hash__(self) -> int:
        return hash("rust-unit")


UNIT = Unit()


class Char(str):
    """A `char`, which prints and compares differently from a one-char string."""


class Struct:
    __slots__ = ("name", "fields", "shape")

    def __init__(self, name, fields, shape="named") -> None:
        self.name = name
        self.fields = fields
        self.shape = shape          # named, tuple or unit

    def clone(self):
        return Struct(self.name, {k: clone_value(v) for k, v in self.fields.items()}, self.shape)

    def __eq__(self, other) -> bool:
        return isinstance(other, Struct) and self.name == other.name \
            and self.fields == other.fields

    def __hash__(self) -> int:
        return hash((self.name, tuple(sorted(
            (k, v if isinstance(v, (int, float, str, bool)) else id(v))
            for k, v in self.fields.items()
        ))))


class Enum:
    __slots__ = ("enum", "variant", "values", "shape")

    def __init__(self, enum, variant, values=None, shape="tuple") -> None:
        self.enum = enum
        self.variant = variant
        self.values = values if values is not None else []
        self.shape = shape          # tuple, named or unit

    def clone(self):
        if self.shape == "named":
            return Enum(self.enum, self.variant,
                        {k: clone_value(v) for k, v in self.values.items()}, self.shape)
        return Enum(self.enum, self.variant, [clone_value(v) for v in self.values], self.shape)

    def __eq__(self, other) -> bool:
        return isinstance(other, Enum) and self.enum == other.enum \
            and self.variant == other.variant and self.values == other.values

    def __hash__(self) -> int:
        values = tuple(self.values) if isinstance(self.values, list) else \
            tuple(sorted(self.values.items()))
        try:
            return hash((self.enum, self.variant, values))
        except TypeError:
            return hash((self.enum, self.variant))


def some(value):
    return Enum("Option", "Some", [value])


NONE = Enum("Option", "None", [], "unit")


def ok(value=UNIT):
    return Enum("Result", "Ok", [value])


def err(value):
    return Enum("Result", "Err", [value])


def is_none(value) -> bool:
    return isinstance(value, Enum) and value.enum == "Option" and value.variant == "None"


def is_some(value) -> bool:
    return isinstance(value, Enum) and value.enum == "Option" and value.variant == "Some"


class Ref:
    """`&mut x` where x holds something Python cannot mutate in place."""

    __slots__ = ("getter", "setter")

    def __init__(self, getter, setter) -> None:
        self.getter = getter
        self.setter = setter

    def get(self):
        return self.getter()

    def set(self, value) -> None:
        self.setter(value)


class Func:
    __slots__ = ("name", "params", "body", "env", "takes_self", "owner")

    def __init__(self, name, params, body, env, takes_self=False, owner=None) -> None:
        self.name = name
        self.params = params
        self.body = body
        self.env = env
        self.takes_self = takes_self
        self.owner = owner


class Bound:
    __slots__ = ("func", "receiver")

    def __init__(self, func, receiver) -> None:
        self.func = func
        self.receiver = receiver


class Native:
    """A library function or object implemented in Python."""

    __slots__ = ("name", "call")

    def __init__(self, name, call) -> None:
        self.name = name
        self.call = call


class Range:
    __slots__ = ("start", "end", "inclusive")

    def __init__(self, start, end, inclusive=False) -> None:
        self.start = start
        self.end = end
        self.inclusive = inclusive

    def __iter__(self):
        if self.end is None:
            return self.unbounded()
        stop = self.end + 1 if self.inclusive else self.end
        return iter(range(self.start or 0, stop))

    def unbounded(self):
        index = self.start or 0
        while True:
            yield index
            index += 1

    def __len__(self) -> int:
        stop = self.end + 1 if self.inclusive else self.end
        return max(0, stop - (self.start or 0))

    def contains(self, value) -> bool:
        if self.inclusive:
            return self.start <= value <= self.end
        return self.start <= value < self.end


class Iter:
    """A lazy iterator, which is what every `.iter().map(...)` chain becomes."""

    __slots__ = ("source",)

    def __init__(self, source) -> None:
        self.source = source

    def __iter__(self):
        return iter(self.source)


class Formatter:
    """What `impl fmt::Display` writes into."""

    __slots__ = ("pieces",)

    def __init__(self) -> None:
        self.pieces = []

    def write(self, text) -> None:
        self.pieces.append(text)

    def text(self) -> str:
        return "".join(self.pieces)


def unref(value):
    return value.get() if isinstance(value, Ref) else value


def clone_value(value):
    if isinstance(value, (Struct, Enum)):
        return value.clone()
    if isinstance(value, list):
        return [clone_value(item) for item in value]
    if isinstance(value, dict):
        return {k: clone_value(v) for k, v in value.items()}
    if isinstance(value, set):
        return set(value)
    return value


def format_float(value: float, debug=False) -> str:
    if value != value:
        return "NaN"
    if value == math.inf:
        return "inf"
    if value == -math.inf:
        return "-inf"
    text = repr(value)
    if text.endswith(".0"):
        return text if debug else text[:-2]
    if "e" in text:
        # Rust never abbreviates a Display float with an exponent.
        text = f"{value:.17f}".rstrip("0")
        if text.endswith("."):
            text += "0"
    return text


def escape(text: str) -> str:
    out = []
    for character in text:
        if character == '"':
            out.append('\\"')
        elif character == "\\":
            out.append("\\\\")
        elif character == "\n":
            out.append("\\n")
        elif character == "\t":
            out.append("\\t")
        elif character == "\r":
            out.append("\\r")
        else:
            out.append(character)
    return "".join(out)


def display(value, interp=None) -> str:
    """`{}` - what a type shows a user."""
    value = unref(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Char):
        return str(value)
    if isinstance(value, float):
        return format_float(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, Unit):
        return "()"
    if isinstance(value, (Struct, Enum)) and interp is not None:
        rendered = interp.user_display(value)
        if rendered is not None:
            return rendered
    return debug(value, interp)


def debug(value, interp=None, pretty=False, indent=0) -> str:
    """`{:?}` - what a type shows a programmer."""
    value = unref(value)
    pad = "    " * (indent + 1)
    closing = "    " * indent

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Char):
        return f"'{value}'"
    if isinstance(value, float):
        return format_float(value, debug=True)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return f'"{escape(value)}"'
    if isinstance(value, Unit):
        return "()"

    if isinstance(value, list):
        if not value:
            return "[]"
        items = [debug(item, interp, pretty, indent + 1) for item in value]
        if pretty:
            return "[\n" + ",\n".join(pad + item for item in items) + ",\n" + closing + "]"
        return "[" + ", ".join(items) + "]"

    if isinstance(value, tuple):
        items = [debug(item, interp, pretty, indent + 1) for item in value]
        if len(items) == 1:
            return f"({items[0]},)"
        return "(" + ", ".join(items) + ")"

    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [
            f"{debug(k, interp, pretty, indent + 1)}: {debug(v, interp, pretty, indent + 1)}"
            for k, v in value.items()
        ]
        if pretty:
            return "{\n" + ",\n".join(pad + item for item in items) + ",\n" + closing + "}"
        return "{" + ", ".join(items) + "}"

    if isinstance(value, set):
        items = [debug(item, interp, pretty, indent + 1) for item in value]
        return "{" + ", ".join(items) + "}"

    if isinstance(value, Struct):
        if value.shape == "unit":
            return value.name
        if value.shape == "tuple":
            items = [debug(v, interp, pretty, indent + 1) for v in value.fields.values()]
            return f"{value.name}(" + ", ".join(items) + ")"
        if not value.fields:
            return value.name
        items = [
            f"{k}: {debug(v, interp, pretty, indent + 1)}" for k, v in value.fields.items()
        ]
        if pretty:
            return (f"{value.name} {{\n" + ",\n".join(pad + item for item in items) +
                    ",\n" + closing + "}")
        return f"{value.name} {{ " + ", ".join(items) + " }"

    if isinstance(value, Enum):
        if value.shape == "unit" or not value.values:
            return value.variant
        if value.shape == "named":
            items = [
                f"{k}: {debug(v, interp, pretty, indent + 1)}" for k, v in value.values.items()
            ]
            if pretty:
                return (f"{value.variant} {{\n" + ",\n".join(pad + item for item in items) +
                        ",\n" + closing + "}")
            return f"{value.variant} {{ " + ", ".join(items) + " }"
        items = [debug(v, interp, pretty, indent + 1) for v in value.values]
        if pretty and len(items) == 1:
            return f"{value.variant}(\n{pad}{items[0]},\n{closing})"
        return f"{value.variant}(" + ", ".join(items) + ")"

    if isinstance(value, Range):
        end = "" if value.end is None else str(value.end)
        return f"{value.start}..{'=' if value.inclusive else ''}{end}"
    if isinstance(value, Iter):
        return "Iter"
    if isinstance(value, (Func, Bound, Native)):
        return "<fn>"
    return str(value)


def type_label(value) -> str:
    value = unref(value)
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, Char):
        return "char"
    if isinstance(value, float):
        return "f64"
    if isinstance(value, int):
        return "i32"
    if isinstance(value, str):
        return "String"
    if isinstance(value, list):
        return "Vec"
    if isinstance(value, dict):
        return "HashMap"
    if isinstance(value, set):
        return "HashSet"
    if isinstance(value, tuple):
        return "tuple"
    if isinstance(value, Struct):
        return value.name
    if isinstance(value, Enum):
        return value.enum
    if isinstance(value, Range):
        return "Range"
    if isinstance(value, Iter):
        return "Iterator"
    return type(value).__name__
