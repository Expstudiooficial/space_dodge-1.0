/*
 * The JavaScript side of running a .js file.
 *
 * There is no home-made interpreter here on purpose: the device already ships
 * a complete, fast, standards-compliant engine inside its WebView, and a
 * second-rate reimplementation would only be slower and wrong in corners.
 * This file turns that engine into something console-shaped - stdout, stderr,
 * blocking-looking input, and a run that ends when the work ends rather than
 * when the last statement does.
 *
 * Kotlin exposes `__pycmd`; everything below is what the user's code sees.
 */
(function () {
  'use strict';

  var bridge = window.__pycmd;
  var token = '';
  var settled = false;      // the top-level body has finished
  var finished = false;     // finish() has already been reported
  var failed = null;        // first error, kept so the exit status is honest
  var pending = 0;          // outstanding timers and intervals
  var intervals = {};       // ids we still count as pending
  var waiting = {};         // input requests keyed by id
  var nextInput = 1;
  var exiting = null;       // set by exit(); not an error

  // ----------------------------------------------------------------- output

  function write(text) {
    if (finished && !text) return;
    bridge.write(token, String(text));
  }

  function writeErr(text) {
    bridge.writeErr(token, String(text));
  }

  /**
   * Turns a value into something worth reading.
   *
   * Deliberately close to Node's console.log: strings print bare at the top
   * level but quoted inside a structure, so `console.log("a b")` and
   * `console.log(["a b"])` stay tellable apart.
   */
  function inspect(value, depth, seen) {
    depth = depth || 0;
    seen = seen || [];

    if (value === null) return 'null';
    var type = typeof value;
    if (type === 'undefined') return 'undefined';
    if (type === 'number') return Object.is(value, -0) ? '-0' : String(value);
    if (type === 'bigint') return String(value) + 'n';
    if (type === 'boolean') return String(value);
    if (type === 'symbol') return value.toString();
    if (type === 'string') return depth === 0 ? value : JSON.stringify(value);
    if (type === 'function') {
      return value.name ? '[Function: ' + value.name + ']' : '[Function (anonymous)]';
    }

    if (value instanceof Error) {
      return value.stack ? cleanStack(value.stack) : (value.name + ': ' + value.message);
    }
    if (value instanceof Date) return value.toISOString();
    if (value instanceof RegExp) return value.toString();

    if (seen.indexOf(value) !== -1) return '[Circular]';
    if (depth > 4) return Array.isArray(value) ? '[Array]' : '[Object]';
    seen = seen.concat([value]);

    if (Array.isArray(value)) {
      var items = value.map(function (item) { return inspect(item, depth + 1, seen); });
      var oneLine = '[ ' + items.join(', ') + ' ]';
      if (items.length === 0) return '[]';
      if (oneLine.length <= 72) return oneLine;
      return '[\n  ' + items.join(',\n  ') + '\n]';
    }

    if (value instanceof Map) {
      var pairs = [];
      value.forEach(function (v, k) {
        pairs.push(inspect(k, depth + 1, seen) + ' => ' + inspect(v, depth + 1, seen));
      });
      return 'Map(' + value.size + ') {' + (pairs.length ? ' ' + pairs.join(', ') + ' ' : '') + '}';
    }
    if (value instanceof Set) {
      var members = [];
      value.forEach(function (v) { members.push(inspect(v, depth + 1, seen)); });
      return 'Set(' + value.size + ') {' + (members.length ? ' ' + members.join(', ') + ' ' : '') + '}';
    }
    if (typeof value.then === 'function') return 'Promise { ... }';

    var keys = Object.keys(value);
    if (keys.length === 0) return '{}';
    var body = keys.map(function (key) {
      var label = /^[A-Za-z_$][\w$]*$/.test(key) ? key : JSON.stringify(key);
      return label + ': ' + inspect(value[key], depth + 1, seen);
    });
    var flat = '{ ' + body.join(', ') + ' }';
    if (flat.length <= 72) return flat;
    return '{\n  ' + body.join(',\n  ') + '\n}';
  }

  function joinArgs(args) {
    var parts = [];
    for (var i = 0; i < args.length; i++) parts.push(inspect(args[i], 0, []));
    return parts.join(' ');
  }

  /** Drops the frames that belong to this file rather than to the user. */
  function cleanStack(stack) {
    return String(stack)
      .split('\n')
      .filter(function (line) {
        return line.indexOf('jsruntime.js') === -1 &&
               line.indexOf('pycmd-internal') === -1 &&
               line.indexOf('at eval (eval') === -1;
      })
      .join('\n')
      .replace(/\s+$/, '');
  }

  var console = {
    log: function () { write(joinArgs(arguments) + '\n'); },
    info: function () { write(joinArgs(arguments) + '\n'); },
    debug: function () { write(joinArgs(arguments) + '\n'); },
    dir: function (value) { write(inspect(value, 1, []) + '\n'); },
    warn: function () { writeErr(joinArgs(arguments) + '\n'); },
    error: function () { writeErr(joinArgs(arguments) + '\n'); },
    trace: function () {
      writeErr(joinArgs(arguments) + '\n' + cleanStack(new Error().stack) + '\n');
    },
    table: function (value) { write(inspect(value, 1, []) + '\n'); },
    assert: function (ok) {
      if (!ok) {
        writeErr('Assertion failed' +
                 (arguments.length > 1 ? ': ' + joinArgs([].slice.call(arguments, 1)) : '') + '\n');
      }
    },
    group: function () { write(joinArgs(arguments) + '\n'); },
    groupEnd: function () {},
    time: function (label) { timers[label || 'default'] = Date.now(); },
    timeEnd: function (label) {
      var key = label || 'default';
      if (timers[key] !== undefined) {
        write(key + ': ' + (Date.now() - timers[key]) + 'ms\n');
        delete timers[key];
      }
    },
  };
  var timers = {};
  window.console = console;

  // ------------------------------------------------------------------ input

  /**
   * Reads one line from the console.
   *
   * Returns a promise rather than blocking: JavaScript in a WebView shares a
   * thread with the app, so a genuine block would freeze the interface. `await`
   * makes it read the same either way.
   */
  function readLine(promptText) {
    if (promptText !== undefined && promptText !== null && promptText !== '') {
      write(String(promptText));
    }
    var id = nextInput++;
    pending++;
    return new Promise(function (resolve) {
      waiting[id] = resolve;
      bridge.readLine(token, String(id));
    });
  }

  window.__pycmd_resolve = function (id, hasValue, value) {
    var resolve = waiting[id];
    if (!resolve) return;
    delete waiting[id];
    pending--;
    resolve(hasValue ? value : null);
    maybeFinish();
  };

  // ----------------------------------------------------------------- timers

  var realSetTimeout = window.setTimeout.bind(window);
  var realClearTimeout = window.clearTimeout.bind(window);
  var realSetInterval = window.setInterval.bind(window);
  var realClearInterval = window.clearInterval.bind(window);

  /*
   * A run is over when nothing is left to do, not when the last line has been
   * read - otherwise `setTimeout(f, 100)` would print after the console has
   * already said the script finished. Counting outstanding work is what a
   * Node-shaped event loop does for you.
   */
  var spent = {};   // timeout ids that have fired or been cleared

  window.setTimeout = function (fn, delay) {
    if (typeof fn !== 'function') return realSetTimeout(fn, delay);
    var extra = [].slice.call(arguments, 2);
    pending++;
    var id = realSetTimeout(function () {
      spent[id] = true;
      try {
        fn.apply(null, extra);
      } catch (error) {
        report(error);
      } finally {
        pending--;
        maybeFinish();
      }
    }, delay);
    return id;
  };

  window.clearTimeout = function (id) {
    // A cleared timeout will never run, so its slot has to be released or the
    // run would wait forever for a callback that cannot arrive. Ids that
    // already fired are remembered, because clearing one of those a second
    // time must not release a slot that was never held.
    if (id !== undefined && id !== null && spent[id] !== true) {
      spent[id] = true;
      pending--;
      maybeFinish();
    }
    return realClearTimeout(id);
  };

  window.setInterval = function (fn, delay) {
    if (typeof fn !== 'function') return realSetInterval(fn, delay);
    var extra = [].slice.call(arguments, 2);
    pending++;
    var id = realSetInterval(function () {
      try {
        fn.apply(null, extra);
      } catch (error) {
        report(error);
      }
    }, delay);
    intervals[id] = true;
    return id;
  };

  window.clearInterval = function (id) {
    if (intervals[id]) {
      delete intervals[id];
      pending--;
      maybeFinish();
    }
    return realClearInterval(id);
  };

  function sleep(ms) {
    return new Promise(function (resolve) { window.setTimeout(resolve, ms || 0); });
  }

  // ------------------------------------------------------------- completion

  function report(error) {
    if (error && error.__pycmdExit !== undefined) {
      exiting = error.__pycmdExit;
      return;
    }
    if (!failed) failed = error;
    var text;
    if (error instanceof Error) {
      text = cleanStack(error.stack || (error.name + ': ' + error.message));
      if (!text) text = error.name + ': ' + error.message;
    } else {
      text = 'Uncaught ' + inspect(error, 1, []);
    }
    writeErr(text + '\n');
  }

  function maybeFinish() {
    if (finished || !settled) return;
    if (exiting === null && pending > 0) return;
    finished = true;
    // Anything still scheduled belongs to a run that is over.
    Object.keys(intervals).forEach(function (id) { realClearInterval(id); });
    var status = failed ? 'error' : 'ok';
    var code = exiting === null ? 0 : exiting;
    bridge.finish(token, status, String(code), failed ? String(failed && failed.message || failed) : '');
  }

  window.addEventListener('error', function (event) {
    if (finished) return;
    report(event.error || new Error(event.message));
    maybeFinish();
  });

  window.addEventListener('unhandledrejection', function (event) {
    if (finished) return;
    report(event.reason instanceof Error ? event.reason : new Error(inspect(event.reason, 1, [])));
    event.preventDefault();
    maybeFinish();
  });

  // -------------------------------------------------------------- user API

  function exit(code) {
    var error = new Error('exit');
    error.__pycmdExit = code === undefined ? 0 : code;
    throw error;
  }

  window.print = function () { write(joinArgs(arguments) + '\n'); };
  window.readLine = readLine;
  window.input = readLine;
  window.prompt = function (message) { return readLine(message); };
  window.sleep = sleep;
  window.exit = exit;
  window.alert = function (message) { write(inspect(message, 0, []) + '\n'); };

  /** A tiny stand-in for the shape scripts expect to find. */
  window.process = {
    argv: ['pycmd', ''],
    platform: 'android',
    env: {},
    exit: exit,
    stdout: { write: function (text) { write(text); return true; } },
    stderr: { write: function (text) { writeErr(text); return true; } },
  };

  // ------------------------------------------------------------------- run

  /*
   * The body is wrapped in an async function so that top-level `await` works,
   * which is what makes `await readLine()` read like input() does in Python.
   * The wrapper opens on the same line the user's first line starts on, so
   * line numbers in a stack trace still point at the right line.
   */
  window.__pycmd_run = function (source, name, runToken) {
    token = String(runToken);
    window.process.argv[1] = name;
    var wrapped = '(async function () { "use strict";' + source +
                  '\n})()\n//# sourceURL=' + name + '\n';
    var promise;
    try {
      promise = (0, eval)(wrapped);
    } catch (error) {
      // A syntax error never becomes a promise.
      report(error);
      settled = true;
      maybeFinish();
      return;
    }
    promise.then(function () {
      settled = true;
      maybeFinish();
    }, function (error) {
      report(error);
      settled = true;
      maybeFinish();
    });
  };

  bridge.ready();
})();
