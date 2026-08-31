/*
 * Measures a plugin panel the way a phone would.
 *
 * Every other check in this suite reads source or drives a hand-written DOM.
 * This one lays the panels out in a real browser at a phone's size, drags a
 * finger down them, and asks whether anything moved - which is the only way
 * to catch the class of bug this exists for: a panel taller than the screen
 * whose bottom nobody can reach.
 *
 * It found two things worth keeping a test for. A panel is not scrolled by
 * the document but by its own `body`, because leaving it to the document is
 * what did not work on a phone; and that only works if the root element's
 * overflow is hidden, because otherwise the browser hands the body's overflow
 * up to the viewport and puts the scrolling back where it was broken.
 *
 * Needs `playwright-core` and the Chromium at PLAYWRIGHT_BROWSERS_PATH. It
 * says so and skips when they are not there, rather than failing a suite that
 * is otherwise about logic.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const os = require('os');

const ROOT = path.join(__dirname, '..');

let chromium;
try {
  ({ chromium } = require('playwright-core'));
} catch (error) {
  console.log('  SKIP  panel layout - playwright-core is not installed');
  process.exit(0);
}

const CHROME = [
  process.env.PYCMD_CHROMIUM,
  '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  '/opt/pw-browsers/chromium/chrome-linux/chrome',
].find((candidate) => candidate && fs.existsSync(candidate));

if (!CHROME) {
  console.log('  SKIP  panel layout - no Chromium to lay the panels out in');
  process.exit(0);
}

let failures = 0;
let checks = 0;

function check(name, condition, detail) {
  checks += 1;
  if (condition) {
    console.log(`  PASS  ${name}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${name}${detail === undefined ? '' : `  (${JSON.stringify(detail)})`}`);
  }
}

/** Builds every bundled panel exactly as the app serves it. */
function buildPanels() {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'pycmd-panels-'));
  const python = process.env.PYTHON || 'python3.13';
  const script = `
import json, os, sys, tempfile
root = ${JSON.stringify(ROOT)}
sys.path.insert(0, os.path.join(root, "app", "src", "main", "python"))
import pycmd_plugins as plugins
scratch = tempfile.mkdtemp()
plugins.configure(os.path.join(scratch, "plugins"), os.path.join(scratch, "workspace"), None)
base = os.path.join(root, "app", "src", "main", "assets", "plugins")
made = []
for name in sorted(os.listdir(base)):
    folder = os.path.join(base, name)
    reply = json.loads(plugins.install(folder))
    if not reply.get("ok"):
        continue
    for panel in sorted(f for f in os.listdir(folder) if f.endswith(".html")):
        where = os.path.join(${JSON.stringify(out)}, name + "-" + panel)
        with open(where, "w", encoding="utf-8") as handle:
            handle.write(plugins.panel_html(reply["manifest"]["id"], panel))
        made.append([name + "/" + panel, where])
sys.stdout.write(json.dumps(made))
`;
  return JSON.parse(execFileSync(python, ['-c', script], { encoding: 'utf8' }));
}

/** A finger, dragged up the middle of the panel. */
async function dragUp(page, from, to) {
  const session = await page.context().newCDPSession(page);
  await session.send('Input.dispatchTouchEvent', {
    type: 'touchStart', touchPoints: [{ x: 195, y: from }],
  });
  for (let y = from; y >= to; y -= 40) {
    await session.send('Input.dispatchTouchEvent', {
      type: 'touchMove', touchPoints: [{ x: 195, y }],
    });
  }
  await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await page.waitForTimeout(350);
}

async function main() {
  const panels = buildPanels();
  const browser = await chromium.launch({ executablePath: CHROME });

  console.log('== every panel can be scrolled to its end ==');
  for (const [name, file] of panels) {
    // Roughly the room a panel gets: the screen, less the app bar, the
    // panel's own header and the navigation bar.
    const page = await browser.newPage({
      viewport: { width: 390, height: 560 }, hasTouch: true,
    });
    await page.addInitScript(() => {
      window.__pycmd_panel = {
        call(id) {
          setTimeout(
            () => window.__pycmd_resolve(String(id), true, JSON.stringify({ ok: true, result: {} })),
            5,
          );
        },
        innerScroll() {}, toast() {}, log() {}, close() {},
        manifest() { return JSON.stringify({ id: 'test.plugin', name: 'Test' }); },
      };
    });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('file://' + file);
    await page.waitForTimeout(900);

    const before = await page.evaluate(() => {
      const scrollers = [document.body, ...document.querySelectorAll('*')]
        .filter((el) => {
          const style = getComputedStyle(el);
          return /(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 2;
        });
      return {
        rootOverflow: getComputedStyle(document.documentElement).overflow,
        documentScrolls:
          document.documentElement.scrollHeight > document.documentElement.clientHeight + 2,
        overflows: scrollers.length > 0,
      };
    });

    check(`${name}: the document itself is not the scroller`, !before.documentScrolls, before);

    if (!before.overflows) {
      check(`${name}: it fits, so there is nothing to reach`, true);
    } else {
      await dragUp(page, 460, 140);
      const moved = await page.evaluate(() =>
        [document.body, ...document.querySelectorAll('*')]
          .some((el) => el.scrollTop > 0));
      check(`${name}: a finger drag moves it`, moved);
    }

    check(`${name}: nothing threw while it drew`, errors.length === 0, errors);
    await page.close();
  }

  console.log('\n== the shared stylesheet keeps the arrangement that works ==');
  const [, firstPanel] = panels[0];
  const html = fs.readFileSync(firstPanel, 'utf8');
  check('the root is a fixed-height box that does not scroll',
        /html\s*\{[^}]*height:\s*100%[^}]*overflow:\s*hidden/.test(html), '');
  check('and the body is what scrolls',
        /body\s*\{[^}]*height:\s*100%[^}]*overflow-y:\s*auto/.test(html), '');

  await browser.close();

  console.log(`\n${checks} checks, ${failures} failed`);
  if (failures) process.exit(1);
  console.log('all panel layout checks passed');
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
