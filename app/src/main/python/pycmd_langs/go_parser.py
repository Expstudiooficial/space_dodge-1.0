"""Parser for the Go interpreter.

Produces tuple-shaped nodes that :mod:`go_interp` walks. The grammar covered
is the one people actually write: packages, imports, functions with multiple
return values, methods, structs, interfaces, slices, maps, channels, closures,
`defer`, `go`, and every statement form Go has.

Semicolons are inserted the way the real compiler does it - at a line break
after a token that can end a statement - so source written in ordinary Go
style parses without them.
"""

from __future__ import annotations

from .clike_lexer import LangSyntaxError, Options, Token, tokenize

KEYWORDS = {
    "break", "case", "chan", "const", "continue", "default", "defer", "else",
    "fallthrough", "for", "func", "go", "goto", "if", "import", "interface",
    "map", "package", "range", "return", "select", "struct", "switch", "type",
    "var",
}

OPERATORS = [
    "<<=", ">>=", "...", "&^=",
    "&&", "||", "<-", "++", "--", "==", "!=", "<=", ">=", ":=", "...",
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<", ">>", "&^",
    "+", "-", "*", "/", "%", "&", "|", "^", "<", ">", "=", "!",
    "(", ")", "[", "]", "{", "}", ",", ";", ".", ":",
]

LEX = Options(
    keywords=KEYWORDS,
    operators=OPERATORS,
    backtick_raw=True,
    char_as_int=True,          # 'a' is a rune, which is an integer
    number_suffixes=(),
)

# A newline ends a statement when the line's last token could end one.
ENDERS_KIND = {"id", "int", "float", "str", "char"}
ENDERS_VALUE = {"break", "continue", "fallthrough", "return", ")", "]", "}", "++", "--"}

# Binary operators by precedence, loosest first.
BINARY_LEVELS = [
    ["||"],
    ["&&"],
    ["==", "!=", "<", "<=", ">", ">="],
    ["+", "-", "|", "^"],
    ["*", "/", "%", "<<", ">>", "&", "&^"],
]

ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", "&^="}

BASIC_TYPES = {
    "int", "int8", "int16", "int32", "int64", "uint", "uint8", "uint16",
    "uint32", "uint64", "uintptr", "float32", "float64", "complex64",
    "complex128", "string", "bool", "byte", "rune", "error", "any",
}


def add_semicolons(tokens: list) -> list:
    """Go's rule for ending a statement at a line break."""
    result = []
    for token in tokens:
        if result:
            previous = result[-1]
            ends = previous.kind in ENDERS_KIND or previous.value in ENDERS_VALUE
            if ends and token.line > previous.line:
                result.append(Token("op", ";", previous.line))
        result.append(token)
    last = result[-2] if len(result) >= 2 else None
    if last is not None and (last.kind in ENDERS_KIND or last.value in ENDERS_VALUE):
        result.insert(len(result) - 1, Token("op", ";", last.line))
    return result


