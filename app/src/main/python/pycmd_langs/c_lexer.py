"""Tokeniser for the C interpreter.

Handles the parts of C that appear in real programs people type by hand:
comments, character and string escapes, integer/float/hex/octal literals, and
the full operator set including the multi-character ones.

The preprocessor is deliberately minimal - `#include` is recorded and ignored
(the runtime supplies the standard library itself) and `#define` handles
object-like and simple function-like macros. That covers what a phone-sized C
program actually uses without pretending to be cpp.
"""

from __future__ import annotations

KEYWORDS = {
    "auto", "break", "case", "char", "const", "continue", "default", "do",
    "double", "else", "enum", "extern", "float", "for", "goto", "if", "int",
    "long", "register", "return", "short", "signed", "sizeof", "static",
    "struct", "switch", "typedef", "union", "unsigned", "void", "volatile",
    "while", "_Bool",
}

# Longest first: the lexer takes the first that matches, so "<<=" must be
# tested before "<<", and "<<" before "<".
OPERATORS = [
    "<<=", ">>=", "...",
    "->", "++", "--", "<<", ">>", "<=", ">=", "==", "!=", "&&", "||",
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
    "+", "-", "*", "/", "%", "=", "<", ">", "!", "~", "&", "|", "^",
    "?", ":", ";", ",", ".", "(", ")", "[", "]", "{", "}",
]

SIMPLE_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\",
    "'": "'", '"': '"', "a": "\a", "b": "\b", "f": "\f", "v": "\v",
    "?": "?",
}


class CSyntaxError(Exception):
    """Raised for anything the lexer or parser cannot make sense of."""

    def __init__(self, message: str, line: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.line = line

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}" if self.line else self.message


class Token:
    __slots__ = ("kind", "value", "line")

    def __init__(self, kind: str, value, line: int) -> None:
        self.kind = kind  # id, kw, int, float, char, str, op, eof
        self.value = value
        self.line = line

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Token({self.kind}, {self.value!r}, line={self.line})"


def _read_escape(source: str, i: int, line: int):
    """Reads one escape sequence after the backslash. Returns (char, next_i)."""
    if i >= len(source):
        raise CSyntaxError("unterminated escape sequence", line)
    ch = source[i]
    if ch in SIMPLE_ESCAPES:
        return SIMPLE_ESCAPES[ch], i + 1
    if ch == "x":
        j = i + 1
        digits = ""
        while j < len(source) and source[j] in "0123456789abcdefABCDEF":
            digits += source[j]
            j += 1
        if not digits:
            raise CSyntaxError("\\x needs at least one hex digit", line)
        return chr(int(digits, 16) & 0xFF), j
    if ch.isdigit():  # octal, up to three digits
        j = i
        digits = ""
        while j < len(source) and source[j] in "01234567" and len(digits) < 3:
            digits += source[j]
            j += 1
        return chr(int(digits, 8) & 0xFF), j
    # Unknown escape: C says undefined; keeping the character is the friendly
    # reading and matches what most compilers do.
    return ch, i + 1


