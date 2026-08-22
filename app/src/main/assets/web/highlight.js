/**
 * Python syntax highlighter.
 *
 * One pass, one regex. Ordering inside the pattern matters: comments and
 * strings come first so that a `#` inside a string, or a keyword inside a
 * comment, is never mistaken for code.
 */
(function (global) {
  'use strict';

  var KEYWORDS = [
    'and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue',
    'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global',
    'if', 'import', 'in', 'is', 'lambda', 'match', 'nonlocal', 'not', 'or',
    'pass', 'raise', 'return', 'try', 'while', 'with', 'yield'
  ];

  var CONSTANTS = ['True', 'False', 'None'];

  var BUILTINS = [
    'abs', 'all', 'any', 'bin', 'bool', 'bytearray', 'bytes', 'callable',
    'chr', 'classmethod', 'compile', 'complex', 'dict', 'dir', 'divmod',
    'enumerate', 'eval', 'exec', 'filter', 'float', 'format', 'frozenset',
    'getattr', 'globals', 'hasattr', 'hash', 'help', 'hex', 'id', 'input',
    'int', 'isinstance', 'issubclass', 'iter', 'len', 'list', 'locals', 'map',
    'max', 'min', 'next', 'object', 'oct', 'open', 'ord', 'pow', 'print',
    'property', 'range', 'repr', 'reversed', 'round', 'set', 'setattr',
    'slice', 'sorted', 'staticmethod', 'str', 'sum', 'super', 'tuple', 'type',
    'vars', 'zip'
  ];

  var KEYWORD_SET = toSet(KEYWORDS);
  var CONSTANT_SET = toSet(CONSTANTS);
  var BUILTIN_SET = toSet(BUILTINS);

  function toSet(list) {
    var set = Object.create(null);
    for (var i = 0; i < list.length; i += 1) {
      set[list[i]] = true;
    }
    return set;
  }

  var HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;' };

  function escapeHtml(text) {
    return text.replace(/[&<>]/g, function (char) {
      return HTML_ESCAPES[char];
    });
  }

  // Alternatives in priority order: triple-quoted strings, single-quoted
  // strings, comments, decorators, numbers, identifiers, operators.
  var TOKEN_PATTERN = new RegExp(
    [
      '([rbuf]{0,2})("""[^]*?"""|\'\'\'[^]*?\'\'\')',
      '([rbuf]{0,2})("(?:\\\\.|[^"\\\\\\n])*"|\'(?:\\\\.|[^\'\\\\\\n])*\')',
      '(#[^\\n]*)',
      '(@[A-Za-z_][A-Za-z0-9_.]*)',
      '(\\b(?:0[xXbBoO][0-9a-fA-F_]+|\\d[\\d_]*(?:\\.[\\d_]*)?(?:[eE][+-]?\\d+)?[jJ]?)\\b)',
      '([A-Za-z_][A-Za-z0-9_]*)',
      '([+\\-*/%=<>!&|^~@]+)'
    ].join('|'),
    'g'
  );

  /**
   * @param {string} source Python source text.
   * @returns {string} HTML with `tok-*` spans, safe to assign to innerHTML.
   */
  function highlight(source) {
    var out = '';
    var lastIndex = 0;
    var match;
    var previousWord = '';

    TOKEN_PATTERN.lastIndex = 0;
    while ((match = TOKEN_PATTERN.exec(source)) !== null) {
      out += escapeHtml(source.slice(lastIndex, match.index));
      var token = match[0];

      if (match[2] !== undefined || match[4] !== undefined) {
        out += span('tok-str', token);
      } else if (match[5] !== undefined) {
        out += span('tok-comment', token);
      } else if (match[6] !== undefined) {
        out += span('tok-decorator', token);
      } else if (match[7] !== undefined) {
        out += span('tok-num', token);
      } else if (match[8] !== undefined) {
        out += identifier(token, previousWord);
        previousWord = token;
      } else if (match[9] !== undefined) {
        out += span('tok-op', token);
      } else {
        out += escapeHtml(token);
      }

      if (match[8] === undefined) {
        previousWord = '';
      }
      lastIndex = match.index + token.length;
    }

    out += escapeHtml(source.slice(lastIndex));
    return out;
  }

  function identifier(name, previousWord) {
    if (previousWord === 'def' || previousWord === 'class') {
      return span('tok-def', name);
    }
    if (KEYWORD_SET[name]) {
      return span('tok-kw', name);
    }
    if (CONSTANT_SET[name]) {
      return span('tok-num', name);
    }
    if (name === 'self' || name === 'cls') {
      return span('tok-self', name);
    }
    if (BUILTIN_SET[name]) {
      return span('tok-builtin', name);
    }
    return escapeHtml(name);
  }

  function span(className, text) {
    return '<span class="' + className + '">' + escapeHtml(text) + '</span>';
  }

  global.PyHighlight = { highlight: highlight, keywords: KEYWORDS, builtins: BUILTINS };
})(window);