class Parser:

    def __init__(self, source: str) -> None:
        self.tokens = add_semicolons(tokenize(source, LEX))
        self.position = 0
        # Set while parsing the header of an `if`/`for`/`switch`, where a `{`
        # starts the body rather than a composite literal.
        self.no_literal = 0

    # ---------------------------------------------------------------- tokens

    @property
    def token(self) -> Token:
        return self.tokens[self.position]

    def peek(self, offset=1) -> Token:
        index = min(self.position + offset, len(self.tokens) - 1)
        return self.tokens[index]

    def next(self) -> Token:
        token = self.tokens[self.position]
        if token.kind != "eof":
            self.position += 1
        return token

    def at(self, value) -> bool:
        return self.token.value == value and self.token.kind in ("op", "kw")

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

    def skip_semis(self) -> None:
        while self.at(";"):
            self.next()

    # ------------------------------------------------------------------ file

    def parse(self) -> dict:
        unit = {"package": "main", "imports": [], "functions": {}, "methods": {},
                "types": {}, "globals": [], "consts": []}

        self.skip_semis()
        if self.accept("package"):
            unit["package"] = self.next().value
            self.skip_semis()

        while self.token.kind != "eof":
            self.skip_semis()
            if self.token.kind == "eof":
                break
            if self.accept("import"):
                self.parse_import(unit)
            elif self.at("func"):
                self.parse_func(unit)
            elif self.at("type"):
                self.parse_type_decl(unit)
            elif self.at("var"):
                self.next()
                for declaration in self.parse_var_group():
                    unit["globals"].append(declaration)
            elif self.at("const"):
                self.next()
                for declaration in self.parse_const_group():
                    unit["consts"].append(declaration)
            else:
                raise LangSyntaxError(
                    f"unexpected {self.token.value!r} at the top level", self.token.line
                )
        return unit

    def parse_import(self, unit) -> None:
        if self.accept("("):
            self.skip_semis()
            while not self.at(")"):
                self.read_import_line(unit)
                self.skip_semis()
            self.expect(")")
        else:
            self.read_import_line(unit)

    def read_import_line(self, unit) -> None:
        alias = None
        if self.token.kind == "id" or self.at("."):
            alias = self.next().value
        path = self.next().value
        unit["imports"].append((alias, path))

    # ------------------------------------------------------------ functions

    def parse_func(self, unit) -> None:
        line = self.token.line
        self.expect("func")

        receiver = None
        if self.at("("):
            receiver = self.parse_receiver()

        name = self.next().value
        if self.at("["):
            self.skip_type_params()
        params, variadic = self.parse_params()
        results = self.parse_results()
        body = self.parse_block()

        node = ("func", name, params, variadic, results, body, receiver, line)
        if receiver is None:
            unit["functions"][name] = node
        else:
            unit["methods"].setdefault(receiver[1], {})[name] = node

    def parse_receiver(self):
        self.expect("(")
        name = self.next().value
        pointer = False
        if self.accept("*"):
            pointer = True
        type_name = self.next().value
        if self.at("[",):
            self.skip_type_params()
        self.expect(")")
        return (name, type_name, pointer)

    def skip_type_params(self) -> None:
        """Generics are parsed and thrown away: the interpreter is dynamic."""
        depth = 0
        while True:
            if self.at("["):
                depth += 1
            elif self.at("]"):
                depth -= 1
                if depth == 0:
                    self.next()
                    return
            elif self.token.kind == "eof":
                raise LangSyntaxError("unterminated type parameters", self.token.line)
            self.next()

    def parse_params(self):
        self.expect("(")
        params = []
        variadic = False
        pending = []
        while not self.at(")"):
            if self.accept("..."):
                variadic = True
                self.parse_type()
                params.extend(pending)
                pending = []
                if params:
                    pass
                self.accept(",")
                continue

            # Go allows `a, b int`: names accumulate until a type appears.
            if self.token.kind == "id" and (self.peek().value == "," or
                                            self.is_type_start(self.peek())):
                name = self.next().value
                if self.accept(","):
                    pending.append(name)
                    continue
                if self.accept("..."):
                    variadic = True
                    self.parse_type()
                    params.extend(pending)
                    pending = []
                    params.append(name)
                    self.accept(",")
                    continue
                self.parse_type()
                params.extend(pending)
                pending = []
                params.append(name)
            else:
                # An unnamed parameter still occupies a position.
                self.parse_type()
                params.extend(pending)
                pending = []
                params.append("_")
            self.accept(",")
        self.expect(")")
        params.extend(pending)
        return params, variadic

    def is_type_start(self, token: Token) -> bool:
        if token.kind == "id":
            return True
        if token.kind == "kw":
            return token.value in ("map", "chan", "func", "struct", "interface")
        return token.value in ("*", "[", "...", "(")

    def parse_results(self):
        """Returns how many results there are, and any names they were given.

        Named results are not decoration: `func f() (result string)` declares a
        variable, a bare `return` hands back whatever it holds, and a deferred
        function can still change it after the return - which is exactly how
        `recover` turns a panic into a value.
        """
        if self.at("{") or self.at(";") or self.token.kind == "eof":
            return (0, [])
        if self.accept("("):
            entries = []
            while not self.at(")"):
                name = None
                if self.token.kind == "id" and self.is_type_start(self.peek()) and \
                        self.peek().value != ",":
                    name = self.next().value
                entries.append((name, self.parse_type()))
                self.accept(",")
            self.expect(")")
            return (len(entries), entries)
        return (1, [(None, self.parse_type())])

    # ----------------------------------------------------------------- types

    def parse_type_decl(self, unit) -> None:
        self.expect("type")
        if self.accept("("):
            self.skip_semis()
            while not self.at(")"):
                self.read_type_line(unit)
                self.skip_semis()
            self.expect(")")
        else:
            self.read_type_line(unit)

    def read_type_line(self, unit) -> None:
        name = self.next().value
        if self.at("["):
            self.skip_type_params()
        self.accept("=")
        unit["types"][name] = self.parse_type()

    def parse_type(self):
        token = self.token

        if self.accept("*"):
            return ("ptr", self.parse_type())
        if self.accept("["):
            if self.accept("]"):
                return ("slice", self.parse_type())
            if self.accept("..."):
                self.expect("]")
                return ("slice", self.parse_type())
            size = self.parse_expression()
            self.expect("]")
            return ("array", size, self.parse_type())
        if self.accept("map"):
            self.expect("[")
            key = self.parse_type()
            self.expect("]")
            return ("map", key, self.parse_type())
        if self.accept("chan"):
            self.accept("<-")
            return ("chan", self.parse_type())
        if self.at("<-"):
            self.next()
            self.expect("chan")
            return ("chan", self.parse_type())
        if self.accept("func"):
            params, _ = self.parse_params()
            results = self.parse_results()
            return ("functype", len(params), results)
        if self.accept("struct"):
            return ("struct", self.parse_struct_fields())
        if self.accept("interface"):
            return ("iface", self.parse_interface_body())
        if self.accept("("):
            inner = self.parse_type()
            self.expect(")")
            return inner

        if token.kind in ("id", "kw"):
            name = self.next().value
            if self.accept("."):
                name = f"{name}.{self.next().value}"
            if self.at("[") and self.peek().value != "]":
                self.skip_type_params()
            return ("named", name)

        raise LangSyntaxError(f"expected a type, found {token.value!r}", token.line)

    def parse_struct_fields(self):
        self.expect("{")
        self.skip_semis()
        fields = []
        while not self.at("}"):
            names = [self.next().value]
            while self.accept(","):
                names.append(self.next().value)
            if self.at(";") or self.at("}"):
                # An embedded type: the field is named after its type.
                fields.append((names[0], ("named", names[0])))
            else:
                field_type = self.parse_type()
                if self.token.kind == "str":
                    self.next()   # a struct tag, which we do not use
                for name in names:
                    fields.append((name, field_type))
            self.skip_semis()
        self.expect("}")
        return fields

    def parse_interface_body(self):
        self.expect("{")
        self.skip_semis()
        methods = []
        while not self.at("}"):
            name = self.next().value
            if self.at("("):
                self.parse_params()
                self.parse_results()
                methods.append(name)
            self.skip_semis()
        self.expect("}")
        return methods

    # ------------------------------------------------------------ statements

    def parse_block(self):
        self.expect("{")
        statements = []
        self.skip_semis()
        while not self.at("}"):
            statements.append(self.parse_statement())
            self.skip_semis()
        self.expect("}")
        return statements

    def parse_statement(self):
        line = self.token.line

        if self.at("{"):
            return ("block", self.parse_block(), line)
        if self.accept("var"):
            return ("varblock", self.parse_var_group(), line)
        if self.accept("const"):
            return ("varblock", self.parse_const_group(), line)
        if self.at("type"):
            unit = {"types": {}}
            self.parse_type_decl(unit)
            return ("localtype", unit["types"], line)
        if self.accept("return"):
            values = []
            if not self.at(";") and not self.at("}"):
                values.append(self.parse_expression())
                while self.accept(","):
                    values.append(self.parse_expression())
            return ("return", values, line)
        if self.accept("break"):
            label = self.next().value if self.token.kind == "id" else None
            return ("break", label, line)
        if self.accept("continue"):
            label = self.next().value if self.token.kind == "id" else None
            return ("continue", label, line)
        if self.accept("fallthrough"):
            return ("fallthrough", line)
        if self.accept("goto"):
            self.next()
            raise LangSyntaxError("goto is not supported", line)
        if self.at("if"):
            return self.parse_if()
        if self.at("for"):
            return self.parse_for()
        if self.at("switch"):
            return self.parse_switch()
        if self.at("select"):
            return self.parse_select()
        if self.accept("defer"):
            return ("defer", self.parse_expression(), line)
        if self.accept("go"):
            return ("go", self.parse_expression(), line)

        # A label, which only `break`/`continue` care about.
        if self.token.kind == "id" and self.peek().value == ":" and \
                self.peek(2).value in ("for", "switch", "select"):
            label = self.next().value
            self.expect(":")
            return ("label", label, self.parse_statement(), line)

        return self.parse_simple_statement()

    def parse_simple_statement(self):
        line = self.token.line
        if self.at(";"):
            return ("empty", line)

        first = self.parse_expression()

        if self.at(",") or self.token.value in ASSIGN_OPS or self.at(":="):
            targets = [first]
            while self.accept(","):
                targets.append(self.parse_expression())
            operator = self.token.value
            if operator == ":=":
                self.next()
                values = [self.parse_expression()]
                while self.accept(","):
                    values.append(self.parse_expression())
                return ("define", targets, values, line)
            if operator in ASSIGN_OPS:
                self.next()
                values = [self.parse_expression()]
                while self.accept(","):
                    values.append(self.parse_expression())
                return ("assign", targets, operator, values, line)
            raise LangSyntaxError("expected an assignment", line)

        if self.at("++") or self.at("--"):
            operator = self.next().value
            return ("incdec", first, operator, line)

        if self.accept("<-"):
            return ("send", first, self.parse_expression(), line)

        return ("expr", first, line)

    def parse_var_group(self):
        declarations = []
        if self.accept("("):
            self.skip_semis()
            while not self.at(")"):
                declarations.append(self.parse_var_line())
                self.skip_semis()
            self.expect(")")
        else:
            declarations.append(self.parse_var_line())
        return declarations

    def parse_var_line(self):
        line = self.token.line
        names = [self.next().value]
        while self.accept(","):
            names.append(self.next().value)
        declared = None
        if not self.at("=") and not self.at(";") and not self.at(")"):
            declared = self.parse_type()
        values = []
        if self.accept("="):
            values.append(self.parse_expression())
            while self.accept(","):
                values.append(self.parse_expression())
        return (names, declared, values, line)

    def parse_const_group(self):
        """`iota` counts within a const block, which is where it is legal."""
        declarations = []
        if self.accept("("):
            self.skip_semis()
            index = 0
            previous = None
            while not self.at(")"):
                names, declared, values, line = self.parse_var_line()
                if not values and previous is not None:
                    values = previous
                else:
                    previous = values
                declarations.append((names, declared, values, line, index))
                index += 1
                self.skip_semis()
            self.expect(")")
        else:
            names, declared, values, line = self.parse_var_line()
            declarations.append((names, declared, values, line, 0))
        return declarations

    def parse_if(self):
        line = self.token.line
        self.expect("if")
        self.no_literal += 1
        init = None
        condition = self.parse_simple_or_expression()
        if self.at(";"):
            self.next()
            init = condition
            condition = self.parse_expression()
        elif condition[0] != "expr":
            raise LangSyntaxError("if wants a condition", line)
        if isinstance(condition, tuple) and condition[0] == "expr":
            condition = condition[1]
        self.no_literal -= 1

        then = self.parse_block()
        otherwise = None
        if self.accept("else"):
            if self.at("if"):
                otherwise = [self.parse_if()]
            else:
                otherwise = self.parse_block()
        return ("if", init, condition, then, otherwise, line)

    def parse_simple_or_expression(self):
        return self.parse_simple_statement()

    def parse_for(self):
        line = self.token.line
        self.expect("for")
        self.no_literal += 1

        if self.at("{"):
            self.no_literal -= 1
            return ("for", None, None, None, self.parse_block(), line)

        # `for range ch {}` with no variables.
        if self.at("range"):
            self.next()
            subject = self.parse_expression()
            self.no_literal -= 1
            return ("range", None, None, subject, self.parse_block(), False, line)

        first = self.parse_simple_statement()

        # `for k, v := range xs` and `for i := range n`.
        if first[0] in ("define", "assign") and len(first[2 if first[0] == "define" else 3]) == 1:
            values = first[2] if first[0] == "define" else first[3]
            if values[0][0] == "range":
                targets = first[1]
                key = targets[0] if targets else None
                value = targets[1] if len(targets) > 1 else None
                self.no_literal -= 1
                return ("range", key, value, values[0][1],
                        self.parse_block(), first[0] == "define", line)

        if self.at("{"):
            self.no_literal -= 1
            if first[0] != "expr":
                raise LangSyntaxError("for wants a condition", line)
            return ("for", None, first[1], None, self.parse_block(), line)

        self.expect(";")
        condition = None
        if not self.at(";"):
            condition = self.parse_expression()
        self.expect(";")
        post = None
        if not self.at("{"):
            post = self.parse_simple_statement()
        self.no_literal -= 1
        return ("for", first, condition, post, self.parse_block(), line)

    def parse_switch(self):
        line = self.token.line
        self.expect("switch")
        self.no_literal += 1
        init = None
        tag = None
        type_switch = None

        if not self.at("{"):
            first = self.parse_simple_statement()
            if self.at(";"):
                self.next()
                init = first
                if not self.at("{"):
                    first = self.parse_simple_statement()
                else:
                    first = None
            if first is not None:
                if first[0] == "define" and first[2] and first[2][0][0] == "typeassert" \
                        and first[2][0][2] is None:
                    type_switch = (first[1][0][1], first[2][0][1])
                elif first[0] == "expr" and first[1][0] == "typeassert" and first[1][2] is None:
                    type_switch = (None, first[1][1])
                elif first[0] == "expr":
                    tag = first[1]
                else:
                    init = first
        self.no_literal -= 1

        self.expect("{")
        self.skip_semis()
        cases = []
        default = None
        while not self.at("}"):
            if self.accept("case"):
                if type_switch is not None:
                    matches = [self.parse_type()]
                    while self.accept(","):
                        matches.append(self.parse_type())
                else:
                    matches = [self.parse_expression()]
                    while self.accept(","):
                        matches.append(self.parse_expression())
                self.expect(":")
                cases.append((matches, self.parse_case_body()))
            elif self.accept("default"):
                self.expect(":")
                default = self.parse_case_body()
            else:
                raise LangSyntaxError(
                    f"expected case or default, found {self.token.value!r}", self.token.line
                )
            self.skip_semis()
        self.expect("}")

        if type_switch is not None:
            return ("typeswitch", init, type_switch[0], type_switch[1], cases, default, line)
        return ("switch", init, tag, cases, default, line)

    def parse_case_body(self):
        statements = []
        self.skip_semis()
        while not self.at("case") and not self.at("default") and not self.at("}"):
            statements.append(self.parse_statement())
            self.skip_semis()
        return statements

    def parse_select(self):
        line = self.token.line
        self.expect("select")
        self.expect("{")
        self.skip_semis()
        cases = []
        default = None
        while not self.at("}"):
            if self.accept("case"):
                comm = self.parse_simple_statement()
                self.expect(":")
                cases.append((comm, self.parse_case_body()))
            elif self.accept("default"):
                self.expect(":")
                default = self.parse_case_body()
            self.skip_semis()
        self.expect("}")
        return ("select", cases, default, line)

    # ----------------------------------------------------------- expressions

    def parse_expression(self, level=0):
        if level >= len(BINARY_LEVELS):
            return self.parse_unary()

        left = self.parse_expression(level + 1)
        while self.token.kind == "op" and self.token.value in BINARY_LEVELS[level]:
            operator = self.next().value
            line = self.token.line
            right = self.parse_expression(level + 1)
            left = ("bin", operator, left, right, line)
        return left

    def parse_unary(self):
        line = self.token.line
        if self.at("range"):
            # Only legal in a `for` header, where the statement parser looks
            # for exactly this node.
            self.next()
            return ("range", self.parse_expression(), line)
        if self.token.kind == "op" and self.token.value in ("-", "+", "!", "^", "*", "&"):
            operator = self.next().value
            return ("unary", operator, self.parse_unary(), line)
        if self.accept("<-"):
            return ("recv", self.parse_unary(), line)
        return self.parse_postfix(self.parse_primary())

    def parse_postfix(self, node):
        while True:
            line = self.token.line
            if self.accept("."):
                if self.accept("("):
                    if self.accept("type"):
                        self.expect(")")
                        node = ("typeassert", node, None, line)
                        continue
                    wanted = self.parse_type()
                    self.expect(")")
                    node = ("typeassert", node, wanted, line)
                    continue
                node = ("field", node, self.next().value, line)
            elif self.at("("):
                node = ("call", node, *self.parse_arguments(), line)
            elif self.accept("["):
                if self.accept(":"):
                    high = None if self.at("]") else self.parse_expression()
                    self.expect("]")
                    node = ("slice", node, None, high, line)
                    continue
                index = self.parse_expression()
                if self.accept(":"):
                    high = None if self.at("]") else self.parse_expression()
                    self.expect("]")
                    node = ("slice", node, index, high, line)
                    continue
                self.expect("]")
                node = ("index", node, index, line)
            elif self.at("{") and self.no_literal == 0 and node[0] in ("name", "field"):
                node = ("complit", self.node_to_type(node), self.parse_literal_body(), line)
            else:
                return node

    def node_to_type(self, node):
        if node[0] == "name":
            return ("named", node[1])
        if node[0] == "field":
            return ("named", f"{node[1][1]}.{node[2]}")
        raise LangSyntaxError("not a type", node[-1])

    def parse_arguments(self):
        self.expect("(")
        arguments = []
        spread = False
        saved = self.no_literal
        self.no_literal = 0
        while not self.at(")"):
            self.skip_semis()
            if self.at(")"):
                break
            # `[]int` here may be a type - make([]int, 3) - or the head of a
            # literal - []int{1, 2}. parse_primary tells them apart by what
            # follows, so it does the work rather than a guess here.
            arguments.append(self.parse_expression())
            if self.accept("..."):
                spread = True
            self.accept(",")
            self.skip_semis()
        self.no_literal = saved
        self.expect(")")
        return arguments, spread

    def parse_literal_body(self):
        self.expect("{")
        items = []
        self.skip_semis()
        saved = self.no_literal
        self.no_literal = 0
        while not self.at("}"):
            key = None
            if self.at("{"):
                value = ("complit", None, self.parse_literal_body(), self.token.line)
            else:
                value = self.parse_expression()
            if self.accept(":"):
                key = value
                if self.at("{"):
                    value = ("complit", None, self.parse_literal_body(), self.token.line)
                else:
                    value = self.parse_expression()
            items.append((key, value))
            self.accept(",")
            self.skip_semis()
        self.no_literal = saved
        self.expect("}")
        return items

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
        if token.kind == "id":
            self.next()
            return ("name", token.value, line)

        if self.accept("("):
            saved = self.no_literal
            self.no_literal = 0
            inner = self.parse_expression()
            self.no_literal = saved
            self.expect(")")
            return inner

        if self.at("func"):
            self.next()
            params, variadic = self.parse_params()
            results = self.parse_results()
            saved = self.no_literal
            self.no_literal = 0
            body = self.parse_block()
            self.no_literal = saved
            return ("closure", params, variadic, results, body, line)

        if self.at("[") or self.at("map") or self.at("chan") or self.at("struct") or \
                self.at("interface"):
            declared = self.parse_type()
            if self.at("{"):
                return ("complit", declared, self.parse_literal_body(), line)
            return ("type", declared, line)

        if self.accept("*"):
            return ("unary", "*", self.parse_unary(), line)

        raise LangSyntaxError(f"unexpected {token.value!r}", line)


def parse(source: str) -> dict:
    return Parser(source).parse()