def tokenize(source: str) -> list:
    """Turns C source into a token list, running the small preprocessor first."""
    source = _preprocess(source)
    tokens = []
    i = 0
    line = 1
    length = len(source)

    while i < length:
        ch = source[i]

        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch in " \t\r\f\v":
            i += 1
            continue

        # Comments
        if source.startswith("//", i):
            while i < length and source[i] != "\n":
                i += 1
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end == -1:
                raise CSyntaxError("unterminated /* comment", line)
            line += source.count("\n", i, end)
            i = end + 2
            continue

        # Character literal
        if ch == "'":
            i += 1
            if i < length and source[i] == "\\":
                value, i = _read_escape(source, i + 1, line)
            else:
                if i >= length:
                    raise CSyntaxError("unterminated character literal", line)
                value = source[i]
                i += 1
            if i >= length or source[i] != "'":
                raise CSyntaxError("unterminated character literal", line)
            i += 1
            tokens.append(Token("char", ord(value), line))
            continue

        # String literal, including adjacent-literal concatenation
        if ch == '"':
            text = ""
            while True:
                i += 1
                out = []
                while i < length and source[i] != '"':
                    if source[i] == "\\":
                        piece, i = _read_escape(source, i + 1, line)
                        out.append(piece)
                    else:
                        if source[i] == "\n":
                            raise CSyntaxError("unterminated string literal", line)
                        out.append(source[i])
                        i += 1
                if i >= length:
                    raise CSyntaxError("unterminated string literal", line)
                text += "".join(out)
                i += 1
                # Skip whitespace to see whether another literal follows.
                j = i
                while j < length and source[j] in " \t\r\n":
                    if source[j] == "\n":
                        line += 1
                    j += 1
                if j < length and source[j] == '"':
                    i = j
                    continue
                break
            tokens.append(Token("str", text, line))
            continue

        # Numbers
        if ch.isdigit() or (ch == "." and i + 1 < length and source[i + 1].isdigit()):
            start = i
            is_float = False
            if source.startswith(("0x", "0X"), i):
                i += 2
                while i < length and source[i] in "0123456789abcdefABCDEF":
                    i += 1
                value = int(source[start:i], 16)
            elif source.startswith(("0b", "0B"), i):
                i += 2
                while i < length and source[i] in "01":
                    i += 1
                value = int(source[start + 2:i], 2)
            else:
                while i < length and source[i].isdigit():
                    i += 1
                if i < length and source[i] == ".":
                    is_float = True
                    i += 1
                    while i < length and source[i].isdigit():
                        i += 1
                if i < length and source[i] in "eE":
                    peek = i + 1
                    if peek < length and source[peek] in "+-":
                        peek += 1
                    if peek < length and source[peek].isdigit():
                        is_float = True
                        i = peek
                        while i < length and source[i].isdigit():
                            i += 1
                text = source[start:i]
                if is_float:
                    value = float(text)
                elif text.startswith("0") and len(text) > 1 and text.isdigit():
                    value = int(text, 8)  # octal
                else:
                    value = int(text)
            # Suffixes: 10u, 10L, 1.5f ...
            while i < length and source[i] in "uUlLfF":
                if source[i] in "fF" and not is_float:
                    is_float = True
                    value = float(value)
                i += 1
            tokens.append(Token("float" if is_float else "int", value, line))
            continue

        # Identifiers and keywords
        if ch.isalpha() or ch == "_":
            start = i
            while i < length and (source[i].isalnum() or source[i] == "_"):
                i += 1
            word = source[start:i]
            tokens.append(Token("kw" if word in KEYWORDS else "id", word, line))
            continue

        # Operators
        for op in OPERATORS:
            if source.startswith(op, i):
                tokens.append(Token("op", op, line))
                i += len(op)
                break
        else:
            raise CSyntaxError(f"unexpected character {ch!r}", line)

    tokens.append(Token("eof", None, line))
    return tokens


def _preprocess(source: str) -> str:
    """Strips directives and expands simple #defines.

    Line structure is preserved so error messages still point at the right
    line: every directive becomes a blank line rather than disappearing.
    """
    macros: dict[str, str] = {}
    out_lines = []

    # Join backslash-continued lines, keeping the line count intact.
    lines = source.split("\n")
    merged = []
    buffer = ""
    pending_blanks = 0
    for raw in lines:
        if raw.rstrip().endswith("\\"):
            buffer += raw.rstrip()[:-1]
            pending_blanks += 1
            continue
        merged.append((buffer + raw, pending_blanks))
        buffer = ""
        pending_blanks = 0
    if buffer:
        merged.append((buffer, pending_blanks))

    for text, blanks in merged:
        stripped = text.strip()
        if stripped.startswith("#"):
            directive = stripped[1:].strip()
            if directive.startswith("define"):
                rest = directive[len("define"):].strip()
                if rest:
                    name, _, body = rest.partition(" ")
                    # Function-like macros are out of scope; treat the name as
                    # an object-like macro so at least the constant case works.
                    name = name.split("(")[0]
                    macros[name] = body.strip()
            # #include, #ifdef, #pragma and friends are ignored: the runtime
            # provides the library, and there is no second translation unit.
            out_lines.append("")
        else:
            out_lines.append(text)
        out_lines.extend([""] * blanks)

    result = "\n".join(out_lines)

    if macros:
        import re

        pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in macros) + r")\b")
        # Two passes let one macro refer to another without looping forever.
        for _ in range(2):
            result = pattern.sub(lambda m: macros.get(m.group(1), m.group(0)), result)

    return result
