"""Parser for the Rust interpreter.

Covers the Rust people write rather than the Rust the reference describes:
functions, structs, enums, traits, impl blocks, generics (parsed and then
ignored), closures, iterator chains, `match` with real patterns, `if let`,
`while let`, the `?` operator, and the macros that appear in every program.

Lifetimes and type annotations are parsed so that source is accepted verbatim,
and then dropped: nothing downstream enforces types, so carrying them would be
weight without work.
"""

from __future__ import annotations

from .clike_lexer import LangSyntaxError, Options, Token, tokenize

KEYWORDS = {
    "as", "async", "await", "break", "const", "continue", "crate", "dyn",
    "else", "enum", "extern", "false", "fn", "for", "if", "impl", "in", "let",
    "loop", "match", "mod", "move", "mut", "pub", "ref", "return", "self",
    "Self", "static", "struct", "super", "trait", "true", "type", "unsafe",
    "use", "where", "while",
}

OPERATORS = [
    "<<=", ">>=", "..=", "...",
    "->", "=>", "::", "..", "&&", "||", "==", "!=", "<=", ">=", "+=", "-=",
    "*=", "/=", "%=", "&=", "|=", "^=", "<<", ">>",
    "+", "-", "*", "/", "%", "=", "<", ">", "!", "&", "|", "^", "?", "@", "#",
    "(", ")", "[", "]", "{", "}", ",", ";", ":", ".",
]

SUFFIXES = tuple(sorted(
    ("i8", "i16", "i32", "i64", "i128", "isize",
     "u8", "u16", "u32", "u64", "u128", "usize", "f32", "f64"),
    key=len, reverse=True,
))

LEX = Options(
    keywords=KEYWORDS,
    operators=OPERATORS,
    raw_prefix=True,
    lifetimes=True,
    nested_comments=True,
    number_suffixes=SUFFIXES,
    char_as_int=False,
)

BINARY_LEVELS = [
    ["||"],
    ["&&"],
    ["==", "!=", "<", "<=", ">", ">="],
    ["|"],
    ["^"],
    ["&"],
    ["<<", ">>"],
    ["+", "-"],
    ["*", "/", "%"],
]

ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}

BLOCK_EXPRESSIONS = {"if", "match", "loop", "while", "for", "unsafe", "block"}


