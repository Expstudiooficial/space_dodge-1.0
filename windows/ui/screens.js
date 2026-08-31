/*
 * One function per screen. Each is handed the empty middle of the window and
 * fills it.
 *
 * The console and the editor are iframes onto `/web/console.html` and
 * `/web/editor.html` - the very files the phone loads into its WebView, not
 * copies of them. Everything is served from the same 127.0.0.1 origin, so the
 * shell can reach into the frame and call `PyConsole.append` directly, which
 * is what the Kotlin side does with `evaluateJavascript`. That is the whole
 * trick behind this being a port rather than a rewrite.
 */
'use strict';

const el = PyCmd.el;
const clear = PyCmd.clear;

function head(title, lead) {
  return el('div', {},
    el('h1', { text: title }),
    lead ? el('p', { class: 'lead', text: lead }) : null);
}

function card(...children) {
  return el('div', { class: 'card' }, ...children);
}

// ---------------------------------------------------------------------------
// Console
// ---------------------------------------------------------------------------

let consoleFrame = null;
let consoleQueue = [];

function consoleReady() {
  return consoleFrame && consoleFrame.contentWindow && consoleFrame.contentWindow.PyConsole;
}

function consoleWrite(stream, text) {
  if (!consoleReady()) {
    consoleQueue.push([stream, text]);
    if (consoleQueue.length > 4000) consoleQueue.splice(0, consoleQueue.length - 4000);
    return;
  }
  consoleFrame.contentWindow.PyConsole.append(stream, text);
}

PyCmd.on('output', (event) => consoleWrite(event.stream, event.text));

/**
 * A script called input().
 *
 * The interpreter thread is blocked waiting, so this asks and hands the answer
 * straight back. Cancelling sends an empty line rather than nothing at all,
 * because nothing at all leaves that thread waiting for ten minutes.
 */
PyCmd.on('input-wanted', () => {
  const box = el('input', { placeholder: 'Your program is waiting for a line…' });
  const send = () => {
    PyCmd.call('console.stdin', { text: box.value });
    consoleWrite('stdin', box.value + '\n');
    PyCmd.closeSheet();
  };
  box.addEventListener('keydown', (event) => { if (event.key === 'Enter') send(); });
  PyCmd.sheet('Your program is asking for something', el('div', {},
    el('p', { class: 'muted', text: 'Whatever you type goes to input().' }),
    box,
    el('div', { class: 'row', style: 'margin-top:12px' },
      el('button', { class: 'small primary', text: 'Send', onclick: send }),
      el('button', {
        class: 'small', text: 'Send nothing',
        onclick: () => { PyCmd.call('console.stdin', { text: '' }); PyCmd.closeSheet(); },
      }))));
  setTimeout(() => box.focus(), 60);
});
PyCmd.on('finished', (event) => {
  if (event.status === 'error') consoleWrite('stderr', '');
});

function Console(screen) {
  screen.classList.add('flush');
  const wrap = el('div', {
    style: 'display:grid;grid-template-rows:1fr auto;height:100%;min-height:0',
  });

  const frame = el('iframe', { class: 'frame', src: '/web/console.html' });
  consoleFrame = frame;
  frame.addEventListener('load', () => {
    const pending = consoleQueue;
    consoleQueue = [];
    pending.forEach(([stream, text]) => consoleWrite(stream, text));
  });

  const input = el('input', {
    placeholder: 'Python, or a command like  ls · run app.py · pip install flask',
    spellcheck: 'false', autocomplete: 'off',
  });

  async function send() {
    const text = input.value;
    if (!text.trim()) return;
    input.value = '';
    consoleWrite('stdin', '>>> ' + text + '\n');
    const reply = await PyCmd.call('console.run', { text });
    if (!reply.ok) consoleWrite('stderr', (reply.error || 'that did not run') + '\n');
  }

  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); }
  });

  const bar = el('div', {
    class: 'row',
    style: 'padding:10px 12px;border-top:1px solid var(--line);background:var(--surface)',
  },
    input,
    el('button', { class: 'small primary', text: 'Run', onclick: send }),
    el('button', {
      class: 'small', text: 'Clear',
      onclick: () => { if (consoleReady()) consoleFrame.contentWindow.PyConsole.clear(); },
    }),
  );

  wrap.appendChild(frame);
  wrap.appendChild(bar);
  screen.appendChild(wrap);
  setTimeout(() => input.focus(), 60);
}

