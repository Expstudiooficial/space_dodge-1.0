/**
 * Code editor.
 *
 * A transparent `<textarea>` sits on top of a highlighted `<pre>`: the textarea
 * keeps the platform caret, selection handles, IME and clipboard behaviour that
 * a hand-rolled editor always gets wrong, while the pre underneath supplies the
 * colour. The two only stay aligned if their font metrics and padding match,
 * which is why editor.css sets both from the same variables.
 *
 * Kotlin talks to this file through `window.PyEditor`; this file talks back
 * through `window.PyBridge` (a @JavascriptInterface object).
 */
(function (global) {
  'use strict';

  var INDENT = '    ';
  var SYNC_DELAY = 120; // ms of quiet before the host is told about an edit.

  var input = document.getElementById('input');
  var highlightCode = document.getElementById('highlight-code');
  var surface = document.getElementById('surface');
  var gutterInner = document.getElementById('gutter-inner');

  var syncTimer = null;
  var lineCount = -1;
  var suppressChangeEvent = false;

  var PAIRS = { '(': ')', '[': ']', '{': '}', '"': '"', "'": "'" };
  var CLOSERS = { ')': true, ']': true, '}': true, '"': true, "'": true };

  // ----------------------------------------------------------------- rendering

  function render() {
    var text = input.value;
    highlightCode.innerHTML = global.PyHighlight.highlight(text);
    resize();
    renderGutter(text);
    highlightActiveLine();
  }

  function resize() {
    // Height first: the textarea must be exactly as tall as its content so the
    // surrounding surface, not the textarea, does the scrolling.
    input.style.height = 'auto';
    input.style.height = input.scrollHeight + 'px';

    var contentWidth = highlightCode.scrollWidth + 24;
    var width = Math.max(surface.clientWidth, contentWidth);
    input.style.width = width + 'px';
  }

  function renderGutter(text) {
    var lines = countLines(text);
    if (lines === lineCount) {
      return;
    }
    lineCount = lines;

    var html = '';
    for (var i = 1; i <= lines; i += 1) {
      html += '<span class="num" data-line="' + i + '">' + i + '</span>';
    }
    gutterInner.innerHTML = html;
  }

  function countLines(text) {
    var count = 1;
    for (var i = 0; i < text.length; i += 1) {
      if (text.charCodeAt(i) === 10) {
        count += 1;
      }
    }
    return count;
  }

  function currentLine() {
    var upto = input.value.slice(0, input.selectionStart);
    return countLines(upto);
  }

  function currentColumn() {
    var upto = input.value.slice(0, input.selectionStart);
    var lastBreak = upto.lastIndexOf('\n');
    return input.selectionStart - lastBreak;
  }

  var activeNumber = null;

  function highlightActiveLine() {
    var line = currentLine();
    if (activeNumber && activeNumber.dataset.line === String(line)) {
      return;
    }
    if (activeNumber) {
      activeNumber.classList.remove('active');
    }
    activeNumber = gutterInner.querySelector('[data-line="' + line + '"]');
    if (activeNumber) {
      activeNumber.classList.add('active');
    }
  }

  // ------------------------------------------------------------------- editing

  /**
   * Inserts text at the caret through the browser's own editing command, so a
   * single Ctrl-Z / long-press-undo reverses it. Falls back to a direct value
   * splice where the command is unavailable.
   */
  function insertText(text) {
    input.focus();
    var inserted = false;
    try {
      inserted = document.execCommand('insertText', false, text);
    } catch (error) {
      inserted = false;
    }
    if (!inserted) {
      var start = input.selectionStart;
      var end = input.selectionEnd;
      input.value = input.value.slice(0, start) + text + input.value.slice(end);
      var caret = start + text.length;
      input.setSelectionRange(caret, caret);
      onInput();
    }
  }

  function setSelection(start, end) {
    input.setSelectionRange(start, end === undefined ? start : end);
  }

  function indentOf(line) {
    var match = /^[ \t]*/.exec(line);
    return match ? match[0] : '';
  }

  function lineStartIndex(position) {
    return input.value.lastIndexOf('\n', position - 1) + 1;
  }

  function handleEnter(event) {
    event.preventDefault();
    var start = input.selectionStart;
    var lineStart = lineStartIndex(start);
    var line = input.value.slice(lineStart, start);
    var indent = indentOf(line);
    var trimmed = line.trim();

    // A block opener earns an extra level; a dedent keyword loses one.
    if (/:\s*(#.*)?$/.test(trimmed)) {
      indent += INDENT;
    } else if (/^(return|pass|break|continue|raise)\b/.test(trimmed) && indent.length >= INDENT.length) {
      indent = indent.slice(0, indent.length - INDENT.length);
    }

    var closer = input.value.charAt(input.selectionEnd);
    if (CLOSERS[closer] && (closer === ')' || closer === ']' || closer === '}')) {
      // Put the closing bracket on its own line, indented back out.
      var outer = indentOf(line);
      insertText('\n' + indent + '\n' + outer);
      setSelection(start + 1 + indent.length);
      scheduleSync();
      render();
      return;
    }

    insertText('\n' + indent);
  }

  function handleTab(event) {
    event.preventDefault();
    var start = input.selectionStart;
    var end = input.selectionEnd;

    if (start === end) {
      if (event.shiftKey) {
        outdentLines(start, end);
      } else {
        insertText(INDENT);
      }
      return;
    }
    if (event.shiftKey) {
      outdentLines(start, end);
    } else {
      indentLines(start, end);
    }
  }

  function selectedLineRange(start, end) {
    var from = lineStartIndex(start);
    var to = input.value.indexOf('\n', end);
    if (to === -1) {
      to = input.value.length;
    }
    return { from: from, to: to };
  }

  function indentLines(start, end) {
    var range = selectedLineRange(start, end);
    var block = input.value.slice(range.from, range.to);
    var updated = block.split('\n').map(function (line) {
      return INDENT + line;
    }).join('\n');
    replaceRange(range.from, range.to, updated);
    setSelection(start + INDENT.length, end + (updated.length - block.length));
  }

  function outdentLines(start, end) {
    var range = selectedLineRange(start, end);
    var block = input.value.slice(range.from, range.to);
    var removedFirst = 0;
    var first = true;
    var updated = block.split('\n').map(function (line) {
      var removed = 0;
      while (removed < INDENT.length && line.charAt(0) === ' ') {
        line = line.slice(1);
        removed += 1;
      }
      if (removed === 0 && line.charAt(0) === '\t') {
        line = line.slice(1);
        removed = 1;
      }
      if (first) {
        removedFirst = removed;
        first = false;
      }
      return line;
    }).join('\n');
    replaceRange(range.from, range.to, updated);
    var delta = block.length - updated.length;
    setSelection(Math.max(range.from, start - removedFirst), Math.max(range.from, end - delta));
  }

  function replaceRange(from, to, text) {
    input.setSelectionRange(from, to);
    insertText(text);
  }

  function handleBackspace(event) {
    if (input.selectionStart !== input.selectionEnd) {
      return;
    }
    var start = input.selectionStart;
    if (start === 0) {
      return;
    }

    // Delete a full indent level when the caret sits in leading whitespace.
    var lineStart = lineStartIndex(start);
    var before = input.value.slice(lineStart, start);
    if (before.length > 0 && /^ +$/.test(before) && before.length % INDENT.length === 0) {
      event.preventDefault();
      input.setSelectionRange(start - INDENT.length, start);
      insertText('');
      return;
    }

    // Delete both halves of an auto-inserted pair.
    var previous = input.value.charAt(start - 1);
    var next = input.value.charAt(start);
    if (PAIRS[previous] && PAIRS[previous] === next) {
      event.preventDefault();
      input.setSelectionRange(start - 1, start + 1);
      insertText('');
    }
  }

  function handleAutoPair(event) {
    var char = event.key;
    var start = input.selectionStart;
    var end = input.selectionEnd;

    // Typing a closer that is already there just steps over it.
    if (CLOSERS[char] && start === end && input.value.charAt(start) === char) {
      event.preventDefault();
      setSelection(start + 1);
      return true;
    }

    if (!PAIRS[char]) {
      return false;
    }

    if (start !== end) {
      // Wrap the selection instead of replacing it.
      event.preventDefault();
      var selected = input.value.slice(start, end);
      insertText(char + selected + PAIRS[char]);
      setSelection(start + 1, start + 1 + selected.length);
      return true;
    }

    // Do not auto-close a quote in the middle of a word.
    var next = input.value.charAt(start);
    if (next && /[A-Za-z0-9_"']/.test(next)) {
      return false;
    }

    event.preventDefault();
    insertText(char + PAIRS[char]);
    setSelection(start + 1);
    return true;
  }

  // -------------------------------------------------------------------- events

  function onInput() {
    render();
    scheduleSync();
  }

  function scheduleSync() {
    if (suppressChangeEvent) {
      return;
    }
    if (syncTimer !== null) {
      global.clearTimeout(syncTimer);
    }
    syncTimer = global.setTimeout(function () {
      syncTimer = null;
      notifyHost();
    }, SYNC_DELAY);
  }

  function notifyHost() {
    if (global.PyBridge && global.PyBridge.onEditorChanged) {
      global.PyBridge.onEditorChanged(input.value);
    }
  }

  function notifyCursor() {
    if (global.PyBridge && global.PyBridge.onCursorMoved) {
      global.PyBridge.onCursorMoved(currentLine(), currentColumn());
    }
  }

  input.addEventListener('input', onInput);

  input.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
      handleEnter(event);
    } else if (event.key === 'Tab') {
      handleTab(event);
    } else if (event.key === 'Backspace') {
      handleBackspace(event);
    } else if (event.key.length === 1) {
      handleAutoPair(event);
    }
  });

  ['click', 'keyup', 'select', 'focus'].forEach(function (name) {
    input.addEventListener(name, function () {
      highlightActiveLine();
      notifyCursor();
    });
  });

  surface.addEventListener('scroll', function () {
    gutterInner.style.transform = 'translateY(' + -surface.scrollTop + 'px)';
  }, { passive: true });

  global.addEventListener('resize', function () {
    resize();
  });

  // ---------------------------------------------------------------- public API

  global.PyEditor = {
    /** Replaces the whole document without emitting a change back to the host. */
    setContent: function (text) {
      suppressChangeEvent = true;
      input.value = text || '';
      input.setSelectionRange(0, 0);
      lineCount = -1;
      render();
      surface.scrollTop = 0;
      surface.scrollLeft = 0;
      gutterInner.style.transform = 'translateY(0px)';
      suppressChangeEvent = false;
    },

    /** Switches which grammar the highlighter uses, and repaints. */
    setLanguage: function (name) {
      if (global.PyHighlight && global.PyHighlight.setLanguage) {
        global.PyHighlight.setLanguage(name);
        lineCount = -1;
        render();
      }
    },

    insert: function (text) {
      insertText(text);
      onInput();
      notifyCursor();
    },

    /**
     * Inserts a snippet and puts the caret where the snippet wants it.
     *
     * Without the second step every snippet would leave the caret at its end,
     * which for a function body is the wrong side of the closing brace.
     */
    insertSnippet: function (text, caret) {
      var start = input.selectionStart;
      insertText(text);
      var target = start + (typeof caret === 'number' ? caret : text.length);
      input.setSelectionRange(target, target);
      onInput();
      notifyCursor();
      render();
    },

    indent: function () {
      indentLines(input.selectionStart, input.selectionEnd);
      onInput();
    },

    outdent: function () {
      outdentLines(input.selectionStart, input.selectionEnd);
      onInput();
    },

    undo: function () {
      input.focus();
      try {
        document.execCommand('undo');
      } catch (error) {
        // Nothing to undo, or the command is unsupported.
      }
      onInput();
    },

    redo: function () {
      input.focus();
      try {
        document.execCommand('redo');
      } catch (error) {
        // Nothing to redo, or the command is unsupported.
      }
      onInput();
    },

    focus: function () {
      input.focus();
    }
  };

  render();

  if (global.PyBridge && global.PyBridge.onEditorReady) {
    global.PyBridge.onEditorReady();
  }
})(window);
