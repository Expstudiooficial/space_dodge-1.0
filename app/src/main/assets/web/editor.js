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
  // ms of quiet before the colours are recomputed. Typing repaints the text
  // immediately in one colour; the tokeniser runs once the burst is over.
  var PAINT_DELAY = 90;
  // Above this, a keystroke repaints plain text and waits for the pause to
  // colour it. Below it, everything happens on the spot and the delay is
  // never noticed.
  var BIG_DOCUMENT = 8000;

  var input = document.getElementById('input');
  var highlightCode = document.getElementById('highlight-code');
  var surface = document.getElementById('surface');
  var gutterInner = document.getElementById('gutter-inner');

  var syncTimer = null;
  var paintTimer = null;
  var lineCount = -1;
  var suppressChangeEvent = false;
  var lastSent = null;
  var lastPainted = null;
  var HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;' };

  var PAIRS = { '(': ')', '[': ']', '{': '}', '"': '"', "'": "'" };
  var CLOSERS = { ')': true, ']': true, '}': true, '"': true, "'": true };

  // ----------------------------------------------------------------- rendering

  function escapeHtml(text) {
    return text.replace(/[&<>]/g, function (char) {
      return HTML_ESCAPES[char];
    });
  }

  /**
   * Repaints the layer under the textarea.
   *
   * The textarea's own text is transparent - the `<pre>` beneath is what you
   * actually read - so this cannot simply be deferred while typing, or the
   * document would disappear for as long as the delay. Instead a big document
   * is painted twice: plain text now, so the keystroke lands instantly, and
   * coloured once the typing stops. A small one is coloured straight away,
   * because tokenising it costs less than the two paints would.
   */
  function render(immediate) {
    var text = input.value;
    var big = text.length > BIG_DOCUMENT;

    if (big && !immediate) {
      if (lastPainted !== text) {
        highlightCode.innerHTML = escapeHtml(text);
        lastPainted = text;
      }
      schedulePaint();
    } else {
      cancelPaint();
      highlightCode.innerHTML = global.PyHighlight.highlight(text);
      lastPainted = text;
    }

    resize();
    renderGutter(text);
    highlightActiveLine();
  }

  function schedulePaint() {
    if (paintTimer !== null) {
      global.clearTimeout(paintTimer);
    }
    paintTimer = global.setTimeout(function () {
      paintTimer = null;
      highlightCode.innerHTML = global.PyHighlight.highlight(input.value);
      lastPainted = input.value;
      resize();
    }, PAINT_DELAY);
  }

  function cancelPaint() {
    if (paintTimer !== null) {
      global.clearTimeout(paintTimer);
      paintTimer = null;
    }
  }

  var lastWidth = -1;

  function resize() {
    // Height first: the textarea must be exactly as tall as its content so the
    // surrounding surface, not the textarea, does the scrolling.
    //
    // Both reads below force the browser to lay the page out, which on a long
    // document is the single most expensive thing here - so the results are
    // compared before being written back. Assigning the same height again
    // would dirty the layout and make the next keystroke pay for it twice.
    input.style.height = 'auto';
    var height = input.scrollHeight;
    input.style.height = height + 'px';

    // Reading scrollWidth forces a second layout, so the result is kept and
    // the write skipped when nothing moved: on a long document that is the
    // difference between one reflow per keystroke and two.
    var width = Math.max(surface.clientWidth, highlightCode.scrollWidth + 24);
    if (width !== lastWidth) {
      lastWidth = width;
      input.style.width = width + 'px';
    }
  }

  function renderGutter(text) {
    var lines = countLines(text);
    if (lines === lineCount) {
      return;
    }

    // Growing by a line at a time is what typing does, so append rather than
    // rebuilding every number in the document.
    if (lines > lineCount && lineCount > 0) {
      var added = '';
      for (var next = lineCount + 1; next <= lines; next += 1) {
        added += '<span class="num" data-line="' + next + '">' + next + '</span>';
      }
      gutterInner.insertAdjacentHTML('beforeend', added);
      lineCount = lines;
      return;
    }

    lineCount = lines;
    var html = '';
    for (var i = 1; i <= lines; i += 1) {
      html += '<span class="num" data-line="' + i + '">' + i + '</span>';
    }
    gutterInner.innerHTML = html;
  }

  /**
   * Counts the lines in a string.
   *
   * `indexOf` is a native scan; the loop over `charCodeAt` this replaced was
   * pure interpreted JavaScript, and it ran on every keystroke, every click
   * and every caret move - three times over the whole document for one tap.
   */
  function countLines(text) {
    var count = 1;
    var at = text.indexOf('\n');
    while (at !== -1) {
      count += 1;
      at = text.indexOf('\n', at + 1);
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
    // The whole document crosses the bridge on every sync. Sending one that
    // has not changed - a caret move, a repaint - costs a copy of the string
    // on both sides for nothing.
    if (input.value === lastSent) {
      return;
    }
    lastSent = input.value;
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
      lastSent = input.value;
      render(true);
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
        lastPainted = null;
        render(true);
      }
    },

    insert: function (text) {
      // insertText already ends in a render: the browser's own input event
      // fires during execCommand, and the fallback path calls onInput itself.
      // Rendering again here painted every insertion twice.
      insertText(text);
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
      notifyCursor();
      highlightActiveLine();
    },

    indent: function () {
      indentLines(input.selectionStart, input.selectionEnd);
    },

    outdent: function () {
      outdentLines(input.selectionStart, input.selectionEnd);
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

  render(true);

  if (global.PyBridge && global.PyBridge.onEditorReady) {
    global.PyBridge.onEditorReady();
  }
})(window);
