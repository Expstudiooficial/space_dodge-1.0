/**
 * Host-side tests for the app's browser-side modules.
 *
 * The console renderer, the ANSI parser and the Python highlighter all run
 * inside a WebView on the device; here they run under Node against a stub
 * document, which is enough to cover their logic.
 *
 *     node tools/test_js.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const WEB = path.join(__dirname, '..', 'app', 'src', 'main', 'assets', 'web');

const failures = [];

function check(name, condition, detail) {
  if (condition) {
    console.log('  PASS  ' + name);
  } else {
    console.log('  FAIL  ' + name + '  ' + (detail === undefined ? '' : JSON.stringify(detail)));
    failures.push(name);
  }
}

// A window object is all these files need; neither touches the DOM at load time
// except console.js, which is tested separately with a stub document.
const sandbox = { window: {}, console: console };
sandbox.window.window = sandbox.window;
vm.createContext(sandbox);

for (const file of ['ansi.js', 'highlight.js']) {
  vm.runInContext(fs.readFileSync(path.join(WEB, file), 'utf8'), sandbox, { filename: file });
}

const Ansi = sandbox.window.Ansi;
const PyHighlight = sandbox.window.PyHighlight;
const ESC = '\u001b';

console.log('\n== ansi: escaping ==');
check('html is escaped', Ansi.toHtml('<script>&"', Ansi.newState()) === '&lt;script&gt;&amp;&quot;');
check('plain text passes through', Ansi.toHtml('hello world', Ansi.newState()) === 'hello world');

console.log('\n== ansi: colour ==');
let out = Ansi.toHtml(ESC + '[31mred' + ESC + '[0m plain', Ansi.newState());
check('red opens a span', out.indexOf('<span class="fg1">red</span>') === 0, out);
check('reset closes the colour', out.endsWith(' plain'), out);

out = Ansi.toHtml(ESC + '[1;32mbold green' + ESC + '[0m', Ansi.newState());
check('bold and colour combine', /class="b fg2"/.test(out), out);

out = Ansi.toHtml(ESC + '[91mbright' + ESC + '[0m', Ansi.newState());
check('bright colours map to 8-15', /class="fg9"/.test(out), out);

out = Ansi.toHtml(ESC + '[38;5;196mindexed' + ESC + '[0m', Ansi.newState());
check('256-colour is mapped', /class="fg9"/.test(out), out);

out = Ansi.toHtml(ESC + '[38;2;255;0;0mtruecolour' + ESC + '[0m', Ansi.newState());
check('truecolour is mapped', /class="fg9"/.test(out), out);

console.log('\n== ansi: state across chunks ==');
const shared = Ansi.newState();
const first = Ansi.toHtml(ESC + '[34mblue start', shared);
const second = Ansi.toHtml(' still blue' + ESC + '[0m done', shared);
check('colour opens in the first chunk', /fg4/.test(first), first);
check('colour continues into the second', /fg4/.test(second), second);
check('reset applies mid-chunk', second.endsWith('</span> done'), second);

console.log('\n== ansi: sequences that are not colour ==');
out = Ansi.toHtml(ESC + '[2J' + ESC + '[H' + 'text', Ansi.newState());
check('clear-screen and home are dropped', out === 'text', out);
out = Ansi.toHtml(ESC + ']0;window title' + '\u0007' + 'after', Ansi.newState());
check('OSC title is dropped', out === 'after', out);
out = Ansi.toHtml('progress\rdone', Ansi.newState());
check('bare carriage return is dropped', out === 'progressdone', out);
out = Ansi.toHtml('line1\nline2', Ansi.newState());
check('newlines survive', out === 'line1\nline2', out);
check('empty input is empty output', Ansi.toHtml('', Ansi.newState()) === '');

console.log('\n== ansi: a real rich-style line ==');
out = Ansi.toHtml(ESC + '[1;36m|' + ESC + '[0m name ' + ESC + '[1;36m|' + ESC + '[0m', Ansi.newState());
check('table borders render', (out.match(/fg6/g) || []).length === 2, out);
check('no escape bytes leak through', out.indexOf(ESC) === -1, out);

console.log('\n== highlight: keywords ==');
let html = PyHighlight.highlight('def greet(name):\n    return name');
check('def is a keyword', /<span class="tok-kw">def<\/span>/.test(html), html);
check('function name is a definition', /<span class="tok-def">greet<\/span>/.test(html), html);
check('return is a keyword', /<span class="tok-kw">return<\/span>/.test(html), html);

html = PyHighlight.highlight('class Robot:\n    pass');
check('class name is a definition', /<span class="tok-def">Robot<\/span>/.test(html), html);

console.log('\n== highlight: strings and comments ==');
html = PyHighlight.highlight('x = "hello # not a comment"');
check('string is one token', /<span class="tok-str">"hello # not a comment"<\/span>/.test(html), html);
check('hash inside a string is not a comment', !/tok-comment/.test(html), html);

html = PyHighlight.highlight('# def is not a keyword here\nx = 1');
check('comment is highlighted', /<span class="tok-comment"># def is not a keyword here<\/span>/.test(html), html);
check('keyword inside a comment is inert', !/tok-kw/.test(html), html);

html = PyHighlight.highlight('s = """triple\nline"""');
check('triple-quoted strings span lines', /tok-str">"""triple\nline"""/.test(html), html);

html = PyHighlight.highlight('f = f"value: {x}"');
check('f-string prefix is part of the string', /tok-str">f"value: \{x\}"/.test(html), html);

html = PyHighlight.highlight("t = 'single \\' escaped'");
check('escaped quote does not end the string', (html.match(/tok-str/g) || []).length === 1, html);

console.log('\n== highlight: numbers, builtins, decorators ==');
html = PyHighlight.highlight('n = 42\nf = 3.14\nh = 0xFF\nc = 1e10');
check('integers are numbers', /tok-num">42/.test(html), html);
check('floats are numbers', /tok-num">3.14/.test(html), html);
check('hex is a number', /tok-num">0xFF/.test(html), html);
check('exponents are numbers', /tok-num">1e10/.test(html), html);

html = PyHighlight.highlight('print(len(items))');
check('print is a builtin', /tok-builtin">print/.test(html), html);
check('len is a builtin', /tok-builtin">len/.test(html), html);

html = PyHighlight.highlight('@property\ndef value(self):\n    return self._v');
check('decorator is highlighted', /tok-decorator">@property/.test(html), html);
check('self is highlighted', /tok-self">self/.test(html), html);

html = PyHighlight.highlight('x = True\ny = None');
check('True is a constant', /tok-num">True/.test(html), html);
check('None is a constant', /tok-num">None/.test(html), html);

console.log('\n== highlight: safety ==');
html = PyHighlight.highlight('x = "<script>alert(1)</script>"');
check('markup inside a string is escaped', html.indexOf('<script>') === -1, html);
html = PyHighlight.highlight('# <img src=x onerror=alert(1)>');
check('markup inside a comment is escaped', html.indexOf('<img') === -1, html);
html = PyHighlight.highlight('a < b and c > d');
check('comparisons are escaped', html.indexOf('&lt;') !== -1 && html.indexOf('&gt;') !== -1, html);

console.log('\n== highlight: round trip ==');
const samples = [
  'x = 1',
  '',
  'def f():\n    """doc"""\n    return {"a": [1, 2, 3]}',
  'if a and b or not c:\n    pass  # trailing',
  "print(f'{x!r:>10}')",
];
function stripTags(value) {
  return value
    .replace(/<[^>]*>/g, '')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}
samples.forEach(function (source, index) {
  check('sample ' + index + ' survives highlighting unchanged', stripTags(PyHighlight.highlight(source)) === source, {
    source: source,
    got: stripTags(PyHighlight.highlight(source)),
  });
});

console.log('\n== console.js against a stub DOM ==');
const nodes = {};
function makeElement(id) {
  const element = {
    id: id,
    childNodes: [],
    _text: '',
    get textContent() { return this._text; },
    set textContent(value) {
      this._text = value;
      if (value === '') {
        this.childNodes = [];
        this.firstChild = undefined;
      }
    },
    style: {},
    classList: {
      values: {},
      add: function (n) { this.values[n] = true; },
      remove: function (n) { delete this.values[n]; },
      toggle: function (n, on) { if (on) this.values[n] = true; else delete this.values[n]; },
      contains: function (n) { return !!this.values[n]; },
    },
    scrollTop: 0,
    scrollHeight: 1000,
    clientHeight: 500,
    addEventListener: function () {},
    appendChild: function (child) {
      this.childNodes.push(child);
      this._text += child.textContent;
      this.firstChild = this.childNodes[0];
    },
    removeChild: function (child) {
      const at = this.childNodes.indexOf(child);
      if (at >= 0) this.childNodes.splice(at, 1);
      this.firstChild = this.childNodes[0];
    },
    set innerHTML(value) {
      this._html = value;
      // The stub only needs the text the browser would have rendered.
      this._text = value.replace(/<[^>]*>/g, '')
        .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
        .replace(/&amp;/g, '&');
    },
    get innerHTML() {
      return this._html || '';
    },
  };
  nodes[id] = element;
  return element;
}
['scroller', 'output', 'empty', 'tail'].forEach(makeElement);

const frames = [];
const consoleSandbox = {
  window: {
    Ansi: Ansi,
    requestAnimationFrame: function (fn) { frames.push(fn); },
  },
  document: {
    getElementById: function (id) { return nodes[id]; },
    createElement: function () { return makeElement('tmp' + Math.random()); },
  },
  console: console,
};
consoleSandbox.window.window = consoleSandbox.window;
vm.createContext(consoleSandbox);
vm.runInContext(
  fs.readFileSync(path.join(WEB, 'console.js'), 'utf8'),
  consoleSandbox,
  { filename: 'console.js' }
);

const PyConsole = consoleSandbox.window.PyConsole;
check('PyConsole is exported', typeof PyConsole === 'object');

PyConsole.append('stdout', 'first\n');
PyConsole.append('stderr', 'oops\n');
check('writes are batched, not immediate', nodes.output.childNodes.length === 0, nodes.output.childNodes.length);
check('one frame was requested for two writes', frames.length === 1, frames.length);
frames.shift()();
check('flush appends to the DOM', nodes.output.childNodes.length === 1, nodes.output.childNodes.length);
check('stdout text is present', nodes.output.textContent.indexOf('first') !== -1, nodes.output.textContent);
check('stderr text is present', nodes.output.textContent.indexOf('oops') !== -1, nodes.output.textContent);
check('stderr is class-tagged', nodes.output.childNodes[0].innerHTML.indexOf('class="stderr"') !== -1);
check('empty placeholder is hidden', nodes.empty.classList.contains('hidden'));
check('view scrolled to the bottom', nodes.scroller.scrollTop === nodes.scroller.scrollHeight);

PyConsole.append('stdout', '');
check('empty writes are ignored', frames.length === 0, frames.length);

PyConsole.clear();
check('clear empties the output', nodes.output.textContent === '', nodes.output.textContent);
check('clear restores the placeholder', !nodes.empty.classList.contains('hidden'));

PyConsole.append('system', '<b>note</b>\n');
frames.shift()();
check('system text is escaped, not parsed',
  nodes.output.childNodes[0].innerHTML.indexOf('&lt;b&gt;') !== -1,
  nodes.output.childNodes[0].innerHTML);

PyConsole.clear();
PyConsole.append('stdout', ESC + '[32mgreen\n');
frames.shift()();
check('ansi is applied to stdout',
  nodes.output.childNodes[0].innerHTML.indexOf('fg2') !== -1,
  nodes.output.childNodes[0].innerHTML);

PyConsole.setWrap(false);
check('wrap toggles the class', nodes.output.classList.contains('nowrap'));
PyConsole.setWrap(true);
check('wrap toggles back', !nodes.output.classList.contains('nowrap'));

console.log('\n== console.js: buffer cap ==');
PyConsole.clear();
const big = 'x'.repeat(100000);
for (let i = 0; i < 8; i += 1) {
  PyConsole.append('stdout', big);
  while (frames.length) frames.shift()();
}
check('old blocks are dropped past the cap', nodes.output.childNodes.length < 8, nodes.output.childNodes.length);
check('at least one block is kept', nodes.output.childNodes.length >= 1, nodes.output.childNodes.length);

console.log('');
if (failures.length) {
  console.log(failures.length + ' FAILURE(S): ' + failures.join(', '));
  process.exit(1);
}
console.log('all checks passed');
