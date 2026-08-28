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
function makeSandbox(options) {
  const counters = { highlight: 0, paints: 0, gutterRebuilds: 0, gutterAppends: 0, sent: [] };
  // Shared with the stub nodes so a check can put the page back on screen.
  const sandboxRef = { hidden: !!(options && options.hidden) };

  function element(id) {
    return {
      id: id,
      value: '',
      // A stand-in for CSS: the editor writes width/height here and the
      // checks read them back, which is the whole point - the sizing is
      // arithmetic now, so it can be checked without a browser.
      style: {},
      _html: '',
      _attributes: {},
      textContent: '',
      selectionStart: 0,
      selectionEnd: 0,
      dataset: {},
      classList: {
        _on: new Set(),
        add(name) { this._on.add(name); },
        remove(name) { this._on.delete(name); },
        toggle(name, force) {
          const on = force === undefined ? !this._on.has(name) : force;
          if (on) this._on.add(name); else this._on.delete(name);
        },
        contains(name) { return this._on.has(name); },
      },
      setAttribute(name, value) { this._attributes[name] = value; },
      getAttribute(name) { return this._attributes[name]; },
      // 8px per character, 21px per line: the numbers the ruler would give.
      getBoundingClientRect() {
        const per = sandboxRef.hidden ? 0 : 8;
        return { width: (this.textContent || '').length * per, height: 21 };
      },
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
      addEventListener(name, handler) {
        this._listeners = this._listeners || {};
        (this._listeners[name] = this._listeners[name] || []).push(handler);
      },
      dispatch(name, event) {
        (this._listeners?.[name] || []).forEach((handler) => handler(event || {}));
      },
      setSelectionRange(start, end) {
        this.selectionStart = start;
        this.selectionEnd = end === undefined ? start : end;
      },
      querySelector() { return null; },
      focus() {},
      get scrollHeight() { return 100; },
      get scrollWidth() { return 100; },
      // A narrow screen: 320px, of which 292 is usable once the padding is
      // taken off. That is what makes a long line have somewhere to go.
      // `hidden` stands in for a WebView that has not been laid out yet.
      get clientWidth() { return sandboxRef.hidden ? 0 : 320; },
      get clientHeight() { return 400; },
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
    getComputedStyle() {
      return {
        lineHeight: '21px',
        paddingLeft: '12px',
        paddingRight: '16px',
        paddingTop: '10px',
        paddingBottom: '60px',
      };
    },
    addEventListener() {},
    requestAnimationFrame(fn) { fn(); },
    PyBridge: {
      onEditorChanged(text) { counters.sent.push(text.length); },
      onCursorMoved() {},
      onEditorReady() {},
    },
  };
  sandbox.startComposition = () => sandbox.document.getElementById('input').dispatch('compositionstart');
  sandbox.endComposition = () => sandbox.document.getElementById('input').dispatch('compositionend');
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
  return { sandbox, counters, nodes, sandboxRef };
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

console.log('\n== a long line has somewhere to go ==');
{
  const { sandbox, nodes } = makeSandbox();
  const longLine = 'x'.repeat(400);
  sandbox.PyEditor.setContent(longLine);

  // 400 characters at 8px, plus two of slack and the padding.
  const expected = Math.ceil(402 * 8) + 12 + 16;
  check('the textarea is as wide as the line needs',
        nodes.input.style.width === expected + 'px',
        nodes.input.style.width + ' vs ' + expected + 'px');
  check('which is far wider than the screen', expected > 320 * 9, expected);

  // The bug it replaces: a width taken from the layer under it, which stops
  // growing at the width of its container.
  check('and not the width of the container',
        nodes.input.style.width !== '320px', nodes.input.style.width);

  sandbox.PyEditor.setContent('x'.repeat(4000));
  const wider = parseInt(nodes.input.style.width, 10);
  check('ten times the line, ten times the width', wider > 32000, wider);

  sandbox.PyEditor.setContent('short');
  check('a short document is only as wide as the screen',
        nodes.input.style.width === '320px', nodes.input.style.width);
}

console.log('\n== an editor built before it is on screen ==');
{
  // The editor's WebView is created before its tab is ever shown, so the
  // first measurement lands on a page with no width. Every character was then
  // assumed to be eight pixels wide for the rest of the session.
  const { sandbox, nodes, sandboxRef } = makeSandbox({ hidden: true });
  sandbox.PyEditor.setContent('q'.repeat(300));
  const guessed = nodes.input.style.width;

  sandboxRef.hidden = false;
  nodes.input.value = 'q'.repeat(300) + 'r';
  sandbox.PyEditor.insert('');

  const real = parseInt(nodes.input.style.width, 10);
  check('it measures again once it can', real > 0, nodes.input.style.width);
  check('and the width is the real one',
        real === Math.ceil(303 * 8) + 12 + 16, real);
  check('rather than what it guessed in the dark',
        nodes.input.style.width !== guessed, guessed);
}

console.log('\n== the height is counted, not measured ==');
{
  const { sandbox, nodes } = makeSandbox();
  sandbox.PyEditor.setContent('a\nb\nc\n');
  // Four lines (the trailing newline makes an empty fourth), 21px each,
  // plus 10 top and 60 bottom of padding.
  check('height follows the line count',
        nodes.input.style.height === (4 * 21 + 70) + 'px', nodes.input.style.height);
  check('and the layout is never asked for it',
        nodes.input.style.height !== '100px', nodes.input.style.height);
}

console.log('\n== wrapping ==');
{
  const { sandbox, nodes } = makeSandbox();
  const longLine = 'y'.repeat(1000);
  sandbox.PyEditor.setContent(longLine + '\nshort');
  const wide = nodes.input.style.width;

  sandbox.PyEditor.setWrap(true);
  check('the frame is marked as wrapping', nodes.frame.classList.contains('wrap'));
  check('the textarea stops being told a width', nodes.input.style.width === '', nodes.input.style.width);
  check('and the element agrees', nodes.input.getAttribute('wrap') === 'soft');

  // 292px usable / 8px = 36 columns. 1000 characters is 28 rows, plus one
  // for the short line.
  const rows = Math.ceil(1000 / 36) + 1;
  check('the height covers every wrapped row',
        nodes.input.style.height === (rows * 21 + 70) + 'px',
        nodes.input.style.height + ' vs ' + (rows * 21 + 70));

  const numbers = nodes['gutter-inner'].innerHTML.match(/class="num"/g) || [];
  check('there is still one number per real line', numbers.length === 2, numbers.length);
  check('and the long one is given the height it now takes',
        nodes['gutter-inner'].innerHTML.includes('height:' + (Math.ceil(1000 / 36) * 21) + 'px'),
        nodes['gutter-inner'].innerHTML.slice(0, 200));

  sandbox.PyEditor.setWrap(false);
  check('turning it off restores the width', nodes.input.style.width === wide,
        nodes.input.style.width + ' vs ' + wide);
  check('and the attribute', nodes.input.getAttribute('wrap') === 'off');
}

console.log('\n== the gutter keeps up with a wrapped line ==');
{
  const { sandbox, counters, nodes } = makeSandbox();
  sandbox.PyEditor.setContent('z'.repeat(700) + '\ntail');
  sandbox.PyEditor.setWrap(true);

  const heightOf = () => {
    const match = nodes['gutter-inner'].innerHTML.match(/height:(\d+)px/);
    return match ? Number(match[1]) : 0;
  };
  const before = heightOf();
  check('the long line is given several rows', before > 21 * 10, before);

  // Growing an existing line does not change the line count - which is what
  // the first version keyed on, so the numbers drifted.
  counters.gutterRebuilds = 0;
  nodes.input.value = 'z'.repeat(900) + '\ntail';
  nodes.input.setSelectionRange(900);
  sandbox.PyEditor.insert('');
  check('a line that grows redraws the gutter', counters.gutterRebuilds > 0,
        counters.gutterRebuilds);
  check('and its number grows with it', heightOf() > before, heightOf() + ' vs ' + before);
}

console.log('\n== the keyboard is left alone mid-word ==');
{
  const { sandbox, counters, nodes } = makeSandbox();
  sandbox.PyEditor.setContent('print(');
  counters.paints = 0;
  counters.highlight = 0;

  nodes.input._listeners = nodes.input._listeners || {};
  sandbox.startComposition();
  nodes.input.value = 'print(hel';
  sandbox.PyEditor.insert('');
  check('nothing is repainted while composing', counters.paints === 0, counters.paints);

  sandbox.endComposition();
  check('and it catches up when the word is finished', counters.paints > 0, counters.paints);
}

console.log('\n== the language decides how it indents ==');
{
  const { sandbox, nodes } = makeSandbox();

  // A stand-in for what a key press does: the editor's Enter handler reads
  // the line it is on and inserts the next one's indentation.
  const pressEnter = () => {
    const event = { key: 'Enter', preventDefault() {} };
    nodes.input.dispatch('keydown', event);
    return nodes.input.value;
  };

  sandbox.PyEditor.setLanguage('python');
  sandbox.PyEditor.setContent('def f():');
  nodes.input.setSelectionRange(8);
  check('python indents after a colon', pressEnter() === 'def f():\n    ',
        JSON.stringify(pressEnter()));

  sandbox.PyEditor.setContent('    return 1');
  nodes.input.setSelectionRange(12);
  check('and steps back out after return', pressEnter() === '    return 1\n',
        JSON.stringify(nodes.input.value));

  sandbox.PyEditor.setLanguage('go');
  sandbox.PyEditor.setContent('func main() {');
  nodes.input.setSelectionRange(13);
  check('go indents after a brace', pressEnter() === 'func main() {\n    ',
        JSON.stringify(nodes.input.value));

  sandbox.PyEditor.setContent('    return 1');
  nodes.input.setSelectionRange(12);
  check('and does not treat return as a dedent',
        nodes.input.value === '    return 1' && pressEnter() === '    return 1\n    ',
        JSON.stringify(nodes.input.value));

  sandbox.PyEditor.setContent('    ');
  nodes.input.setSelectionRange(4);
  nodes.input.dispatch('keydown', { key: '}', preventDefault() {} });
  check('a closing brace steps back out', nodes.input.value === '}',
        JSON.stringify(nodes.input.value));
}

console.log('\n== jumping to a line ==');
{
  const { sandbox, nodes } = makeSandbox();
  sandbox.PyEditor.setContent('one\ntwo\nthree\nfour');
  sandbox.PyEditor.goToLine(3);
  check('the caret lands at the start of it', nodes.input.selectionStart === 8,
        nodes.input.selectionStart);
  sandbox.PyEditor.goToLine(99);
  check('past the end is the last line', nodes.input.selectionStart === 14,
        nodes.input.selectionStart);
  sandbox.PyEditor.goToLine(0);
  check('before the start is the first', nodes.input.selectionStart === 0,
        nodes.input.selectionStart);
}

console.log('\n== what the host can ask ==');
{
  const { sandbox } = makeSandbox();
  sandbox.PyEditor.setContent('a\n' + 'b'.repeat(120));
  const stats = JSON.parse(sandbox.PyEditor.stats());
  check('lines are counted', stats.lines === 2, stats);
  check('the longest line is known', stats.longest === 120, stats);
  check('and the characters', stats.characters === 122, stats);
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