// ---------------------------------------------------------------------------
// Editor
// ---------------------------------------------------------------------------

function Editor(screen) {
  screen.classList.add('flush');
  screen.appendChild(el('iframe', { class: 'frame', src: '/web/editor.html' }));
}

// ---------------------------------------------------------------------------
// Files
// ---------------------------------------------------------------------------

async function Files(screen) {
  screen.appendChild(head('Files', 'Your workspace. Everything PyCmd writes lives here.'));
  const reply = await PyCmd.call('shell', { line: 'ls' });
  const body = card();
  if (reply.ok && reply.output) {
    body.appendChild(el('pre', { class: 'out', text: reply.output }));
  } else {
    body.appendChild(el('div', { class: 'empty', text: 'Nothing here yet. Make something in the console.' }));
  }
  screen.appendChild(body);
  screen.appendChild(el('p', { class: 'muted' },
    'The workspace is at ', el('code', { text: PyCmd.state.root || '…' }), '\\workspace — ',
    'an ordinary Windows folder you can open in Explorer, back up, or put in git.'));
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------

async function Run(screen) {
  screen.appendChild(head('Run a file',
    'Type a path and PyCmd works out what runs it — the real compiler if you have one, ' +
    'the interpreter it carries if you do not.'));

  const path = el('input', { placeholder: 'hello.go', spellcheck: 'false' });
  const pick = el('select', {});
  pick.appendChild(el('option', { value: '', text: 'Best available toolchain' }));
  (PyCmd.state.toolchains || []).filter((c) => c.installed).forEach((c) => {
    pick.appendChild(el('option', { value: c.id, text: c.name + ' — ' + c.languages.join(', ') }));
  });

  async function run() {
    const value = path.value.trim();
    if (!value) return;
    const full = value.includes(':') || value.startsWith('\\')
      ? value
      : (PyCmd.state.root || '') + '\\workspace\\' + value;
    PyCmd.toast('Running ' + value + ' — output is on the Console.');
    const reply = await PyCmd.call('run.file', { path: full, toolchain: pick.value });
    if (!reply.ok) PyCmd.toast(reply.error || 'that did not start');
  }

  screen.appendChild(card(
    el('label', { class: 'field' }, el('span', { text: 'File, relative to the workspace' }), path),
    el('label', { class: 'field' }, el('span', { text: 'Run it with' }), pick),
    el('div', { class: 'row' },
      el('button', { class: 'small primary', text: 'Run', onclick: run }),
      el('button', { class: 'small', text: 'Stop', onclick: () => PyCmd.call('run.stop') }),
      el('span', { class: 'muted', text: 'Output goes to the Console.' }),
    ),
  ));

  const stats = PyCmd.state.languageStats || {};
  screen.appendChild(el('p', { class: 'muted' },
    String(stats.runnable || 0), ' of ', String(stats.total || 0),
    ' file types can be run here. The Toolchains screen says which of them this machine is ready for.'));
}

// ---------------------------------------------------------------------------
// Toolchains
// ---------------------------------------------------------------------------

async function Toolchains(screen) {
  screen.appendChild(head('Toolchains',
    'What is installed on this machine, and what each one lets PyCmd run. ' +
    'PyCmd does not bundle compilers — a build carrying MSVC and a JDK would be gigabytes — ' +
    'so these are yours, found on the PATH.'));

  const status = el('p', { class: 'muted', text: 'Looking…' });
  screen.appendChild(el('div', { class: 'row' },
    el('button', {
      class: 'small', text: 'Look again',
      onclick: async () => {
        status.textContent = 'Looking…';
        const reply = await PyCmd.call('toolchains', { refresh: true });
        if (reply.ok) {
          PyCmd.state.toolchains = reply.toolchains;
          PyCmd.state.toolchainSummary = reply.summary;
        }
        draw();
      },
    }),
    status,
  ));

  const host = el('div', {});
  screen.appendChild(host);

  function draw() {
    const rows = PyCmd.state.toolchains || [];
    const found = rows.filter((r) => r.installed);
    const missing = rows.filter((r) => !r.installed);
    status.textContent = found.length + ' of ' + rows.length + ' found · ' +
      (PyCmd.state.toolchainSummary.language_count || 0) + ' languages ready';

    clear(host);
    host.appendChild(el('h2', { text: 'Here now' }));
    if (!found.length) {
      host.appendChild(el('div', { class: 'empty' },
        'None found yet. PyCmd still runs Python, C, Go, Rust and JavaScript on the ' +
        'interpreters it carries — install anything below to use the real thing instead.'));
    }
    const grid = el('div', { class: 'grid' });
    found.forEach((row) => grid.appendChild(chainCard(row)));
    host.appendChild(grid);

    host.appendChild(el('h2', { text: 'Not installed' }));
    const rest = el('div', { class: 'grid' });
    missing.forEach((row) => rest.appendChild(chainCard(row)));
    host.appendChild(rest);
  }

  function chainCard(row) {
    const install = row.install || {};
    const lines = [];
    ['winget', 'scoop', 'choco'].forEach((manager) => {
      if (install[manager]) {
        lines.push(el('div', { class: 'row', style: 'gap:6px;margin-top:5px' },
          el('code', { class: 'mono', style: 'flex:1 1 auto', text: install[manager] }),
          el('button', {
            class: 'small', text: 'Run',
            onclick: async () => {
              PyCmd.toast('Installing ' + row.name + ' — watch the Console.');
              await PyCmd.call('toolchain.install', { id: row.id, with: manager });
            },
          }),
        ));
      }
    });

    return card(
      el('div', { class: 'row spread' },
        el('b', { text: row.name }),
        row.installed
          ? el('span', { class: 'pill on', text: row.version || 'found' })
          : el('span', { class: 'pill off', text: 'not here' }),
      ),
      el('div', { style: 'margin:4px 0' },
        row.languages.map((id) => el('span', { class: 'pill', text: id }))),
      row.installed
        ? el('div', { class: 'muted mono', text: row.path })
        : el('div', {}, lines),
      row.note ? el('p', { class: 'muted', text: row.note }) : null,
      row.builds ? el('p', { class: 'muted', text: 'Compiles first, then runs what it built.' }) : null,
    );
  }

  draw();
}

// ---------------------------------------------------------------------------
// Languages
// ---------------------------------------------------------------------------

async function Languages(screen) {
  const stats = PyCmd.state.languageStats || {};
  screen.appendChild(head('Languages',
    stats.total + ' file types. ' + stats.runnable + ' run, ' + stats.preview +
    ' preview, ' + stats.editable + ' are edited and served, ' + stats.media + ' are media.'));

  const search = el('input', { placeholder: 'Search — rust, .cs, compiler…', spellcheck: 'false' });
  screen.appendChild(el('div', { class: 'card tight' }, search));
  const host = el('div', {});
  screen.appendChild(host);

  function draw() {
    const needle = search.value.trim().toLowerCase();
    const rows = (PyCmd.state.languages || []).filter((row) => {
      if (!needle) return true;
      return (row.name + ' ' + row.id + ' ' + row.extensions + ' ' +
              (row.toolchain_names || []).join(' ')).toLowerCase().includes(needle);
    });
    clear(host);
    host.appendChild(el('p', { class: 'muted', text: rows.length + ' shown' }));
    const grid = el('div', { class: 'grid' });
    rows.forEach((row) => {
      const ready = (row.toolchains || []).some(
        (id) => (PyCmd.state.toolchains || []).some((c) => c.id === id && c.installed));
      grid.appendChild(card(
        el('div', { class: 'row spread' },
          el('b', { text: row.name }),
          el('span', {
            class: 'pill ' + (row.mode === 'run' ? (ready ? 'on' : '') : 'off'),
            text: row.mode === 'run' ? (ready ? 'ready' : 'needs a toolchain') : row.mode,
          }),
        ),
        el('div', { class: 'muted mono', text: row.extensions }),
        row.note ? el('p', { class: 'muted', text: row.note }) : null,
      ));
    });
    host.appendChild(grid);
  }

  search.addEventListener('input', draw);
  draw();
}

// ---------------------------------------------------------------------------
// Plugins — the two halves, and bringing one over from the phone
// ---------------------------------------------------------------------------

async function Plugins(screen) {
  screen.appendChild(head('Plugins',
    'Thirteen are part of PyCmd and switch on and off. The rest are folders of ' +
    'Python and HTML, installed here or brought from a phone.'));

  const reply = await PyCmd.call('plugins');
  if (reply.ok) PyCmd.state.plugins = reply;
  const builtin = (reply.builtin || {});

  screen.appendChild(card(
    el('div', { class: 'row spread' },
      el('div', {},
        el('b', { text: 'Bring a plugin over from the phone' }),
        el('div', { class: 'muted', text: 'A folder with plugin.json in it, or a .zip of one.' })),
      el('button', { class: 'small primary', text: 'Choose…', onclick: importMobile }),
    ),
    el('p', { class: 'muted' },
      el('b', { text: 'Beta. ' }),
      'The plugin API is the same on both, so most phone plugins simply work — but ' +
      'not all of them do. PyCmd reads the plugin before installing it and tells you ' +
      'which parts of it this machine cannot honour. Anything that reaches for Android ' +
      'itself — notifications, wake locks, the media session, a /storage path — will ' +
      'not work here, and no amount of good will makes it.'),
  ));

  (builtin.groups || []).forEach((group) => {
    screen.appendChild(el('h2', { text: group.name }));
    const grid = el('div', { class: 'grid' });
    group.plugins.forEach((plugin) => grid.appendChild(builtinCard(plugin)));
    screen.appendChild(grid);
  });

  screen.appendChild(el('h2', { text: 'Installed' }));
  const installed = reply.installed || [];
  if (!installed.length) {
    screen.appendChild(el('div', { class: 'empty', text: 'None yet.' }));
  } else {
    const grid = el('div', { class: 'grid' });
    installed.forEach((plugin) => {
      grid.appendChild(card(
        el('div', { class: 'row spread' },
          el('b', { text: plugin.name || plugin.id }),
          el('span', { class: 'pill', text: plugin.version || '' })),
        el('p', { class: 'muted', text: (plugin.description || '').slice(0, 220) }),
        plugin.broken
          ? el('p', { class: 'muted', text: 'This one will not load: ' + (plugin.error || '') })
          : el('div', { class: 'row', style: 'margin-top:8px' },
              plugin.panel
                ? el('button', {
                    class: 'small primary', text: 'Open',
                    onclick: () => openPanel(plugin, plugin.panel),
                  })
                : null,
              el('button', {
                class: 'small', text: 'Settings',
                onclick: () => openSettings(plugin),
              }),
              el('button', {
                class: 'small danger', text: 'Remove',
                onclick: async () => {
                  const done = await PyCmd.call('plugin.remove', { id: plugin.id });
                  PyCmd.toast(done.ok ? (plugin.name + ' removed') : (done.error || 'no'));
                  if (done.ok) go('plugins');
                },
              }),
            ),
      ));
    });
    screen.appendChild(grid);
  }
}

function builtinCard(plugin) {
  const toggle = el('div', { class: 'switch' + (plugin.enabled ? ' on' : '') });
  toggle.addEventListener('click', async () => {
    const wanted = !toggle.classList.contains('on');
    const done = await PyCmd.call('builtin.set', { id: plugin.id, on: wanted });
    if (done.ok) { go('plugins'); PyCmd.toast(plugin.name + (wanted ? ' on' : ' off')); }
  });
  return card(
    el('div', { class: 'row spread' },
      el('div', {},
        el('b', { text: plugin.name }),
        el('div', { class: 'muted', text: plugin.tagline })),
      toggle),
    el('p', { class: 'muted', text: plugin.description }),
    plugin.powered_up
      ? el('p', { class: 'muted' }, el('b', { text: 'With Power Pack: ' }), plugin.powered_up)
      : null,
    plugin.windows_note
      ? el('p', { class: 'muted' }, el('b', { text: 'On Windows: ' }), plugin.windows_note)
      : null,
  );
}

async function openSettings(plugin) {
  const reply = await PyCmd.call('plugin.settings', { id: plugin.id });
  const rows = (reply && reply.settings) || [];
  if (!rows.length) {
    PyCmd.sheet(plugin.name || plugin.id,
      el('p', { class: 'muted', text: 'This plugin has no settings.' }));
    return;
  }
  const body = el('div', {});
  rows.forEach((row) => {
    const kind = row.type === 'switch' ? 'checkbox' : row.type === 'number' ? 'number' : 'text';
    let input;
    if (row.type === 'choice') {
      input = el('select', {});
      (row.options || []).forEach((option) => {
        input.appendChild(el('option', { value: option, text: option,
                                         selected: option === row.value }));
      });
    } else {
      input = el('input', { type: kind });
      if (kind === 'checkbox') input.checked = !!row.value;
      else input.value = row.value === null || row.value === undefined ? '' : String(row.value);
    }
    input.addEventListener('change', () => {
      const value = kind === 'checkbox' ? (input.checked ? '1' : '') : input.value;
      PyCmd.call('plugin.setting.set', { id: plugin.id, name: row.name, value });
    });
    body.appendChild(el('label', { class: 'field' },
      el('span', { text: row.label || row.name }), input,
      row.help ? el('span', { class: 'muted', text: row.help }) : null));
  });
  PyCmd.sheet(plugin.name || plugin.id, body);
}

async function importMobile() {
  const path = el('input', {
    placeholder: 'C:\\Users\\you\\Downloads\\my-plugin.zip',
    spellcheck: 'false',
  });
  const report = el('div', {});

  async function look() {
    clear(report).appendChild(el('p', { class: 'muted', text: 'Reading it…' }));
    const found = await PyCmd.call('plugin.inspect', { path: path.value.trim() });
    clear(report);
    if (!found.ok) {
      report.appendChild(el('p', { class: 'muted', text: found.error }));
      return;
    }
    report.appendChild(el('div', { class: 'row spread' },
      el('b', { text: found.name + ' ' + (found.version || '') }),
      el('span', {
        class: 'pill ' + (found.likely === 'fine' ? 'on' : ''),
        text: found.likely === 'fine' ? 'should work' : 'partly',
      })));
    if (found.description) {
      report.appendChild(el('p', { class: 'muted', text: found.description.slice(0, 300) }));
    }
    if (found.warnings.length) {
      report.appendChild(el('h2', { text: 'What will not carry over' }));
      found.warnings.forEach((warning) => {
        report.appendChild(el('p', { class: 'muted' },
          el('b', { text: warning.about + ': ' }), warning.detail));
      });
    } else {
      report.appendChild(el('p', { class: 'muted' },
        'Nothing in it reaches for Android. It should behave exactly as it did on the phone.'));
    }
    report.appendChild(el('div', { class: 'row', style: 'margin-top:12px' },
      el('button', {
        class: 'small primary', text: 'Install it',
        onclick: async () => {
          const done = await PyCmd.call('plugin.install', { path: found.folder });
          if (done.ok) {
            PyCmd.closeSheet();
            PyCmd.toast(found.name + ' installed. It is switched off until you turn it on.');
            go('plugins');
          } else {
            PyCmd.toast(done.error || 'that would not install');
          }
        },
      }),
      el('span', { class: 'muted', text: 'It arrives switched off, like any other plugin.' }),
    ));
  }

  PyCmd.sheet('Bring a plugin over', el('div', {},
    el('p', { class: 'muted' },
      'PyCmd plugins are folders of Python and HTML, and the plugin API is the ' +
      'same on the phone and here — so most of them work unchanged. Point at one ' +
      'and PyCmd will read it first and tell you what it finds.'),
    el('label', { class: 'field' },
      el('span', { text: 'Folder or .zip' }), path),
    el('button', { class: 'small', text: 'Read it', onclick: look }),
    report,
  ));
}

// ---------------------------------------------------------------------------
// A plugin's own panel
// ---------------------------------------------------------------------------

/**
 * Opens a plugin's page.
 *
 * The HTML comes from the same `panel_html` the phone build uses - house
 * stylesheet and bridge already injected - so what lands here is byte for byte
 * what a phone would show. It goes into an iframe with `srcdoc`, which keeps
 * this origin, which is what lets the object the page expects be put on its
 * window before its own script runs.
 *
 * `__pycmd_panel` is the same four verbs Kotlin exposes: call, toast, log,
 * close. The plugin cannot tell the difference, and that is the whole point.
 */
async function openPanel(plugin, panelFile) {
  const reply = await PyCmd.call('plugin.panel', { id: plugin.id, panel: panelFile || '' });
  if (!reply.ok || !reply.html) {
    PyCmd.toast((reply && reply.error) || 'that panel would not build');
    return;
  }

  const frame = el('iframe', {
    style: 'width:100%;height:70vh;border:0;border-radius:10px;background:var(--bg)',
    src: 'about:blank',
  });

  /*
   * The object goes on first, then the document is written into the frame.
   *
   * With `srcdoc` the panel's own scripts run before anything outside can
   * touch the frame, and the bridge's very first line is
   * `JSON.parse(window.__pycmd_panel.manifest())` - so every panel threw
   * before it drew. Loading about:blank gives a real same-origin window to
   * put the object on; writing the HTML afterwards means the scripts find it
   * already there, which is exactly the order Kotlin's addJavascriptInterface
   * guarantees on the phone.
   */
  frame.addEventListener('load', function install() {
    frame.removeEventListener('load', install);
    const view = frame.contentWindow;
    if (!view || view.__pycmd_panel) return;
    view.__pycmd_panel = {
      call(id, name, body) {
        let payload = null;
        try { payload = JSON.parse(body); } catch (error) { payload = body; }
        PyCmd.call('plugin.export', { id: plugin.id, name, payload }).then((answer) => {
          if (!view.__pycmd_resolve) return;
          view.__pycmd_resolve(String(id), answer.ok !== false, JSON.stringify(answer));
        });
      },
      toast: (text) => PyCmd.toast(String(text).slice(0, 300)),
      log: (text) => console.log('[' + plugin.id + ']', text),
      close: () => PyCmd.closeSheet(),
      innerScroll() {},
      manifest: () => JSON.stringify({
        id: plugin.id, name: plugin.name, version: plugin.version, author: plugin.author,
      }),
    };
    const document_ = view.document;
    document_.open();
    document_.write(reply.html);
    document_.close();
  });

  PyCmd.sheet(plugin.name || plugin.id, frame);
}

// A plugin pushing to its own panel, the way api.send does on the phone.
PyCmd.on('plugin-message', (event) => {
  document.querySelectorAll('iframe[srcdoc]').forEach((frame) => {
    const view = frame.contentWindow;
    if (view && view.__pycmd_message) view.__pycmd_message(event.body);
  });
});

// ---------------------------------------------------------------------------
// The rest
// ---------------------------------------------------------------------------

async function Servers(screen) {
  screen.appendChild(head('Servers', 'Run a script, a folder or a page and reach it over HTTP.'));
  const reply = await PyCmd.call('servers');
  const rows = (reply && reply.servers) || [];
  if (!rows.length) {
    screen.appendChild(el('div', { class: 'empty', text: 'Nothing running.' }));
  } else {
    rows.forEach((row) => screen.appendChild(card(
      el('div', { class: 'row spread' },
        el('b', { text: row.label || row.path || 'server' }),
        el('span', { class: 'pill on', text: ':' + row.port })),
      el('div', { class: 'muted mono', text: row.url || '' }),
    )));
  }
}

async function Packages(screen) {
  screen.appendChild(head('Packages',
    'Python libraries, installed into PyCmd’s own site-packages rather than the ' +
    'system Python — so nothing here can break anything else on the machine.'));
  const reply = await PyCmd.call('packages');
  const rows = (reply && reply.packages) || [];
  screen.appendChild(card(
    el('p', { class: 'muted', text: 'Install with  pip install <name>  on the Console.' })));
  if (!rows.length) {
    screen.appendChild(el('div', { class: 'empty', text: 'None installed yet.' }));
    return;
  }
  const grid = el('div', { class: 'grid' });
  rows.forEach((row) => grid.appendChild(card(
    el('div', { class: 'row spread' },
      el('b', { text: row.name }), el('span', { class: 'pill', text: row.version || '' })))));
  screen.appendChild(grid);
}

async function Pages(screen) {
  screen.appendChild(head('Pages', 'Point at a folder in the workspace and serve it for real.'));
  const reply = await PyCmd.call('pages');
  const rows = (reply && reply.pages) || [];
  if (!rows.length) {
    screen.appendChild(el('div', { class: 'empty', text: 'No pages yet.' }));
    return;
  }
  rows.forEach((row) => screen.appendChild(card(
    el('div', { class: 'row spread' },
      el('b', { text: row.name || row.id }),
      el('span', { class: 'pill' + (row.active ? ' on' : ''), text: row.active ? 'live' : 'off' })),
    el('div', { class: 'muted mono', text: row.url || row.folder || '' }))));
}

async function Docs(screen) {
  screen.appendChild(head('Guides', 'How PyCmd works, written for Windows.'));
  const guides = [
    ['README.md', 'What PyCmd is', 'The tour: every screen, and what it does.'],
    ['TUTORIAL.md', 'Getting started', 'From a fresh install to a running program.'],
    ['TOOLCHAINS.md', 'Compilers and languages', 'What runs what, and how to install the rest.'],
    ['PLUGINS.md', 'Writing a plugin', 'The whole plugin API, and what changes on Windows.'],
    ['MOBILE.md', 'Coming from the phone', 'What carries over, what does not, and why.'],
    ['FORKING.md', 'Forking PyCmd', 'Building the exe yourself, and where the source is.'],
  ];
  const grid = el('div', { class: 'grid' });
  guides.forEach(([file, title, blurb]) => {
    grid.appendChild(card(
      el('b', { text: title }),
      el('p', { class: 'muted', text: blurb }),
      el('button', {
        class: 'small', text: 'Read',
        onclick: async () => {
          const reply = await fetch('/wdocs/' + file).then((r) => r.ok ? r.text() : '');
          PyCmd.sheet(title, el('pre', {
            class: 'out',
            style: 'max-height:none;white-space:pre-wrap',
            text: reply || 'That guide is not in this build.',
          }));
        },
      }),
    ));
  });
  screen.appendChild(grid);
}

async function System(screen) {
  screen.appendChild(head('System', 'What PyCmd is using, and where.'));
  const reply = await PyCmd.call('system');
  if (!reply.ok) {
    screen.appendChild(el('div', { class: 'empty', text: reply.error || 'nothing to show' }));
    return;
  }
  const store = reply.store || {};

  if (PyCmd.state.update) {
    const update = PyCmd.state.update;
    screen.appendChild(card(
      el('b', { text: 'PyCmd ' + update.version + ' is out' }),
      el('p', { class: 'muted', text: update.notes || '' }),
      el('p', { class: 'muted' },
        'It downloads to your Downloads folder and is checked against its ' +
        'published checksum. Replacing the exe is a step you take yourself — ' +
        'an app that swaps its own exe while you are using it eventually swaps ' +
        'in a broken one.'),
    ));
  }

  screen.appendChild(card(
    el('div', { class: 'row spread' }, el('b', { text: 'PyCmd' }),
      el('span', { class: 'pill on', text: reply.version })),
    el('div', { class: 'muted' }, 'Python ', reply.python),
    el('div', { class: 'muted mono', text: store.root || '' }),
    store.portable ? el('p', { class: 'muted', text: 'Portable: PYCMD_HOME is set, so everything lives beside the exe.' }) : null,
  ));

  const grid = el('div', { class: 'grid' });
  ['workspace', 'site-packages', 'downloads', 'plugins', 'pages', 'music', 'versions', 'cache']
    .forEach((name) => {
      const row = store[name];
      if (!row) return;
      grid.appendChild(card(
        el('div', { class: 'row spread' },
          el('b', { text: name }),
          el('span', { class: 'pill', text: PyCmd.bytes(row.bytes) })),
        el('div', { class: 'muted', text: row.files + ' files' }),
        el('div', { class: 'muted mono', style: 'font-size:11px', text: row.path }),
      ));
    });
  screen.appendChild(grid);
  screen.appendChild(el('p', { class: 'muted' },
    'Free on this drive: ', PyCmd.bytes(store.free_bytes)));
}

async function Log(screen) {
  screen.appendChild(head('Debug log', 'Everything PyCmd has said to itself.'));
  const reply = await PyCmd.call('log');
  const entries = (reply && reply.entries) || [];
  screen.appendChild(el('div', { class: 'row' },
    el('button', { class: 'small', text: 'Refresh', onclick: () => go('log') }),
    el('span', { class: 'muted', text: entries.length + ' entries' })));
  const host = el('div', { class: 'card' });
  if (!entries.length) host.appendChild(el('div', { class: 'empty', text: 'Nothing yet.' }));
  entries.slice(-400).reverse().forEach((entry) => {
    host.appendChild(el('div', { class: 'log-line ' + entry.level },
      el('span', { class: 'lvl', text: entry.level }),
      el('span', { text: entry.message }),
      entry.detail ? el('div', { class: 'det', text: entry.detail.slice(0, 1200) }) : null));
  });
  screen.appendChild(host);
}

window.Screens = {
  console: Console,
  editor: Editor,
  files: Files,
  run: Run,
  toolchains: Toolchains,
  languages: Languages,
  servers: Servers,
  pages: Pages,
  packages: Packages,
  plugins: Plugins,
  docs: Docs,
  system: System,
  log: Log,
};
