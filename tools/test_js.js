/*
 * Checks the JavaScript runtime the app loads into its WebView.
 *
 * The WebView is not available here, so this stands in for it: a V8 context
 * with the same bridge Kotlin exposes, the same globals a browser provides,
 * and the same call sequence. What it cannot prove is that Android's WebView
 * behaves like node's V8 - but the runtime file itself, which is where the
 * logic lives, is exercised exactly as it is on the device.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const RUNTIME = path.join(__dirname, '..', 'app', 'src', 'main', 'assets', 'web', 'jsruntime.js');
const source = fs.readFileSync(RUNTIME, 'utf8');

// One process-wide hook, pointed at whichever case is running: node warns
// about a listener per case, and the warning would drown the results.
let rejectionSink = () => {};
process.on('unhandledRejection', (reason) => rejectionSink(reason));

function runCase(code, inputs) {
  return new Promise((resolve, reject) => {
    const out = [];
    const err = [];
    const queue = (inputs || []).slice();
    const listeners = {};
    let nextTimerId = 1;
    const handles = new Map();

    const context = vm.createContext({});
    vm.runInContext('globalThis.window = globalThis;', context);

    // Browser-shaped timers: numeric ids, which is what the runtime keys on.
    context.setTimeout = (fn, ms, ...rest) => {
      const id = nextTimerId++;
      handles.set(id, setTimeout(() => { handles.delete(id); fn(...rest); }, ms || 0));
      return id;
    };
    context.clearTimeout = (id) => {
      if (handles.has(id)) { clearTimeout(handles.get(id)); handles.delete(id); }
    };
    context.setInterval = (fn, ms, ...rest) => {
      const id = nextTimerId++;
      handles.set(id, setInterval(() => fn(...rest), ms || 0));
      return id;
    };
    context.clearInterval = (id) => {
      if (handles.has(id)) { clearInterval(handles.get(id)); handles.delete(id); }
    };
    context.addEventListener = (name, fn) => { (listeners[name] = listeners[name] || []).push(fn); };
    context.queueMicrotask = queueMicrotask;

    context.__pycmd = {
      ready() {},
      write(token, text) { out.push(text); },
      writeErr(token, text) { err.push(text); },
      readLine(token, id) {
        const line = queue.length ? queue.shift() : null;
        setTimeout(() => {
          vm.runInContext(
            `__pycmd_resolve(${id}, ${line !== null}, ${JSON.stringify(line)})`,
            context,
          );
        }, 0);
      },
      finish(token, status, exitCode, detail) {
        handles.forEach((handle) => { clearTimeout(handle); clearInterval(handle); });
        resolve({
          status,
          exit: Number(exitCode),
          out: out.join(''),
          err: err.join(''),
        });
      },
    };

    vm.runInContext(source, context);
    // Unhandled rejections inside the context surface through the listener the
    // runtime registers, exactly as they do in a WebView.
    rejectionSink = (reason) => {
      (listeners['unhandledrejection'] || [])
        .forEach((fn) => fn({ reason, preventDefault() {} }));
    };

    vm.runInContext(
      `__pycmd_run(${JSON.stringify(code)}, "test.js", "1")`,
      context,
    );
    setTimeout(() => reject(new Error('timed out')), 5000).unref();
  });
}

const cases = [];
function check(name, code, expected, options) {
  cases.push({ name, code, expected, options: options || {} });
}

// ------------------------------------------------------------------ basics

check('hello', 'console.log("hello")', 'hello\n');
check('arithmetic', 'console.log(2 + 3 * 4)', '14\n');
check('several arguments', 'console.log("a", 1, true)', 'a 1 true\n');
check('template literals', 'const n = 4; console.log(`n is ${n}`)', 'n is 4\n');
check('string is bare at the top level', 'console.log("a b")', 'a b\n');
check('string is quoted inside an array', 'console.log(["a b"])', "[ \"a b\" ]\n");
check('numbers', 'console.log(1.5, -0, 1e21)', '1.5 -0 1e+21\n');
check('null and undefined', 'console.log(null, undefined)', 'null undefined\n');
check('object', 'console.log({a: 1, b: "x"})', '{ a: 1, b: "x" }\n');
check('nested object', 'console.log({a: {b: [1, 2]}})', '{ a: { b: [ 1, 2 ] } }\n');
check('empty array and object', 'console.log([], {})', '[] {}\n');
check('map and set', 'console.log(new Map([["a", 1]]), new Set([1, 2]))',
      'Map(1) { "a" => 1 } Set(2) { 1, 2 }\n');
check('circular reference', 'const o = {}; o.self = o; console.log(o)', '{ self: [Circular] }\n');
check('function', 'function greet() {} console.log(greet)', '[Function: greet]\n');
check('print alias', 'print("via print")', 'via print\n');
check('process.stdout.write', 'process.stdout.write("no newline")', 'no newline');

// --------------------------------------------------------------- language

check('classes', `
class Counter {
  constructor() { this.n = 0; }
  bump() { this.n += 1; return this; }
}
console.log(new Counter().bump().bump().n);
`, '2\n');

check('destructuring and spread', `
const [a, ...rest] = [1, 2, 3];
const {x, y = 9} = {x: 5};
console.log(a, rest, x, y);
`, '1 [ 2, 3 ] 5 9\n');

check('array methods', `
const values = [5, 3, 8, 1];
console.log(values.filter(v => v > 2).sort((p, q) => p - q).map(v => v * 2).join(","));
`, '6,10,16\n');

check('regular expressions', `
const m = "2026-08-23".match(/(\\d{4})-(\\d{2})-(\\d{2})/);
console.log(m[1], m[2], m[3]);
`, '2026 08 23\n');

check('JSON round trip', `
const text = JSON.stringify({b: [1, 2], a: "x"});
console.log(text);
console.log(JSON.parse(text).b[1]);
`, '{"b":[1,2],"a":"x"}\n2\n');

check('generators', `
function* take() { yield 1; yield 2; yield 3; }
console.log([...take()]);
`, '[ 1, 2, 3 ]\n');

check('closures and recursion', `
const fib = n => (n < 2 ? n : fib(n - 1) + fib(n - 2));
console.log(fib(20));
`, '6765\n');

// ------------------------------------------------------------------ async

check('await a promise', `
const value = await Promise.resolve(41);
console.log(value + 1);
`, '42\n');

check('setTimeout still runs before the script ends', `
setTimeout(() => console.log("later"), 10);
console.log("first");
`, 'first\nlater\n');

check('sleep', `
console.log("before");
await sleep(5);
console.log("after");
`, 'before\nafter\n');

check('setInterval that clears itself', `
let n = 0;
const id = setInterval(() => {
  n += 1;
  console.log("tick", n);
  if (n === 3) clearInterval(id);
}, 1);
`, 'tick 1\ntick 2\ntick 3\n');

check('cleared timeout does not hang the run', `
const id = setTimeout(() => console.log("never"), 50);
clearTimeout(id);
console.log("done");
`, 'done\n');

check('promise chain', `
await new Promise(resolve => setTimeout(resolve, 5))
  .then(() => console.log("one"))
  .then(() => console.log("two"));
`, 'one\ntwo\n');

// ------------------------------------------------------------------ input

check('readLine', `
const name = await readLine("Name: ");
console.log("hello " + name);
`, 'Name: hello Ada\n', { inputs: ['Ada'] });

check('several reads', `
const a = Number(await input());
const b = Number(await input());
console.log(a + b);
`, '7\n', { inputs: ['3', '4'] });

check('read at the end of input', `
const line = await readLine();
console.log(line === null ? "no more input" : line);
`, 'no more input\n', { inputs: [] });

// ------------------------------------------------------------------ errors

check('thrown error', 'throw new Error("boom")', '', {
  status: 'error', errIncludes: 'Error: boom',
});
check('syntax error', 'const = 3', '', {
  status: 'error', errIncludes: 'SyntaxError',
});
check('reference error', 'console.log(nope)', '', {
  status: 'error', errIncludes: 'nope is not defined',
});
check('type error', 'null.field', '', {
  status: 'error', errIncludes: 'TypeError',
});
check('error inside a timer', `
setTimeout(() => { throw new Error("late failure"); }, 1);
console.log("scheduled");
`, 'scheduled\n', { status: 'error', errIncludes: 'late failure' });
check('rejected promise', `
await Promise.reject(new Error("rejected"));
`, '', { status: 'error', errIncludes: 'rejected' });
check('console.error goes to stderr', 'console.error("to stderr"); console.log("to stdout")',
      'to stdout\n', { errIncludes: 'to stderr' });
check('catching an error keeps the run clean', `
try { throw new Error("handled"); } catch (e) { console.log("caught " + e.message); }
`, 'caught handled\n');

// ------------------------------------------------------------------- exit

check('exit code', 'console.log("bye"); exit(3);', 'bye\n', { exit: 3 });
check('exit zero', 'exit()', '', { exit: 0 });
check('process.exit', 'process.exit(2)', '', { exit: 2 });

(async () => {
  let failures = 0;
  for (const item of cases) {
    let result;
    try {
      result = await runCase(item.code, item.options.inputs);
    } catch (error) {
      console.log(`FAIL ${item.name}: ${error.message}`);
      failures += 1;
      continue;
    }

    const wantStatus = item.options.status || 'ok';
    const problems = [];
    if (result.status !== wantStatus) {
      problems.push(`status ${JSON.stringify(result.status)}, wanted ${JSON.stringify(wantStatus)}`);
    }
    if (result.out !== item.expected) {
      problems.push(`stdout ${JSON.stringify(result.out)}, wanted ${JSON.stringify(item.expected)}`);
    }
    if (item.options.errIncludes && !result.err.includes(item.options.errIncludes)) {
      problems.push(`stderr ${JSON.stringify(result.err)} lacks ${JSON.stringify(item.options.errIncludes)}`);
    }
    if (!item.options.errIncludes && wantStatus === 'ok' && result.err.trim() !== '') {
      problems.push(`unexpected stderr ${JSON.stringify(result.err)}`);
    }
    if (item.options.exit !== undefined && result.exit !== item.options.exit) {
      problems.push(`exit ${result.exit}, wanted ${item.options.exit}`);
    }

    if (problems.length) {
      failures += 1;
      console.log(`FAIL ${item.name}`);
      problems.forEach((line) => console.log(`     ${line}`));
    } else {
      console.log(`ok   ${item.name}`);
    }
  }

  console.log(`\n${cases.length - failures}/${cases.length} checks passed`);
  process.exit(failures ? 1 : 0);
})();
