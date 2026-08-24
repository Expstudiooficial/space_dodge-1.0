"""The Rust evaluator.

Walks what :mod:`rust_parser` produces. Like the Go interpreter it is dynamic:
types are parsed and dropped, and ownership and borrowing are not enforced.
That is the honest trade - a phone cannot run rustc, and a borrow checker is
most of rustc - and it is stated plainly in the language note rather than
hidden, because a program that compiles will run here, while a program that
would not compile may also run.

What is real: traits and their default methods, impl blocks, enums with
payloads, `match` with proper patterns, closures, iterator chains, `?`,
`Option` and `Result`, and the macros.
"""

from __future__ import annotations

import sys

from .clike_lexer import LangSyntaxError
from . import rust_parser, rust_stdlib
from .rust_values import (
    Bound, Char, Enum, Formatter, Func, Iter, NONE, Native, Range, Ref, Struct,
    UNIT, Unit, RustError, RustPanic, clone_value, debug, display, err, is_none,
    is_some, ok, some, type_label, unref,
)


class Env:
    __slots__ = ("values", "parent")

    def __init__(self, parent=None) -> None:
        self.values = {}
        self.parent = parent

    def define(self, name, value) -> None:
        self.values[name] = value

    def has(self, name) -> bool:
        scope = self
        while scope is not None:
            if name in scope.values:
                return True
            scope = scope.parent
        return False

    def lookup(self, name):
        scope = self
        while scope is not None:
            if name in scope.values:
                return scope.values[name]
            scope = scope.parent
        raise RustError(f"cannot find value `{name}` in this scope")

    def assign(self, name, value) -> None:
        scope = self
        while scope is not None:
            if name in scope.values:
                scope.values[name] = value
                return
            scope = scope.parent
        raise RustError(f"cannot find value `{name}` in this scope")

    def cell(self, name):
        scope = self
        while scope is not None:
            if name in scope.values:
                return scope
            scope = scope.parent
        raise RustError(f"cannot find value `{name}` in this scope")


class VariantCtor:
    """`Shape::Circle` before it has been given its payload."""

    __slots__ = ("enum", "variant", "arity", "shape")

    def __init__(self, enum, variant, arity, shape="tuple") -> None:
        self.enum = enum
        self.variant = variant
        self.arity = arity
        self.shape = shape


class _Return(Exception):
    def __init__(self, value) -> None:
        self.value = value


class _Break(Exception):
    def __init__(self, value=UNIT) -> None:
        self.value = value


class _Continue(Exception):
    pass


