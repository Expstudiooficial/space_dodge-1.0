/**
 * Checks the editor's rendering rules without a browser.
 *
 * The DOM here is a stub that counts the expensive things - how often the
 * highlighter runs, how often the layer under the textarea is rewritten - so
 * that a change which makes typing slow again fails a check rather than being
 * noticed on a phone three weeks later.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');
const WEB = path.join(ROOT, 'app', 'src', 'main', 'assets', 'web');

let failures = 0;
function check(name, condition, detail) {
  if (condition) {
    console.log('  PASS  ' + name);
  } else {
    failures += 1;
    console.log('  FAIL  ' + name + '  ' + (detail === undefined ? '' : detail));
  }
}

/** A DOM just real enough for editor.js, and instrumented. */
function makeSandbox() {
  const counters = { highlight: 0, paints: 0, gutterRebuilds: 0, gutterAppends: 0, sent: [] };

  function element(id) {
    return {
      id: id,
      value: '',
      style: {},
      _html: '',
      selectionStart: 0,
      selectionEnd: 0,
      dataset: {},
      classList: { add() {}, remove() {}, toggle() {} },
      set innerHTML(value) {
        this._html = value;
        if (this.id === 'highlight-code') counters.paints += 1;
        if (this.id === 'gutter-inner') counters.gutterRebuilds += 1;
      },
      get innerHTML() { return this._html; },
      insertAdjacentHTML(where, html) {
        this._html += html;
        if (this.id === 'gutter-inner') counters.gutterAppends += 1;
      },
      addEventListener() {},
      setSelectionRange(start, end) {
        this.selectionStart = start;
        this.selectionEnd = end === undefined ? start : end;
      },
      querySelector() { return null; },
      focus() {},
      get scrollHeight() { return 100; },
      get scrollWidth() { return 100; },
      get clientWidth() { return 100; },
      scrollTop: 0,
      scrollLeft: 0,
    };
  }

  const nodes = {};
  const sandbox = {
    console,
    counters,
    timers: [],
    document: {
      getElementById(id) {
        if (!nodes[id]) nodes[id] = element(id);
        return nodes[id];
      },
      execCommand() { return false; },
    },
    setTimeout(fn, ms) { sandbox.timers.push(fn); return sandbox.timers.length; },
    clearTimeout(handle) { if (handle) sandbox.timers[handle - 1] = null; },
    addEventListener() {},
    requestAnimationFrame(fn) { fn(); },
    PyBridge: {
      onEditorChanged(text) { counters.sent.push(text.length); },
      onCursorMoved() {},
      onEditorReady() {},
    },
  };
  sandbox.window = sandbox;
  sandbox.global = sandbox;
  vm.createContext(sandbox);

  vm.runInContext(fs.readFileSync(path.join(WEB, 'highlight.js'), 'utf8'), sandbox);
  const realHighlight = sandbox.PyHighlight.highlight;
  sandbox.PyHighlight.highlight = function (source) {
    counters.highlight += 1;
    return realHighlight(source);
  };
  vm.runInContext(fs.readFileSync(path.join(WEB, 'editor.js'), 'utf8'), sandbox);
  return { sandbox, counters, nodes };
}

/** Types text into the stub the way the browser would, one input event each. */
function type(sandbox, nodes, text) {
  const input = nodes.input;
  for (const char of text) {
    input.value += char;
    input.setSelectionRange(input.value.length);
    sandbox.PyEditor.insert('');   // reaches onInput() without touching value
  }
}

function runTimers(sandbox) {
  const pending = sandbox.timers.slice();
  sandbox.timers.length = 0;
  pending.forEach((fn) => { if (fn) fn(); });
}

const big = ('def f(x):\n    return x * 2\n\n').repeat(500); // ~14 KB

console.log('\n== a big document is painted before it is coloured ==');
{
  const { sandbox, counters, nodes } = makeSandbox();
  counters.highlight = 0;   // the module paints once as it loads
  sandbox.PyEditor.setContent(big);
  check('loading a document colours it once', counters.highlight === 1, counters.highlight);

  counters.paints = 0;
  counters.highlight = 0;
  nodes.input.value = big + 'x';
  nodes.input.setSelectionRange(nodes.input.value.length);
  sandbox.PyEditor.insert('');
  check('a keystroke repaints the text at once', counters.paints >= 1, counters.paints);
  check('but does not tokenise it yet', counters.highlight === 0, counters.highlight);

  runTimers(sandbox);
  check('the pause afterwards does', counters.highlight === 1, counters.highlight);
}

console.log('\n== a small document is coloured on the spot ==');
{
  const { sandbox, counters, nodes } = makeSandbox();
  sandbox.PyEditor.setContent('print(1)\n');
  counters.highlight = 0;
  nodes.input.value = 'print(12)\n';
  nodes.input.setSelectionRange(9);
  sandbox.PyEditor.insert('');
  check('no delay is introduced', counters.highlight === 1, counters.highlight);
  check('and nothing is left pending', sandbox.timers.filter(Boolean).length <= 1);
}

console.log('\n== the gutter grows rather than being rebuilt ==');
{
  const { sandbox, counters, nodes } = makeSandbox();
  sandbox.PyEditor.setContent('a\nb\nc\n');
  counters.gutterRebuilds = 0;
  counters.gutterAppends = 0;
  nodes.input.value = 'a\nb\nc\nd\n';
  nodes.input.setSelectionRange(nodes.input.value.length);
  sandbox.PyEditor.insert('');
  check('adding a line appends one number', counters.gutterAppends === 1, counters.gutterAppends);
  check('and does not redraw the rest', counters.gutterRebuilds === 0, counters.gutterRebuilds);
}

console.log('\n== the host is not told what it already knows ==');
{
  const { sandbox, counters, nodes } = makeSandbox();
  sandbox.PyEditor.setContent(big);
  runTimers(sandbox);
  counters.sent.length = 0;

  // A caret move, then a sync: nothing changed, so nothing should cross.
  nodes.input.setSelectionRange(10);
  sandbox.PyEditor.insert('');
  runTimers(sandbox);
  check('an unchanged document is not sent', counters.sent.length === 0, counters.sent);

  nodes.input.value = big + 'y';
  sandbox.PyEditor.insert('');
  runTimers(sandbox);
  check('a changed one is', counters.sent.length === 1, counters.sent);
}

console.log('\n== counting lines ==');
{
  const { sandbox, nodes } = makeSandbox();
  sandbox.PyEditor.setContent('one\ntwo\nthree');
  check('every line is numbered', (nodes['gutter-inner'].innerHTML.match(/class="num"/g) || []).length === 3);
  sandbox.PyEditor.setContent('');
  check('an empty document still has line 1',
        (nodes['gutter-inner'].innerHTML.match(/class="num"/g) || []).length === 1);
}

console.log();
if (failures) {
  console.log(failures + ' editor checks failed');
  process.exit(1);
}
console.log('all editor checks passed');
