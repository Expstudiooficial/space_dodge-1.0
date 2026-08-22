/**
 * Console renderer.
 *
 * Kotlin pushes output through `PyConsole.append(...)`. Writes are batched into
 * an animation frame because a chatty script can emit hundreds of chunks per
 * second, and touching the DOM on every one of them makes scrolling stutter.
 */
(function (global) {
  'use strict';

  var MAX_CHARS = 400000; // Roughly 5k lines; beyond this the WebView gets slow.
  var BOTTOM_SLACK = 48; // px from the bottom that still counts as "at the bottom".

  var scroller = document.getElementById('scroller');
  var output = document.getElementById('output');
  var empty = document.getElementById('empty');

  var ansiState = global.Ansi.newState();
  var pending = [];
  var frameRequested = false;
  var charCount = 0;
  var stickToBottom = true;
  var hasContent = false;

  scroller.addEventListener('scroll', function () {
    var distance = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
    stickToBottom = distance <= BOTTOM_SLACK;
  }, { passive: true });

  function classForStream(stream) {
    switch (stream) {
      case 'stderr':
        return 'stderr';
      case 'system':
        return 'system';
      case 'input':
        return 'input-echo';
      default:
        return '';
    }
  }

  function flush() {
    frameRequested = false;
    if (!pending.length) {
      return;
    }

    var batch = pending;
    pending = [];

    var html = '';
    for (var i = 0; i < batch.length; i += 1) {
      var item = batch[i];
      var className = classForStream(item.stream);
      var body;
      if (item.stream === 'stdout' || item.stream === 'stderr') {
        body = global.Ansi.toHtml(item.text, ansiState);
      } else {
        // System notes and echoed input are ours, so they are never ANSI.
        body = global.Ansi.escapeHtml(item.text);
      }
      html += className
        ? '<span class="' + className + '">' + body + '</span>'
        : '<span>' + body + '</span>';
      charCount += item.text.length;
    }

    var holder = document.createElement('span');
    holder.innerHTML = html;
    output.appendChild(holder);

    trim();

    if (!hasContent) {
      hasContent = true;
      empty.classList.add('hidden');
    }

    if (stickToBottom) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  }

  /** Drops the oldest blocks once the buffer grows past the cap. */
  function trim() {
    while (charCount > MAX_CHARS && output.childNodes.length > 1) {
      var first = output.firstChild;
      charCount -= (first.textContent || '').length;
      output.removeChild(first);
    }
    if (charCount < 0) {
      charCount = 0;
    }
  }

  global.PyConsole = {
    append: function (stream, text) {
      if (!text) {
        return;
      }
      pending.push({ stream: stream, text: text });
      if (!frameRequested) {
        frameRequested = true;
        global.requestAnimationFrame(flush);
      }
    },

    clear: function () {
      pending = [];
      output.textContent = '';
      charCount = 0;
      ansiState = global.Ansi.newState();
      stickToBottom = true;
      hasContent = false;
      empty.classList.remove('hidden');
    },

    /** Long lines either wrap or scroll sideways; the console offers both. */
    setWrap: function (wrap) {
      output.classList.toggle('nowrap', !wrap);
    }
  };

  // The host injects any output produced before this script finished loading.
  if (global.PyConsoleQueue && global.PyConsoleQueue.length) {
    for (var i = 0; i < global.PyConsoleQueue.length; i += 1) {
      var queued = global.PyConsoleQueue[i];
      global.PyConsole.append(queued.stream, queued.text);
    }
    global.PyConsoleQueue = [];
  }
})(window);