class Parser:

    def __init__(self, source: str) -> None:
        self.tokens = tokenize(source, LEX)
        self.position = 0
        # Set while parsing the subject of `if`/`while`/`match`/`for`, where a
        # `{` opens the body and never a struct literal.
        self.no_struct = 0

    # ---------------------------------------------------------------- tokens

    @property
    def token(self) -> Token:
        return self.tokens[self.position]

    def peek(self, offset=1) -> Token:
        return self.tokens[min(self.position + offset, len(self.tokens) - 1)]

    def next(self) -> Token:
        token = self.tokens[self.position]
        if token.kind != "eof":
            self.position += 1
        return token

    def at(self, value) -> bool:
        return self.token.value == value and self.token.kind in ("op", "kw")

    def at_name(self) -> bool:
        return self.token.kind == "id" or self.at("self") or self.at("Self") or self.at("crate")

    def accept(self, value) -> bool:
        if self.at(value):
            self.next()
            return True
        return False

    def expect(self, value) -> Token:
        if not self.at(value):
            got = self.token.value if self.token.kind != "eof" else "end of file"
            raise LangSyntaxError(f"expected {value!r}, found {got!r}", self.token.line)
        return self.next()

    def name(self) -> str:
        if not self.at_name():
            raise LangSyntaxError(f"expected a name, found {self.token.value!r}", self.token.line)
        return self.next().value

    # ------------------------------------------------------------------ file

    def parse(self) -> dict:
        unit = {"functions": {}, "structs": {}, "enums": {}, "impls": [], "traits": {},
                "consts": [], "uses": []}
        while self.token.kind != "eof":
            self.parse_item(unit)
        return unit

    def parse_item(self, unit) -> None:
        self.skip_attributes()
        self.accept("pub")
        if self.at("("):          # pub(crate)
            self.skip_balanced("(", ")")
        self.accept("unsafe")
        self.accept("async")

        if self.accept(";"):
            return
        if self.accept("use"):
            path = []
            while not self.at(";") and self.token.kind != "eof":
                path.append(self.next().value)
            self.accept(";")
            unit["uses"].append("".join(str(part) for part in path))
            return
        if self.at("mod"):
            self.next()
            self.name()
            if self.accept(";"):
                return
            # An inline module's items are hoisted: there is one namespace here.
            self.expect("{")
            while not self.at("}"):
                self.parse_item(unit)
            self.expect("}")
            return
        if self.at("extern"):
            self.next()
            if self.token.kind == "str":
                self.next()
            if self.at("{"):
                self.skip_balanced("{", "}")
            return
        if self.at("fn"):
            node = self.parse_fn()
            unit["functions"][node[1]] = node
            return
        if self.at("struct"):
            name, node = self.parse_struct()
            unit["structs"][name] = node
            return
        if self.at("enum"):
            name, node = self.parse_enum()
            unit["enums"][name] = node
            return
        if self.at("impl"):
            unit["impls"].append(self.parse_impl())
            return
        if self.at("trait"):
            name, node = self.parse_trait()
            unit["traits"][name] = node
            return
        if self.at("const") or self.at("static"):
            self.next()
            self.accept("mut")
            name = self.name()
            if self.accept(":"):
                self.parse_type()
            self.expect("=")
            value = self.parse_expression()
            self.accept(";")
            unit["consts"].append((name, value))
            return
        if self.at("type"):
            self.next()
            self.name()
            if self.at("<"):
                self.skip_generics()
            self.expect("=")
            self.parse_type()
            self.accept(";")
            return

        raise LangSyntaxError(f"unexpected {self.token.value!r} at the top level",
                              self.token.line)

    def skip_attributes(self) -> None:
        while self.at("#"):
            self.next()
            self.accept("!")
            self.skip_balanced("[", "]")

    def skip_balanced(self, opener, closer) -> None:
        if not self.at(opener):
            return
        depth = 0
        while True:
            if self.at(opener):
                depth += 1
            elif self.at(closer):
                depth -= 1
                if depth == 0:
                    self.next()
                    return
            elif self.token.kind == "eof":
                raise LangSyntaxError(f"unterminated {opener}", self.token.line)
            self.next()

    def skip_generics(self) -> None:
        """`<T: Trait, U>` and its where-clause friends carry no runtime meaning."""
        if not self.at("<"):
            return
        depth = 0
        while True:
            if self.at("<") or self.at("<<"):
                depth += 2 if self.at("<<") else 1
            elif self.at(">") or self.at(">>"):
                depth -= 2 if self.at(">>") else 1
                if depth <= 0:
                    self.next()
                    return
            elif self.token.kind == "eof":
                raise LangSyntaxError("unterminated generics", self.token.line)
            self.next()

    def capture_generics(self):
        """Reads a turbofish and keeps the name in it.

        `collect::<Vec<String>>()` and `parse::<i32>()` are the two places
        where a type argument decides what a call actually does, so that one
        name is worth keeping when the rest of the annotation is not.
        """
        if not self.at("<"):
            return None
        start = self.position
        self.skip_generics()
        for index in range(start, self.position):
            token = self.tokens[index]
            if token.kind == "id":
                return token.value
        return None

    def skip_where(self) -> None:
        if self.token.kind == "id" and self.token.value == "where":
            while not self.at("{") and not self.at(";") and self.token.kind != "eof":
                self.next()

    # ------------------------------------------------------------ functions

    def parse_fn(self):
        line = self.token.line
        self.expect("fn")
        name = self.name()
        if self.at("<"):
            self.skip_generics()

        self.expect("(")
        params = []
        takes_self = False
        while not self.at(")"):
            self.skip_attributes()
            if self.at("&"):
                # &self / &mut self
                save = self.position
                self.next()
                if self.token.kind == "lifetime":
                    self.next()
                self.accept("mut")
                if self.at("self"):
                    self.next()
                    takes_self = True
                    self.accept(",")
                    continue
                self.position = save
            if self.at("mut") and self.peek().value == "self":
                self.next()
                self.next()
                takes_self = True
                self.accept(",")
                continue
            if self.at("self"):
                self.next()
                takes_self = True
                if self.accept(":"):
                    self.parse_type()
                self.accept(",")
                continue

            pattern = self.parse_pattern()
            if self.accept(":"):
                self.parse_type()
            params.append(pattern)
            self.accept(",")
        self.expect(")")

        if self.accept("->"):
            self.parse_type()
        self.skip_where()

        if self.accept(";"):
            return ("fn", name, params, takes_self, None, line)
        body = self.parse_block()
        return ("fn", name, params, takes_self, body, line)

    def parse_struct(self):
        self.expect("struct")
        name = self.name()
        if self.at("<"):
            self.skip_generics()
        self.skip_where()

        if self.accept(";"):
            return name, ("unit", [])
        if self.at("("):
            self.next()
            count = 0
            while not self.at(")"):
                self.accept("pub")
                self.parse_type()
                count += 1
                self.accept(",")
            self.expect(")")
            self.accept(";")
            return name, ("tuple", [str(index) for index in range(count)])

        self.expect("{")
        fields = []
        while not self.at("}"):
            self.skip_attributes()
            self.accept("pub")
            if self.at("("):
                self.skip_balanced("(", ")")
            field = self.name()
            self.expect(":")
            self.parse_type()
            fields.append(field)
            self.accept(",")
        self.expect("}")
        return name, ("named", fields)

    def parse_enum(self):
        self.expect("enum")
        name = self.name()
        if self.at("<"):
            self.skip_generics()
        self.skip_where()
        self.expect("{")
        variants = {}
        while not self.at("}"):
            self.skip_attributes()
            variant = self.name()
            if self.at("("):
                self.next()
                count = 0
                while not self.at(")"):
                    self.parse_type()
                    count += 1
                    self.accept(",")
                self.expect(")")
                variants[variant] = ("tuple", count)
            elif self.at("{"):
                self.next()
                fields = []
                while not self.at("}"):
                    fields.append(self.name())
                    self.expect(":")
                    self.parse_type()
                    self.accept(",")
                self.expect("}")
                variants[variant] = ("named", fields)
            else:
                if self.accept("="):
                    self.parse_expression()
                variants[variant] = ("unit", 0)
            self.accept(",")
        self.expect("}")
        return name, variants

    def parse_impl(self):
        line = self.token.line
        self.expect("impl")
        if self.at("<"):
            self.skip_generics()

        first = self.parse_type_path()
        trait_name = None
        type_name = first
        if self.accept("for"):
            trait_name = first
            type_name = self.parse_type_path()
        self.skip_where()

        self.expect("{")
        functions = {}
        while not self.at("}"):
            self.skip_attributes()
            self.accept("pub")
            if self.at("type"):
                self.next()
                self.name()
                self.expect("=")
                self.parse_type()
                self.accept(";")
                continue
            if self.at("const"):
                self.next()
                self.name()
                if self.accept(":"):
                    self.parse_type()
                self.expect("=")
                self.parse_expression()
                self.accept(";")
                continue
            self.accept("unsafe")
            node = self.parse_fn()
            functions[node[1]] = node
        self.expect("}")
        return (type_name, trait_name, functions, line)

    def parse_trait(self):
        self.expect("trait")
        name = self.name()
        if self.at("<"):
            self.skip_generics()
        if self.accept(":"):
            while not self.at("{") and self.token.kind != "eof":
                self.next()
        self.skip_where()
        self.expect("{")
        functions = {}
        while not self.at("}"):
            self.skip_attributes()
            if self.at("type"):
                self.next()
                self.name()
                self.accept(";")
                continue
            if self.at("const"):
                while not self.at(";"):
                    self.next()
                self.next()
                continue
            node = self.parse_fn()
            functions[node[1]] = node
        self.expect("}")
        return name, functions

    def parse_type_path(self) -> str:
        """Reduces a type to the name that matters for method lookup."""
        self.accept("dyn")
        self.accept("impl")
        self.accept("&")
        if self.token.kind == "lifetime":
            self.next()
        self.accept("mut")

        if self.at("(") or self.at("["):
            self.parse_type()
            return "tuple"

        name = self.name()
        while self.accept("::"):
            name = self.name()
        if self.at("<"):
            self.skip_generics()
        while self.accept("+"):
            if self.token.kind == "lifetime":
                self.next()
            else:
                self.parse_type_path()
        return name

    def parse_type(self) -> None:
        """Types are read for their syntax only; nothing keeps them."""
        if self.token.kind == "lifetime":
            self.next()
        self.accept("&")
        if self.token.kind == "lifetime":
            self.next()
        self.accept("mut")
        self.accept("dyn")
        self.accept("impl")

        if self.accept("("):
            while not self.at(")"):
                self.parse_type()
                self.accept(",")
            self.expect(")")
        elif self.accept("["):
            self.parse_type()
            if self.accept(";"):
                self.parse_expression()
            self.expect("]")
        elif self.at("*"):
            self.next()
            self.accept("const")
            self.accept("mut")
            self.parse_type()
        elif self.at("fn") or self.at("Fn") or (self.token.kind == "id" and
                                                self.token.value in ("Fn", "FnMut", "FnOnce")):
            self.next()
            if self.at("("):
                self.skip_balanced("(", ")")
            if self.accept("->"):
                self.parse_type()
        elif self.at("!"):
            self.next()
        else:
            self.name()
            while self.accept("::"):
                if self.at("<"):
                    self.skip_generics()
                    break
                self.name()
            if self.at("<"):
                self.skip_generics()

        while self.accept("+"):
            if self.token.kind == "lifetime":
                self.next()
            else:
                self.parse_type()

    # ------------------------------------------------------------ statements

    def parse_block(self):
        line = self.token.line
        self.expect("{")
        statements = []
        tail = None
        while not self.at("}"):
            self.skip_attributes()
            if self.accept(";"):
                continue
            if self.at("fn") or self.at("struct") or self.at("enum") or self.at("impl") or \
                    self.at("trait") or self.at("use") or self.at("mod"):
                inner = {"functions": {}, "structs": {}, "enums": {}, "impls": [],
                         "traits": {}, "consts": [], "uses": []}
                self.parse_item(inner)
                statements.append(("item", inner, self.token.line))
                continue
            if self.at("let") or self.at("const") or self.at("static"):
                statements.append(self.parse_let())
                continue

            expression = self.parse_expression()
            if self.accept(";"):
                statements.append(("semi", expression, expression[-1]))
            elif self.at("}"):
                tail = expression
            else:
                # A block-shaped expression needs no semicolon between it and
                # what follows: `if a { } if b { }` is two statements.
                statements.append(("semi", expression, expression[-1]))
        self.expect("}")
        return ("block", statements, tail, line)

    def parse_let(self):
        line = self.token.line
        keyword = self.next().value
        if keyword in ("const", "static"):
            self.accept("mut")
            name = self.name()
            if self.accept(":"):
                self.parse_type()
            self.expect("=")
            value = self.parse_expression()
            self.accept(";")
            return ("let", ("bind", name, line), value, None, line)

        pattern = self.parse_pattern()
        declared = None
        if self.accept(":"):
            start = self.position
            self.parse_type()
            declared = self.type_hint(start)

        value = None
        otherwise = None
        if self.accept("="):
            value = self.parse_expression()
            if self.accept("else"):
                otherwise = self.parse_block()
        self.accept(";")
        return ("let", pattern, value, declared, line, otherwise)

    def type_hint(self, start):
        """The head of an annotation, which is all `collect()` needs."""
        for index in range(start, self.position):
            token = self.tokens[index]
            if token.kind == "id" and token.value not in ("mut", "dyn"):
                return token.value
        return None

    # ----------------------------------------------------------- expressions

    def parse_expression(self):
        return self.parse_assignment()

    def parse_assignment(self):
        left = self.parse_range()
        if self.token.kind == "op" and self.token.value in ASSIGN_OPS:
            operator = self.next().value
            line = self.token.line
            right = self.parse_assignment()
            return ("assign", left, operator, right, line)
        return left

    def parse_range(self):
        line = self.token.line
        if self.at("..") or self.at("..="):
            inclusive = self.next().value == "..="
            end = None
            if not self.range_ends_here():
                end = self.parse_binary(0)
            return ("range", None, end, inclusive, line)

        left = self.parse_binary(0)
        if self.at("..") or self.at("..="):
            inclusive = self.next().value == "..="
            end = None
            if not self.range_ends_here():
                end = self.parse_binary(0)
            return ("range", left, end, inclusive, line)
        return left

    def range_ends_here(self) -> bool:
        return self.at("{") or self.at("}") or self.at(")") or self.at("]") or \
            self.at(",") or self.at(";") or self.token.kind == "eof"

    def parse_binary(self, level):
        if level >= len(BINARY_LEVELS):
            return self.parse_cast()

        left = self.parse_binary(level + 1)
        while self.token.kind == "op" and self.token.value in BINARY_LEVELS[level]:
            # `<` inside a turbofish never reaches here, and a generic in an
            # expression position is always written with `::<`.
            operator = self.next().value
            line = self.token.line
            right = self.parse_binary(level + 1)
            left = ("bin", operator, left, right, line)
        return left

    def parse_cast(self):
        value = self.parse_unary()
        while self.at("as"):
            line = self.token.line
            self.next()
            start = self.position
            self.parse_type()
            value = ("cast", value, self.type_hint(start), line)
        return value

    def parse_unary(self):
        line = self.token.line
        if self.at("-"):
            self.next()
            return ("unary", "-", self.parse_unary(), line)
        if self.at("!"):
            self.next()
            return ("unary", "!", self.parse_unary(), line)
        if self.at("*"):
            self.next()
            return ("deref", self.parse_unary(), line)
        if self.at("&") or self.at("&&"):
            doubled = self.token.value == "&&"
            self.next()
            mutable = self.accept("mut")
            inner = self.parse_unary()
            node = ("ref", inner, mutable, line)
            return ("ref", node, False, line) if doubled else node
        return self.parse_postfix(self.parse_primary())

    def parse_postfix(self, node):
        while True:
            line = self.token.line
            if self.at("."):
                self.next()
                if self.token.kind == "int":
                    node = ("field", node, str(self.next().value), line)
                    continue
                if self.at("await"):
                    self.next()
                    continue
                name = self.name()
                hint = None
                if self.at("::"):
                    self.next()
                    hint = self.capture_generics()
                if self.at("("):
                    node = ("method", node, name, self.parse_call_arguments(), hint, line)
                else:
                    node = ("field", node, name, line)
            elif self.at("("):
                node = ("call", node, self.parse_call_arguments(), line)
            elif self.at("["):
                self.next()
                saved, self.no_struct = self.no_struct, 0
                index = self.parse_expression()
                self.no_struct = saved
                self.expect("]")
                node = ("index", node, index, line)
            elif self.at("?"):
                self.next()
                node = ("try", node, line)
            else:
                return node

    def parse_call_arguments(self):
        self.expect("(")
        saved, self.no_struct = self.no_struct, 0
        arguments = []
        while not self.at(")"):
            arguments.append(self.parse_expression())
            self.accept(",")
        self.no_struct = saved
        self.expect(")")
        return arguments

    def parse_primary(self):
        token = self.token
        line = token.line

        if token.kind == "int":
            self.next()
            return ("int", token.value, line)
        if token.kind == "float":
            self.next()
            return ("float", token.value, line)
        if token.kind == "str":
            self.next()
            return ("str", token.value, line)
        if token.kind == "char":
            self.next()
            return ("char", token.value, line)
        if self.at("true"):
            self.next()
            return ("bool", True, line)
        if self.at("false"):
            self.next()
            return ("bool", False, line)

        if self.at("("):
            self.next()
            saved, self.no_struct = self.no_struct, 0
            if self.at(")"):
                self.next()
                self.no_struct = saved
                return ("unit", line)
            items = [self.parse_expression()]
            is_tuple = False
            while self.accept(","):
                is_tuple = True
                if self.at(")"):
                    break
                items.append(self.parse_expression())
            self.no_struct = saved
            self.expect(")")
            return ("tuple", items, line) if is_tuple else items[0]

        if self.at("["):
            self.next()
            saved, self.no_struct = self.no_struct, 0
            items = []
            repeat = None
            if not self.at("]"):
                items.append(self.parse_expression())
                if self.accept(";"):
                    repeat = self.parse_expression()
                else:
                    while self.accept(","):
                        if self.at("]"):
                            break
                        items.append(self.parse_expression())
            self.no_struct = saved
            self.expect("]")
            return ("array", items, repeat, line)

        if self.at("{"):
            return self.parse_block()
        if self.at("if"):
            return self.parse_if()
        if self.at("match"):
            return self.parse_match()
        if self.at("loop"):
            self.next()
            return ("loop", self.parse_block(), line)
        if self.at("while"):
            return self.parse_while()
        if self.at("for"):
            return self.parse_for()
        if self.at("unsafe"):
            self.next()
            return self.parse_block()
        if self.at("return"):
            self.next()
            if self.at(";") or self.at("}"):
                return ("return", None, line)
            return ("return", self.parse_expression(), line)
        if self.at("break"):
            self.next()
            if self.token.kind == "lifetime":
                self.next()
            if self.at(";") or self.at("}"):
                return ("break", None, line)
            return ("break", self.parse_expression(), line)
        if self.at("continue"):
            self.next()
            if self.token.kind == "lifetime":
                self.next()
            return ("continue", line)
        if self.at("move") or self.at("|") or self.at("||"):
            return self.parse_closure()

        if self.token.kind == "lifetime":
            # A loop label: `'outer: loop { }`.
            self.next()
            self.expect(":")
            return self.parse_primary()

        if self.at_name():
            return self.parse_path_expression()

        raise LangSyntaxError(f"unexpected {token.value!r}", line)

    def parse_closure(self):
        line = self.token.line
        self.accept("move")
        params = []
        if self.accept("||"):
            pass
        else:
            self.expect("|")
            while not self.at("|"):
                pattern = self.parse_pattern()
                if self.accept(":"):
                    self.parse_type()
                params.append(pattern)
                self.accept(",")
            self.expect("|")
        if self.accept("->"):
            self.parse_type()
            body = self.parse_block()
        else:
            body = self.parse_expression()
        return ("closure", params, body, line)

    def parse_path_expression(self):
        line = self.token.line
        parts = [self.name()]
        while self.at("::"):
            self.next()
            if self.at("<"):
                self.skip_generics()
                continue
            parts.append(self.name())

        # A macro: println!(...), vec![...], format!(...).
        if self.at("!") and self.peek().value in ("(", "[", "{"):
            self.next()
            opener = self.token.value
            closer = {"(": ")", "[": "]", "{": "}"}[opener]
            self.next()
            saved, self.no_struct = self.no_struct, 0
            arguments = []
            repeat = None
            while not self.at(closer):
                arguments.append(self.parse_expression())
                if self.accept(";"):
                    repeat = self.parse_expression()
                    break
                self.accept(",")
            self.no_struct = saved
            self.expect(closer)
            return ("macro", parts[-1], arguments, repeat, line)

        if self.at("{") and self.no_struct == 0 and parts[-1][:1].isupper():
            return ("structlit", parts, self.parse_struct_literal(), line)

        return ("path", parts, line)

    def parse_struct_literal(self):
        self.expect("{")
        fields = []
        rest = None
        while not self.at("}"):
            if self.accept(".."):
                rest = self.parse_expression()
                break
            name = self.name()
            if self.accept(":"):
                fields.append((name, self.parse_expression()))
            else:
                # Field shorthand: `Point { x, y }`.
                fields.append((name, ("path", [name], self.token.line)))
            self.accept(",")
        self.expect("}")
        return (fields, rest)

    def parse_if(self):
        line = self.token.line
        self.expect("if")
        if self.accept("let"):
            pattern = self.parse_pattern()
            self.expect("=")
            self.no_struct += 1
            subject = self.parse_expression()
            self.no_struct -= 1
            then = self.parse_block()
            otherwise = self.parse_else()
            return ("iflet", pattern, subject, then, otherwise, line)

        self.no_struct += 1
        condition = self.parse_expression()
        self.no_struct -= 1
        then = self.parse_block()
        return ("if", condition, then, self.parse_else(), line)

    def parse_else(self):
        if not self.accept("else"):
            return None
        if self.at("if"):
            return self.parse_if()
        return self.parse_block()

    def parse_while(self):
        line = self.token.line
        self.expect("while")
        if self.accept("let"):
            pattern = self.parse_pattern()
            self.expect("=")
            self.no_struct += 1
            subject = self.parse_expression()
            self.no_struct -= 1
            return ("whilelet", pattern, subject, self.parse_block(), line)
        self.no_struct += 1
        condition = self.parse_expression()
        self.no_struct -= 1
        return ("while", condition, self.parse_block(), line)

    def parse_for(self):
        line = self.token.line
        self.expect("for")
        pattern = self.parse_pattern()
        self.expect("in")
        self.no_struct += 1
        subject = self.parse_expression()
        self.no_struct -= 1
        return ("for", pattern, subject, self.parse_block(), line)

    def parse_match(self):
        line = self.token.line
        self.expect("match")
        self.no_struct += 1
        subject = self.parse_expression()
        self.no_struct -= 1
        self.expect("{")
        arms = []
        while not self.at("}"):
            self.skip_attributes()
            pattern = self.parse_pattern(allow_or=True)
            guard = None
            if self.accept("if"):
                guard = self.parse_expression()
            self.expect("=>")
            body = self.parse_expression()
            self.accept(",")
            arms.append((pattern, guard, body))
        self.expect("}")
        return ("match", subject, arms, line)

    # -------------------------------------------------------------- patterns

    def parse_pattern(self, allow_or=False):
        self.accept("|")
        first = self.parse_single_pattern()
        if not allow_or or not self.at("|"):
            return first
        alternatives = [first]
        while self.accept("|"):
            alternatives.append(self.parse_single_pattern())
        return ("or", alternatives, first[-1])

    def parse_single_pattern(self):
        line = self.token.line
        self.accept("ref")
        mutable = self.accept("mut")
        self.accept("&")
        self.accept("mut")

        if self.at("_"):
            self.next()
            return ("any", line)
        if self.token.kind in ("int", "float", "str", "char"):
            token = self.next()
            value = ("int" if token.kind == "int" else token.kind, token.value, line)
            if self.at("..=") or self.at(".."):
                inclusive = self.next().value == "..="
                end = self.next()
                return ("rangepat", value[1], end.value, inclusive, line)
            return ("literal", value, line)
        if self.at("-"):
            self.next()
            token = self.next()
            value = -token.value
            if self.at("..=") or self.at(".."):
                inclusive = self.next().value == "..="
                sign = -1 if self.accept("-") else 1
                end = self.next().value * sign
                return ("rangepat", value, end, inclusive, line)
            return ("literal", ("int", value, line), line)
        if self.at("true") or self.at("false"):
            return ("literal", ("bool", self.next().value == "true", line), line)

        if self.at("("):
            self.next()
            items = []
            while not self.at(")"):
                items.append(self.parse_pattern())
                self.accept(",")
            self.expect(")")
            return ("tuplepat", items, line)

        if self.at("["):
            self.next()
            items = []
            while not self.at("]"):
                items.append(self.parse_pattern())
                self.accept(",")
            self.expect("]")
            return ("slicepat", items, line)

        if self.at_name():
            parts = [self.name()]
            while self.accept("::"):
                parts.append(self.name())

            if self.at("("):
                self.next()
                items = []
                while not self.at(")"):
                    if self.accept(".."):
                        continue
                    items.append(self.parse_pattern())
                    self.accept(",")
                self.expect(")")
                return ("enumpat", parts, items, None, line)

            if self.at("{") and self.no_struct == 0:
                self.next()
                fields = []
                while not self.at("}"):
                    if self.accept(".."):
                        break
                    name = self.name()
                    if self.accept(":"):
                        fields.append((name, self.parse_pattern()))
                    else:
                        fields.append((name, ("bind", name, line)))
                    self.accept(",")
                self.expect("}")
                return ("structpat", parts, fields, line)

            if len(parts) > 1 or parts[0][:1].isupper():
                return ("enumpat", parts, [], None, line)
            if self.accept("@"):
                return ("at", parts[0], self.parse_single_pattern(), line)
            return ("bind", parts[0], line)

        raise LangSyntaxError(f"unexpected {self.token.value!r} in a pattern", line)


def parse(source: str) -> dict:
    return Parser(source).parse()
