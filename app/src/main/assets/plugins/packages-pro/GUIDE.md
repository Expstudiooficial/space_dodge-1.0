# Packages Pro

The Packages tab installs Python. This installs everything else.

## Why it exists

A page that wants htmx or a chart library has one option on a phone: a CDN.
That means it only works with a connection - and PyCmd's preview is a loopback
server, so "needs the internet" turns "open my page" into "open my page,
maybe". Vendoring the file fixes it once: one fetch, one file in `vendor/`,
and the page works on a plane.

## Web libraries

**Packages → Web libraries and kits**, or from the console:

```
web install htmx
web install chart.js
web install @fontsource/inter
web list
web remove htmx
web catalogue
```

Seventeen libraries have a one-tap button, because npm packages disagree about
where their built file lives and a wrong guess is a broken page: htmx, Alpine,
Tailwind, Bootstrap, Bulma, normalize.css, three.js, Chart.js, D3, Vue, Preact,
marked, highlight.js, Lodash, Day.js and two self-hosted fonts.

Anything else on npm works by its own name - the file is picked by looking at
what the package actually ships, preferring a minified build under `dist/`.

Files land in `vendor/<name>/` in your workspace. After a fetch the panel and
the console both print the tag to paste:

```html
<script src="vendor/htmx/htmx.min.js"></script>
```

## Kits

A kit is a folder, not a file, because the Servers tab knows how to run a
folder: point **Run a file** at it and it finds the `app.py` or the
`index.html` itself.

```
kit new blog flask
kit new page site
kit new demo htmx
kit kits
```

| Kit | What you get |
|---|---|
| `flask` | `app.py`, `templates/index.html`, `static/style.css` - runs as it is |
| `site` | `index.html`, `style.css`, `app.js` |
| `htmx` | an htmx page and the Flask backend that answers it, htmx vendored in |
| `chart` | a page that draws a chart from data you edit, Chart.js vendored in |
| `three` | a rotating 3D scene |
| `api` | a Flask JSON API and a script that calls it |
| `cli` | a Python program with argparse and a `--help` |

## What it cannot do

**npm packages that need building.** React with JSX, anything with a bundler
step, anything whose published files are ES modules expecting a resolver -
those need Node and a build, and there is no Node on the device. Libraries that
ship a browser build (which is most of the ones people reach for) work.

**Compiled languages.** A Go module or a Rust crate has to be compiled, and
Android has not allowed an app to execute code it compiled itself since API 29.
The C, Go and Rust files here run on interpreters built into PyCmd; their
package ecosystems do not come with them.

**Python packages.** That is the Packages tab, or `pip install` in the console.

## Settings

| Setting | What it changes |
|---|---|
| Where libraries land | The folder inside your workspace. `vendor` by default. |
| Prefer minified files | Which build to take when a package ships both. |
| Open a new project after making it | Whether a kit opens its first file in the editor. |
