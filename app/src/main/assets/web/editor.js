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

  var frame = document.getElementById('frame');
  var input = document.getElementById('input');
  var highlightCode = document.getElementById('highlight-code');
  var surface = document.getElementById('surface');
  var gutterInner = document.getElementById('gutter-inner');
  var ruler = document.getElementById('ruler');

  var syncTimer = null;
  var paintTimer = null;
  var suppressChangeEvent = false;
  var lastSent = null;
  var lastPainted = null;
  var wrapping = false;
  // Set while the keyboard is mid-word: swipe typing and autocorrect on
  // Android hold an open composition, and rewriting the layer underneath it
  // makes the keyboard lose track of what it was suggesting.
  var composing = false;
  var gutterCount = 0;
  var gutterWrapping = false;
  var gutterSignature = '';
  var HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;' };

  var PAIRS = { '(': ')', '[': ']', '{': '}', '"': '"', "'": "'" };
  var CLOSERS = { ')': true, ']': true, '}': true, '"': true, "'": true };

  // Which way this language indents. The editor runs six languages and used
  // Python's rules for all of them, so a Go file got no indent after `{` and
  // an outdent after the word `return` - which is exactly wrong there.
  // Keyed on the grammar name the host sends, which is what the language
  // registry calls it: Java and Kotlin both arrive as "c".
  var BRACE_LANGUAGES = {
    c: true, javascript: true, go: true, rust: true, json: true, css: true,
  };
  var braces = false;

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
    if (remeasureIfNeeded()) {
      // Everything sized from the guess has to be worked out again.
      lastWidth = -1;
      lastHeight = -1;
      gutterSignature = '';
    }

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

    // One pass over the document, shared: the sizing and the gutter both want
    // to know how many rows there are, and walking a long file twice for every
    // keystroke is exactly the kind of waste that shows up as lag.
    var plan = layout();
    resize(plan);
    renderGutter(plan);
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

  // --------------------------------------------------------------- geometry

  /**
   * How wide one character is, and how tall one line.
   *
   * Measured from the real font once, and then everything is arithmetic. The
   * first version asked the DOM how wide the highlighted layer had become,
   * which is a question with a fragile answer: an absolutely positioned box
   * shrink-to-fits within its container, so past a certain line length the
   * measurement stopped growing - and the textarea, sized from it, stopped
   * growing with it. That is what made the end of a long line unreachable.
   */
  var metrics = { char: 8, line: 21, padLeft: 12, padRight: 16, padTop: 10, padBottom: 60 };
  // Whether the numbers above came from a page that was actually on screen.
  var measured = false;

  function measure() {
    var sample = 'MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM';
    ruler.textContent = sample;
    var width = ruler.getBoundingClientRect().width / sample.length;
    ruler.textContent = '';
    if (width > 0) {
      metrics.char = width;
    }

    var style = global.getComputedStyle(input);
    var lineHeight = parseFloat(style.lineHeight);
    if (lineHeight > 0) {
      metrics.line = lineHeight;
    }
    metrics.padLeft = parseFloat(style.paddingLeft) || 0;
    metrics.padRight = parseFloat(style.paddingRight) || 0;
    metrics.padTop = parseFloat(style.paddingTop) || 0;
    metrics.padBottom = parseFloat(style.paddingBottom) || 0;

    // A page that is not on screen yet measures nothing, and this editor is
    // built before its tab is ever shown - so the first attempt lands on a
    // WebView with no width and every character is guessed at eight pixels.
    // Remembering that it was a guess is what lets the next render fix it.
    measured = width > 0 && surface.clientWidth > 0;
    return measured;
  }

  /** Re-measures once the page has a size, and once the font has settled. */
  function remeasureIfNeeded() {
    if (measured || surface.clientWidth <= 0) {
      return false;
    }
    var previous = metrics.char;
    measure();
    return measured && Math.abs(previous - metrics.char) > 0.01;
  }

  /** How many characters fit across, when wrapping. At least one. */
  function columnsPerRow() {
    var usable = surface.clientWidth - metrics.padLeft - metrics.padRight;
    return Math.max(1, Math.floor(usable / metrics.char));
  }

  var lastWidth = -1;
  var lastHeight = -1;

  /**
   * How many rows the document occupies, how wide its longest line is, and a
   * number that changes whenever either of those does.
   *
   * The signature exists because of a bug worth naming: while wrapping, the
   * gutter was rebuilt only when the *line count* changed, so typing into an
   * already-long line took it from twenty-eight rows to twenty-nine and the
   * numbers quietly slid out of step with the code. Counting rows is the only
   * thing that catches that.
   */
  function layout() {
    var lines = documentLines();
    var columns = wrapping ? columnsPerRow() : 0;
    var rows = 0;
    var longest = 0;
    var signature = 0;

    for (var i = 0; i < lines.length; i += 1) {
      var length = lines[i].length;
      if (length > longest) {
        longest = length;
      }
      var taken = wrapping ? Math.max(1, Math.ceil(length / columns)) : 1;
      rows += taken;
      // Weighted by position, so two lines swapping row counts in one edit
      // still reads as a change.
      signature = (signature * 31 + taken * (i + 1)) % 2147483647;
    }

    return {
      lines: lines.length,
      columns: columns,
      rows: rows,
      longest: longest,
      signature: lines.length + ':' + columns + ':' + rows + ':' + signature,
    };
  }

  function resize(plan) {
    plan = plan || layout();

    if (wrapping) {
      applySize(0, plan.rows);
      return;
    }
    // A couple of characters of slack so the caret at the end of the longest
    // line is inside the box rather than on its edge.
    var needed = Math.ceil((plan.longest + 2) * metrics.char)
      + metrics.padLeft + metrics.padRight;
    applySize(Math.max(surface.clientWidth, needed), plan.rows);
  }

  function applySize(width, rows) {
    var height = Math.round(rows * metrics.line) + metrics.padTop + metrics.padBottom;
    if (height !== lastHeight) {
      lastHeight = height;
      input.style.height = height + 'px';
    }

    if (wrapping) {
      if (lastWidth !== 0) {
        lastWidth = 0;
        input.style.width = '';
      }
      return;
    }
    if (width !== lastWidth) {
      lastWidth = width;
      input.style.width = width + 'px';
    }
  }

  /**
   * The document split into lines, cached until it changes.
   *
   * Both the gutter and the sizing want this, and splitting a large document
   * twice per keystroke is the kind of waste that turns into lag.
   */
  var cachedText = null;
  var cachedLines = [];

  function documentLines() {
    if (cachedText !== input.value) {
      cachedText = input.value;
      cachedLines = cachedText.split('\n');
    }
    return cachedLines;
  }

  function renderGutter(plan) {
    plan = plan || layout();
    if (plan.signature === gutterSignature) {
      return;
    }
    var lines = documentLines();

    // Typing at the end of a document adds lines one at a time, and appending
    // one number beats redrawing a thousand. Only when nothing is wrapping,
    // because a wrapped line's height can change without the count doing so.
    var appending = !wrapping && !gutterWrapping
      && gutterCount > 0 && plan.lines > gutterCount;

    if (appending) {
      var added = '';
      for (var next = gutterCount + 1; next <= plan.lines; next += 1) {
        added += numberHtml(next, 0);
      }
      gutterInner.insertAdjacentHTML('beforeend', added);
    } else {
      var html = '';
      for (var i = 1; i <= plan.lines; i += 1) {
        // When wrapping, a logical line can be several rows tall, and its
        // number has to be too or the gutter drifts out of step with the code.
        var rows = wrapping
          ? Math.max(1, Math.ceil(lines[i - 1].length / plan.columns))
          : 1;
        html += numberHtml(i, rows > 1 ? Math.round(rows * metrics.line) : 0);
      }
      gutterInner.innerHTML = html;
    }

    gutterCount = plan.lines;
    gutterWrapping = wrapping;
    gutterSignature = plan.signature;
    activeNumber = null;
  }

  function numberHtml(number, height) {
    return '<span class="num" data-line="' + number + '"'
      + (height ? ' style="height:' + height + 'px"' : '')
      + '>' + number + '</span>';
  }

  /**
   * Where the caret is, as a line and a column, without copying anything.
   *
   * The first version sliced the document up to the caret to count newlines -
   * on every click, every key-up and every selection change, twice over. On a
   * long file with the caret near the end that is a copy of the whole document
   * several times a second, which is a good deal of why the editor felt heavy.
   */
  function caretPosition() {
    var caret = input.selectionStart;
    var text = input.value;
    var line = 1;
    var lineStart = 0;
    var at = text.indexOf('\n');
    while (at !== -1 && at < caret) {
      line += 1;
      lineStart = at + 1;
      at = text.indexOf('\n', at + 1);
    }
    return { line: line, column: caret - lineStart + 1, start: lineStart };
  }

  function currentLine() {
    return caretPosition().line;
  }

  function currentColumn() {
    return caretPosition().column;
  }

  var activeNumber = null;

  /**
   * Scrolls so the caret is on screen.
   *
   * Typing off the right-hand edge of a long line used to leave the caret
   * somewhere past the visible area, which reads as the editor having stopped
   * accepting input. Worked out from the metrics rather than asked for,
   * because a textarea will not say where its caret is.
   */
  function scrollCaretIntoView() {
    var where = caretPosition();
    var line = where.line - 1;
    var column = where.column - 1;

    if (wrapping) {
      var columns = columnsPerRow();
      var lines = documentLines();
      var row = 0;
      for (var i = 0; i < line && i < lines.length; i += 1) {
        row += Math.max(1, Math.ceil(lines[i].length / columns));
      }
      row += Math.floor(column / columns);
      keepVisible(row, 0);
      return;
    }
    keepVisible(line, column);
  }

  function keepVisible(row, column) {
    var top = row * metrics.line + metrics.padTop;
    var viewTop = surface.scrollTop;
    var viewBottom = viewTop + surface.clientHeight;
    if (top < viewTop + metrics.line) {
      surface.scrollTop = Math.max(0, top - metrics.line * 2);
    } else if (top + metrics.line > viewBottom - metrics.line) {
      surface.scrollTop = top - surface.clientHeight + metrics.line * 3;
    }

    if (wrapping) {
      surface.scrollLeft = 0;
      return;
    }
    var left = column * metrics.char + metrics.padLeft;
    var viewLeft = surface.scrollLeft;
    var viewRight = viewLeft + surface.clientWidth;
    if (left < viewLeft + metrics.char * 2) {
      surface.scrollLeft = Math.max(0, left - metrics.char * 6);
    } else if (left > viewRight - metrics.char * 3) {
      surface.scrollLeft = left - surface.clientWidth + metrics.char * 6;
    }
  }

  function highlightActiveLine(known) {
    var line = known || currentLine();
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
    if (braces) {
      if (/[{[(]\s*(\/\/.*)?$/.test(trimmed)) {
        indent += INDENT;
      }
    } else if (/:\s*(#.*)?$/.test(trimmed)) {
      indent += INDENT;
    } else if (/^(return|pass|break|continue|raise)\b/.test(trimmed)
               && indent.length >= INDENT.length) {
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

  /**
   * A closing brace goes back out a level as you type it.
   *
   * Only in a brace language, and only when nothing but whitespace is in
   * front of it - otherwise `a[0]}` would jump about while being typed.
   */
  function handleClosingBrace(event) {
    if (!braces || event.key !== '}') {
      return false;
    }
    var start = input.selectionStart;
    if (start !== input.selectionEnd) {
      return false;
    }
    var lineStart = lineStartIndex(start);
    var before = input.value.slice(lineStart, start);
    if (!/^[ \t]+$/.test(before) || before.length < INDENT.length) {
      return false;
    }
    event.preventDefault();
    input.setSelectionRange(start - INDENT.length, start);
    insertText('}');
    return true;
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
    if (composing) {
      // The colours can wait a fraction of a second; a keyboard that has lost
      // its composition cannot be given it back.
      scheduleSync();
      return;
    }
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
      var where = caretPosition();
      global.PyBridge.onCursorMoved(where.line, where.column);
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
      if (!handleClosingBrace(event)) {
        handleAutoPair(event);
      }
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

  input.addEventListener('compositionstart', function () {
    composing = true;
  });

  input.addEventListener('compositionend', function () {
    composing = false;
    render();
  });

  global.addEventListener('resize', function () {
    // The width the surface offers has changed, so a wrapped document has a
    // different number of rows and the gutter has to be rebuilt.
    measure();
    gutterSignature = '';
    lastWidth = -1;
    lastHeight = -1;
    render(true);
  });

  // ---------------------------------------------------------------- public API

  global.PyEditor = {
    /** Replaces the whole document without emitting a change back to the host. */
    setContent: function (text) {
      suppressChangeEvent = true;
      input.value = text || '';
      input.setSelectionRange(0, 0);
      cachedText = null;
      gutterSignature = '';
      gutterCount = 0;
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
        braces = BRACE_LANGUAGES[name] === true;
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
      scrollCaretIntoView();
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
      scrollCaretIntoView();
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
    },

    /**
     * Wraps long lines instead of scrolling sideways.
     *
     * On a phone this is often the only way to see the end of a line at all.
     * The layer under the textarea gets the same rules so the colours stay
     * where the characters are, and the gutter gives each logical line as many
     * rows as it now takes.
     */
    setWrap: function (on) {
      wrapping = !!on;
      frame.classList.toggle('wrap', wrapping);
      input.setAttribute('wrap', wrapping ? 'soft' : 'off');
      gutterSignature = '';
      lastWidth = -1;
      lastHeight = -1;
      if (wrapping) {
        input.style.width = '';
        surface.scrollLeft = 0;
      }
      render(true);
      scrollCaretIntoView();
    },

    /** Puts the caret at the start of a line and scrolls it into view. */
    goToLine: function (number) {
      var lines = documentLines();
      var target = Math.min(Math.max(1, number | 0), lines.length);
      var index = 0;
      for (var i = 0; i < target - 1; i += 1) {
        index += lines[i].length + 1;
      }
      input.focus();
      input.setSelectionRange(index, index);
      highlightActiveLine();
      notifyCursor();
      scrollCaretIntoView();
    },

    /** What the host asks for when it wants to know where things stand. */
    stats: function () {
      var lines = documentLines();
      var longest = 0;
      for (var i = 0; i < lines.length; i += 1) {
        if (lines[i].length > longest) {
          longest = lines[i].length;
        }
      }
      return JSON.stringify({
        lines: lines.length,
        characters: input.value.length,
        longest: longest,
        wrapping: wrapping,
      });
    }
  };

  measure();
  render(true);

  // The monospace face may not be the one the first measurement saw: a font
  // that swaps in afterwards changes how wide a character is, and every width
  // in the editor is computed from that.
  if (document.fonts && document.fonts.ready && document.fonts.ready.then) {
    document.fonts.ready.then(function () {
      measure();
      lastWidth = -1;
      lastHeight = -1;
      gutterSignature = '';
      render(true);
    });
  }

  if (global.PyBridge && global.PyBridge.onEditorReady) {
    global.PyBridge.onEditorReady();
  }
})(window);