class Interpreter:

    def __init__(self, stdout=None, stdin=None, argv=None) -> None:
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stdin = stdin if stdin is not None else sys.stdin
        self.argv = argv or ["main"]
        self.globals = Env()
        self.structs = {}
        self.enums = {}
        self.variants = {}
        self.methods = {}
        self.traits = {}
        self.implemented = {}
        self.collect_hints = []

    # ---------------------------------------------------------------- setup

    def load(self, unit) -> None:
        rust_stdlib.build_paths(self)
        self.structs.update(unit["structs"])
        self.enums.update(unit["enums"])

        for enum_name, variants in unit["enums"].items():
            for variant, (shape, detail) in variants.items():
                self.variants[variant] = (enum_name, shape, detail)
                self.variants[f"{enum_name}::{variant}"] = (enum_name, shape, detail)

        for name, functions in unit["traits"].items():
            self.traits[name] = functions

        for type_name, trait_name, functions, line in unit["impls"]:
            table = self.methods.setdefault(type_name, {})
            for name, node in functions.items():
                table[name] = (node, type_name)
            if trait_name:
                self.implemented.setdefault(type_name, []).append(trait_name)

        for name, node in unit["functions"].items():
            self.globals.define(name, Func(name, node[2], node[4], self.globals, node[3]))

        for name, value in unit["consts"]:
            self.globals.define(name, self.evaluate(value, self.globals))

    def run(self) -> int:
        if not self.globals.has("main"):
            raise RustError("no main function")
        self.call(self.globals.lookup("main"), [], 0)
        return 0

    # ----------------------------------------------------------- statements

    def execute_block(self, block, env):
        """A block is an expression: its value is its tail, or `()`."""
        _, statements, tail, line = block
        scope = Env(env)
        for statement in statements:
            self.execute(statement, scope)
        if tail is None:
            return UNIT
        return self.evaluate(tail, scope)

    def execute(self, statement, env) -> None:
        kind = statement[0]
        if kind == "semi":
            self.evaluate(statement[1], env)
            return
        if kind == "let":
            self.execute_let(statement, env)
            return
        if kind == "item":
            inner = statement[1]
            self.load(inner)
            return
        raise RustError(f"cannot execute {kind}", statement[-1])

    def execute_let(self, statement, env) -> None:
        pattern, value_node, declared = statement[1], statement[2], statement[3]
        otherwise = statement[5] if len(statement) > 5 else None

        if value_node is None:
            # `let x;` reserves the name; the first assignment fills it.
            if pattern[0] == "bind":
                env.define(pattern[1], UNIT)
            return

        self.collect_hints.append(declared)
        try:
            value = self.evaluate(value_node, env)
        finally:
            self.collect_hints.pop()

        bindings = {}
        if not self.match_pattern(pattern, value, bindings, env):
            if otherwise is not None:
                self.execute_block(otherwise, env)
                return
            raise RustPanic("a `let` pattern did not match the value")
        for name, bound in bindings.items():
            env.define(name, bound)

    # ---------------------------------------------------------- expressions

    def evaluate(self, node, env):
        kind = node[0]

        if kind == "int" or kind == "float" or kind == "bool":
            return node[1]
        if kind == "str":
            return node[1]
        if kind == "char":
            return Char(node[1])
        if kind == "unit":
            return UNIT
        if kind == "path":
            return self.evaluate_path(node[1], env, node[2])
        if kind == "block":
            return self.execute_block(node, env)
        if kind == "bin":
            return self.evaluate_binary(node, env)
        if kind == "unary":
            value = unref(self.evaluate(node[2], env))
            if node[1] == "-":
                return -value
            return not value if isinstance(value, bool) else ~int(value)
        if kind == "ref":
            return self.evaluate_ref(node, env)
        if kind == "deref":
            return unref(self.evaluate(node[1], env))
        if kind == "assign":
            return self.evaluate_assign(node, env)
        if kind == "call":
            return self.evaluate_call(node, env)
        if kind == "method":
            return self.evaluate_method(node, env)
        if kind == "field":
            return self.evaluate_field(node, env)
        if kind == "index":
            return self.evaluate_index(node, env)
        if kind == "macro":
            return rust_stdlib.run_macro(self, node[1], node[2], node[3], env, node[4])
        if kind == "structlit":
            return self.evaluate_struct_literal(node, env)
        if kind == "tuple":
            return tuple(self.evaluate(item, env) for item in node[1])
        if kind == "array":
            if node[2] is not None:
                value = self.evaluate(node[1][0], env)
                return [clone_value(value) for _ in range(int(self.evaluate(node[2], env)))]
            return [self.evaluate(item, env) for item in node[1]]
        if kind == "range":
            start = self.evaluate(node[1], env) if node[1] is not None else 0
            end = self.evaluate(node[2], env) if node[2] is not None else None
            return Range(unref(start), unref(end) if end is not None else None, node[3])
        if kind == "closure":
            return Func("", node[1], node[2], env)
        if kind == "if":
            return self.evaluate_if(node, env)
        if kind == "iflet":
            return self.evaluate_if_let(node, env)
        if kind == "match":
            return self.evaluate_match(node, env)
        if kind == "loop":
            return self.evaluate_loop(node, env)
        if kind == "while":
            return self.evaluate_while(node, env)
        if kind == "whilelet":
            return self.evaluate_while_let(node, env)
        if kind == "for":
            return self.evaluate_for(node, env)
        if kind == "return":
            raise _Return(self.evaluate(node[1], env) if node[1] is not None else UNIT)
        if kind == "break":
            raise _Break(self.evaluate(node[1], env) if node[1] is not None else UNIT)
        if kind == "continue":
            raise _Continue()
        if kind == "try":
            return self.evaluate_try(node, env)
        if kind == "cast":
            return self.evaluate_cast(node, env)
        raise RustError(f"cannot evaluate {kind}", node[-1])

    def evaluate_path(self, parts, env, line):
        if len(parts) == 1:
            name = parts[0]
            if env.has(name):
                return env.lookup(name)
            if name == "None":
                return NONE
            if name in ("Some", "Ok", "Err"):
                return VariantCtor("Option" if name == "Some" else "Result", name, 1)
            if name in self.variants:
                return self.variant_value(name, line)
            if name in self.structs or name in self.methods:
                return name
            builtin = rust_stdlib.path_value(self, parts, line)
            if builtin is not None:
                return builtin
            raise RustError(f"cannot find value `{name}` in this scope", line)

        head = parts[0]
        if head == "Self" and env.has("__Self"):
            head = env.lookup("__Self")
            parts = [head] + list(parts[1:])

        joined = "::".join(parts)
        if joined in self.variants:
            return self.variant_value(joined, line)
        if head in self.enums and parts[-1] in self.enums[head]:
            return self.variant_value(f"{head}::{parts[-1]}", line)
        if head in ("Option", "Result"):
            tail = parts[-1]
            if tail == "None":
                return NONE
            if tail in ("Some", "Ok", "Err"):
                return VariantCtor(head, tail, 1)

        found = self.lookup_method(head, parts[-1])
        if found is not None:
            node, owner = found
            return Func(parts[-1], node[2], node[4], self.globals, node[3], owner)

        builtin = rust_stdlib.path_value(self, parts, line)
        if builtin is not None:
            return builtin

        if env.has(parts[-1]):
            return env.lookup(parts[-1])
        raise RustError(f"cannot find `{joined}`", line)

    def variant_value(self, name, line):
        enum_name, shape, detail = self.variants[name]
        variant = name.split("::")[-1]
        if shape == "unit":
            return Enum(enum_name, variant, [], "unit")
        if shape == "named":
            return VariantCtor(enum_name, variant, len(detail), "named")
        return VariantCtor(enum_name, variant, detail, "tuple")

    def lookup_method(self, type_name, name):
        table = self.methods.get(type_name)
        if table is not None and name in table:
            return table[name]
        # A trait's default body applies to every type that implements it.
        for trait_name in self.implemented.get(type_name, []):
            functions = self.traits.get(trait_name, {})
            if name in functions and functions[name][4] is not None:
                return (functions[name], type_name)
        return None

    def evaluate_binary(self, node, env):
        _, operator, left_node, right_node, line = node

        if operator == "&&":
            return bool(unref(self.evaluate(left_node, env))) and \
                bool(unref(self.evaluate(right_node, env)))
        if operator == "||":
            return bool(unref(self.evaluate(left_node, env))) or \
                bool(unref(self.evaluate(right_node, env)))

        left = unref(self.evaluate(left_node, env))
        right = unref(self.evaluate(right_node, env))
        return self.binary(operator, left, right, line)

    def binary(self, operator, left, right, line):
        if operator == "==":
            return self.equal(left, right)
        if operator == "!=":
            return not self.equal(left, right)
        if operator in ("<", "<=", ">", ">="):
            try:
                if operator == "<":
                    return left < right
                if operator == "<=":
                    return left <= right
                if operator == ">":
                    return left > right
                return left >= right
            except TypeError:
                raise RustError(
                    f"cannot compare {type_label(left)} with {type_label(right)}", line
                ) from None

        if operator == "+":
            if isinstance(left, str) or isinstance(right, str):
                if not isinstance(left, str):
                    raise RustError("cannot add a string to a number", line)
                return left + display(right, self)
            return self.arith(left + right, left, right)
        if operator == "-":
            return self.arith(left - right, left, right)
        if operator == "*":
            return self.arith(left * right, left, right)
        if operator == "/":
            if right == 0 and not isinstance(left, float) and not isinstance(right, float):
                raise RustPanic("attempt to divide by zero")
            if isinstance(left, float) or isinstance(right, float):
                return left / right
            quotient = abs(left) // abs(right)
            return -quotient if (left < 0) != (right < 0) else quotient
        if operator == "%":
            if right == 0:
                raise RustPanic("attempt to calculate the remainder with a divisor of zero")
            if isinstance(left, float) or isinstance(right, float):
                import math

                return math.fmod(left, right)
            remainder = abs(left) % abs(right)
            return -remainder if left < 0 else remainder
        if operator == "&":
            return int(left) & int(right)
        if operator == "|":
            return int(left) | int(right)
        if operator == "^":
            return int(left) ^ int(right)
        if operator == "<<":
            return int(left) << int(right)
        if operator == ">>":
            return int(left) >> int(right)
        raise RustError(f"unknown operator {operator}", line)

    def arith(self, result, left, right):
        if isinstance(left, bool) or isinstance(right, bool):
            raise RustError("arithmetic on a bool")
        return result

    def equal(self, left, right) -> bool:
        left, right = unref(left), unref(right)
        if isinstance(left, bool) != isinstance(right, bool):
            return False
        try:
            return bool(left == right)
        except Exception:  # noqa: BLE001
            return left is right

    def evaluate_ref(self, node, env):
        inner = node[1]
        mutable = node[2]
        if not mutable:
            return self.evaluate(inner, env)

        # A mutable borrow of something Python cannot mutate in place has to
        # carry the place with it, or `*n += 1` would update a copy.
        if inner[0] == "path" and len(inner[1]) == 1 and env.has(inner[1][0]):
            name = inner[1][0]
            current = env.lookup(name)
            if isinstance(current, (int, float, str, bool, tuple, Unit)) or \
                    isinstance(current, Enum):
                scope = env.cell(name)
                return Ref(lambda: scope.values[name],
                           lambda value: scope.values.__setitem__(name, value))
            return current
        if inner[0] == "index":
            container = unref(self.evaluate(inner[1], env))
            index = unref(self.evaluate(inner[2], env))
            if isinstance(container, dict):
                key = rust_stdlib._key(index)
                return Ref(lambda: container[key],
                           lambda value: container.__setitem__(key, value))
            if isinstance(container, list):
                position = int(index)
                item = container[position]
                if isinstance(item, (int, float, str, bool)):
                    return Ref(lambda: container[position],
                               lambda value: container.__setitem__(position, value))
                return item
        if inner[0] == "field":
            owner = unref(self.evaluate(inner[1], env))
            name = inner[2]
            if isinstance(owner, Struct):
                current = owner.fields.get(name)
                if isinstance(current, (int, float, str, bool)):
                    return Ref(lambda: owner.fields[name],
                               lambda value: owner.fields.__setitem__(name, value))
                return current
        return self.evaluate(inner, env)

    def evaluate_assign(self, node, env):
        _, target, operator, value_node, line = node
        value = self.evaluate(value_node, env)
        if operator != "=":
            current = unref(self.evaluate(target, env))
            value = self.binary(operator[:-1], current, unref(value), line)
        self.assign_to(target, value, env)
        return UNIT

    def assign_to(self, target, value, env) -> None:
        kind = target[0]
        if kind == "path" and len(target[1]) == 1:
            name = target[1][0]
            if env.has(name):
                current = env.lookup(name)
                if isinstance(current, Ref):
                    current.set(value)
                    return
            env.assign(name, value)
            return
        if kind == "deref":
            holder = self.evaluate(target[1], env)
            if isinstance(holder, Ref):
                holder.set(value)
                return
            self.assign_to(target[1], value, env)
            return
        if kind == "index":
            container = unref(self.evaluate(target[1], env))
            index = unref(self.evaluate(target[2], env))
            if isinstance(container, dict):
                container[rust_stdlib._key(index)] = value
                return
            if isinstance(container, list):
                position = int(index)
                if position >= len(container):
                    raise RustPanic(
                        f"index out of bounds: the len is {len(container)} "
                        f"but the index is {position}"
                    )
                container[position] = value
                return
            raise RustError(f"cannot index {type_label(container)}", target[3])
        if kind == "field":
            owner = unref(self.evaluate(target[1], env))
            if isinstance(owner, Struct):
                owner.fields[target[2]] = value
                return
            if isinstance(owner, Enum) and isinstance(owner.values, dict):
                owner.values[target[2]] = value
                return
            raise RustError(f"cannot set field `{target[2]}`", target[3])
        raise RustError("cannot assign to this expression", target[-1])

    def evaluate_call(self, node, env):
        _, callee, argument_nodes, line = node
        function = self.evaluate(callee, env)
        arguments = [self.evaluate(item, env) for item in argument_nodes]
        return self.call(function, arguments, line)

    def call(self, function, arguments, line):
        if isinstance(function, VariantCtor):
            if function.shape == "named":
                raise RustError(
                    f"`{function.variant}` is built with braces, not brackets", line
                )
            return Enum(function.enum, function.variant, list(arguments), "tuple")
        if isinstance(function, Native):
            return function.call(arguments)
        if isinstance(function, Bound):
            return self.invoke(function.func, arguments, line, function.receiver)
        if isinstance(function, Func):
            return self.invoke(function, arguments, line)
        if isinstance(function, str) and function in self.structs:
            # A tuple struct used as a constructor: `Wrapper(3)`.
            return self.build_struct(function, list(arguments), line)
        raise RustError(f"`{type_label(function)}` is not callable", line)

    def invoke(self, function, arguments, line, receiver=None):
        env = Env(function.env)
        if function.owner:
            env.define("__Self", function.owner)
        if function.takes_self:
            env.define("self", receiver)

        if len(arguments) != len(function.params):
            raise RustError(
                f"this function takes {len(function.params)} arguments but "
                f"{len(arguments)} were supplied", line
            )
        for pattern, value in zip(function.params, arguments):
            bindings = {}
            if not self.match_pattern(pattern, value, bindings, env):
                raise RustError("an argument did not match its pattern", line)
            for name, bound in bindings.items():
                env.define(name, bound)

        if function.body is None:
            raise RustError(f"`{function.name}` has no body", line)

        try:
            if function.body[0] == "block":
                return self.execute_block(function.body, env)
            return self.evaluate(function.body, env)
        except _Return as returned:
            return returned.value

    def evaluate_method(self, node, env):
        _, receiver_node, name, argument_nodes, hint, line = node
        receiver = self.place_receiver(receiver_node, env)
        arguments = [self.evaluate(item, env) for item in argument_nodes]
        return self.call_method(receiver, name, arguments, hint, line, receiver_node, env)

    def place_receiver(self, node, env):
        """Evaluates a method's receiver, keeping hold of where it lives.

        `s.push_str("x")` has to write back into `s`, and a Python string
        cannot be changed in place, so the receiver arrives as a reference to
        the variable when the value is one of the immutable kinds.
        """
        value = self.evaluate(node, env)
        if isinstance(value, Ref) or not isinstance(value, (str, int, float, bool, tuple)):
            return value
        if node[0] == "path" and len(node[1]) == 1 and env.has(node[1][0]):
            name = node[1][0]
            scope = env.cell(name)
            return Ref(lambda: scope.values[name],
                       lambda new: scope.values.__setitem__(name, new))
        return value

    def call_method(self, receiver, name, arguments, hint, line, receiver_node=None, env=None):
        target = unref(receiver)

        if isinstance(target, rust_stdlib._Entry):
            _, result = rust_stdlib.entry_method(self, target, name, arguments, line)
            return result

        type_name = None
        if isinstance(target, Struct):
            type_name = target.name
        elif isinstance(target, Enum):
            type_name = target.enum
        elif isinstance(target, str) and target in self.methods:
            type_name = target

        if type_name is not None:
            found = self.lookup_method(type_name, name)
            if found is not None:
                node, owner = found
                function = Func(name, node[2], node[4], self.globals, node[3], owner)
                if not function.takes_self:
                    return self.invoke(function, arguments, line)
                return self.invoke(function, arguments, line, target)

        handled, result = rust_stdlib.call_method(self, receiver, name, arguments, hint, line)
        if handled:
            return result

        if hint is None and name == "collect":
            return list(rust_stdlib._iterate(target))

        raise RustError(
            f"no method named `{name}` on `{type_label(target)}`", line
        )

    def evaluate_field(self, node, env):
        _, owner_node, name, line = node
        owner = unref(self.evaluate(owner_node, env))

        if isinstance(owner, Struct):
            if name in owner.fields:
                return owner.fields[name]
            raise RustError(f"`{owner.name}` has no field `{name}`", line)
        if isinstance(owner, Enum) and isinstance(owner.values, dict):
            if name in owner.values:
                return owner.values[name]
        if isinstance(owner, tuple) and name.isdigit():
            index = int(name)
            if index >= len(owner):
                raise RustError(f"a {len(owner)}-tuple has no field `{name}`", line)
            return owner[index]
        if isinstance(owner, Enum) and name.isdigit():
            return owner.values[int(name)]
        raise RustError(f"`{type_label(owner)}` has no field `{name}`", line)

    def evaluate_index(self, node, env):
        _, owner_node, index_node, line = node
        owner = unref(self.evaluate(owner_node, env))
        index = unref(self.evaluate(index_node, env))

        if isinstance(index, Range):
            stop = index.end
            if stop is not None and index.inclusive:
                stop += 1
            if isinstance(owner, str):
                return owner[index.start:stop]
            if isinstance(owner, list):
                return owner[index.start:stop]

        if isinstance(owner, list):
            position = int(index)
            if position < 0 or position >= len(owner):
                raise RustPanic(
                    f"index out of bounds: the len is {len(owner)} "
                    f"but the index is {position}"
                )
            return owner[position]
        if isinstance(owner, dict):
            key = rust_stdlib._key(index)
            if key not in owner:
                raise RustPanic("key not found in the map")
            return owner[key]
        if isinstance(owner, str):
            raise RustError(
                "a String cannot be indexed by a number in Rust; "
                "use .chars().nth(i) or a range", line
            )
        raise RustError(f"cannot index `{type_label(owner)}`", line)

    def evaluate_struct_literal(self, node, env):
        _, parts, body, line = node
        fields, rest = body
        name = parts[-1]
        if name == "Self" and env.has("__Self"):
            name = env.lookup("__Self")

        joined = "::".join(parts)
        if joined in self.variants or (len(parts) > 1 and parts[-1] in
                                       self.enums.get(parts[0], {})):
            enum_name, shape, detail = self.variants.get(joined, self.variants.get(name))
            values = {field: self.evaluate(value, env) for field, value in fields}
            return Enum(enum_name, name, values, "named")
        if name in self.variants and name not in self.structs:
            enum_name, shape, detail = self.variants[name]
            values = {field: self.evaluate(value, env) for field, value in fields}
            return Enum(enum_name, name, values, "named")

        values = {}
        if rest is not None:
            base = unref(self.evaluate(rest, env))
            if isinstance(base, Struct):
                values.update({k: clone_value(v) for k, v in base.fields.items()})
        for field, value_node in fields:
            values[field] = self.evaluate(value_node, env)

        declared = self.structs.get(name)
        if declared is not None:
            shape, names = declared
            ordered = {}
            for field in names:
                if field in values:
                    ordered[field] = values[field]
                elif rest is None:
                    raise RustError(f"missing field `{field}` in `{name}`", line)
            ordered.update({k: v for k, v in values.items() if k not in ordered})
            return Struct(name, ordered, shape)
        return Struct(name, values, "named")

    def build_struct(self, name, arguments, line):
        shape, names = self.structs[name]
        if len(arguments) != len(names):
            raise RustError(
                f"`{name}` takes {len(names)} values but {len(arguments)} were given", line
            )
        return Struct(name, dict(zip(names, arguments)), shape)

    def evaluate_if(self, node, env):
        _, condition, then, otherwise, line = node
        if unref(self.evaluate(condition, env)):
            return self.execute_block(then, env)
        if otherwise is None:
            return UNIT
        if otherwise[0] == "block":
            return self.execute_block(otherwise, env)
        return self.evaluate(otherwise, env)

    def evaluate_if_let(self, node, env):
        _, pattern, subject_node, then, otherwise, line = node
        subject = self.evaluate(subject_node, env)
        bindings = {}
        if self.match_pattern(pattern, subject, bindings, env):
            scope = Env(env)
            for name, value in bindings.items():
                scope.define(name, value)
            return self.execute_block(then, scope)
        if otherwise is None:
            return UNIT
        if otherwise[0] == "block":
            return self.execute_block(otherwise, env)
        return self.evaluate(otherwise, env)

    def evaluate_match(self, node, env):
        _, subject_node, arms, line = node
        subject = self.evaluate(subject_node, env)

        for pattern, guard, body in arms:
            bindings = {}
            if not self.match_pattern(pattern, subject, bindings, env):
                continue
            scope = Env(env)
            for name, value in bindings.items():
                scope.define(name, value)
            if guard is not None and not unref(self.evaluate(guard, scope)):
                continue
            if body[0] == "block":
                return self.execute_block(body, scope)
            return self.evaluate(body, scope)

        raise RustPanic(
            f"no match arm covers {debug(unref(subject), self)}"
        )

    def evaluate_loop(self, node, env):
        while True:
            try:
                self.execute_block(node[1], env)
            except _Break as stop:
                return stop.value
            except _Continue:
                continue

    def evaluate_while(self, node, env):
        _, condition, body, line = node
        while unref(self.evaluate(condition, env)):
            try:
                self.execute_block(body, env)
            except _Break:
                break
            except _Continue:
                continue
        return UNIT

    def evaluate_while_let(self, node, env):
        _, pattern, subject_node, body, line = node
        while True:
            subject = self.evaluate(subject_node, env)
            bindings = {}
            if not self.match_pattern(pattern, subject, bindings, env):
                return UNIT
            scope = Env(env)
            for name, value in bindings.items():
                scope.define(name, value)
            try:
                self.execute_block(body, scope)
            except _Break:
                return UNIT
            except _Continue:
                continue

    def evaluate_for(self, node, env):
        _, pattern, subject_node, body, line = node
        subject = unref(self.evaluate(subject_node, env))
        for item in rust_stdlib._iterate(subject):
            scope = Env(env)
            bindings = {}
            if not self.match_pattern(pattern, item, bindings, env):
                raise RustPanic("a `for` pattern did not match an item")
            for name, value in bindings.items():
                scope.define(name, value)
            try:
                self.execute_block(body, scope)
            except _Break:
                break
            except _Continue:
                continue
        return UNIT

    def evaluate_try(self, node, env):
        value = unref(self.evaluate(node[1], env))
        if isinstance(value, Enum):
            if value.enum == "Result":
                if value.variant == "Err":
                    raise _Return(value)
                return value.values[0]
            if value.enum == "Option":
                if value.variant == "None":
                    raise _Return(NONE)
                return value.values[0]
        return value

    def evaluate_cast(self, node, env):
        value = unref(self.evaluate(node[1], env))
        target = node[2]
        if target in rust_stdlib.FLOAT_TYPES:
            return float(value)
        if target in rust_stdlib.INT_TYPES:
            if isinstance(value, Char):
                return ord(value)
            number = int(value)
            bits = int("".join(c for c in target if c.isdigit()) or 64)
            if target.startswith("u"):
                return number & ((1 << bits) - 1)
            mask = (1 << bits) - 1
            number &= mask
            return number - (1 << bits) if number & (1 << (bits - 1)) else number
        if target == "char":
            return Char(chr(int(value)))
        if target == "bool":
            return bool(value)
        return value

    # -------------------------------------------------------------- patterns

    def match_pattern(self, pattern, value, bindings, env) -> bool:
        kind = pattern[0]

        # A plain binding keeps whatever it was given, including a `&mut`
        # borrow - that is the whole point of passing one to a function.
        if kind == "any":
            return True
        if kind == "bind":
            bindings[pattern[1]] = value
            return True

        value = unref(value)
        if kind == "at":
            bindings[pattern[1]] = value
            return self.match_pattern(pattern[2], value, bindings, env)
        if kind == "or":
            for alternative in pattern[1]:
                if self.match_pattern(alternative, value, bindings, env):
                    return True
            return False
        if kind == "literal":
            literal = pattern[1]
            expected = Char(literal[1]) if literal[0] == "char" else literal[1]
            return self.equal(value, expected)
        if kind == "rangepat":
            low, high, inclusive = pattern[1], pattern[2], pattern[3]
            if isinstance(value, str):
                low, high = str(low), str(high)
            try:
                return low <= value <= high if inclusive else low <= value < high
            except TypeError:
                return False
        if kind == "tuplepat":
            if not isinstance(value, tuple) or len(value) != len(pattern[1]):
                return False
            return all(
                self.match_pattern(item, part, bindings, env)
                for item, part in zip(pattern[1], value)
            )
        if kind == "slicepat":
            if not isinstance(value, list) or len(value) != len(pattern[1]):
                return False
            return all(
                self.match_pattern(item, part, bindings, env)
                for item, part in zip(pattern[1], value)
            )
        if kind == "enumpat":
            return self.match_enum(pattern, value, bindings, env)
        if kind == "structpat":
            name = pattern[1][-1]
            if isinstance(value, Struct):
                if value.name != name and name not in ("Self",):
                    return False
                for field, sub in pattern[2]:
                    if field not in value.fields:
                        return False
                    if not self.match_pattern(sub, value.fields[field], bindings, env):
                        return False
                return True
            if isinstance(value, Enum) and value.variant == name:
                for field, sub in pattern[2]:
                    if field not in value.values:
                        return False
                    if not self.match_pattern(sub, value.values[field], bindings, env):
                        return False
                return True
            return False
        raise RustError(f"cannot match {kind}", pattern[-1])

    def match_enum(self, pattern, value, bindings, env) -> bool:
        parts = pattern[1]
        name = parts[-1]
        payload = pattern[2]

        if isinstance(value, Enum):
            if value.variant != name:
                return False
            if not payload:
                return True
            values = value.values
            if isinstance(values, dict):
                values = list(values.values())
            if len(payload) != len(values):
                return False
            return all(
                self.match_pattern(item, part, bindings, env)
                for item, part in zip(payload, values)
            )

        if isinstance(value, Struct) and value.name == name:
            values = list(value.fields.values())
            if len(payload) != len(values):
                return False
            return all(
                self.match_pattern(item, part, bindings, env)
                for item, part in zip(payload, values)
            )

        # A constant used as a pattern: `MAX => ...`.
        if not payload and env.has(name):
            return self.equal(value, env.lookup(name))
        return False

    # --------------------------------------------------------------- output

    def user_display(self, value):
        """Renders through a user's `impl Display`, when there is one."""
        type_name = value.name if isinstance(value, Struct) else value.enum
        found = self.lookup_method(type_name, "fmt")
        if found is None:
            found = self.lookup_method(type_name, "to_string")
            if found is None:
                return None
            node, owner = found
            function = Func("to_string", node[2], node[4], self.globals, node[3], owner)
            return display(self.invoke(function, [], 0, value), self)

        node, owner = found
        function = Func("fmt", node[2], node[4], self.globals, node[3], owner)
        formatter = Formatter()
        try:
            self.invoke(function, [formatter], 0, value)
        except RustError:
            return None
        return formatter.text()

    def write(self, text) -> None:
        self.stdout.write(text)

    def write_error(self, text) -> None:
        try:
            sys.stderr.write(text)
        except Exception:  # noqa: BLE001
            self.stdout.write(text)

    def read_line(self):
        line = self.stdin.readline()
        if not line:
            return None
        return line.rstrip("\n")


def run_source(source: str, stdout=None, stdin=None, argv=None) -> int:
    """Parses and runs a Rust program, returning its exit status."""
    unit = rust_parser.parse(source)
    interpreter = Interpreter(stdout=stdout, stdin=stdin, argv=argv)
    interpreter.load(unit)

    previous = sys.getrecursionlimit()
    sys.setrecursionlimit(max(previous, 6000))
    try:
        return interpreter.run()
    except SystemExit as request:
        return int(request.code or 0)
    except RustPanic as panic:
        raise RustError(f"thread 'main' panicked: {panic.message}") from None
    except RecursionError:
        raise RustError("stack overflow: the call stack got too deep") from None
    finally:
        sys.setrecursionlimit(previous)
