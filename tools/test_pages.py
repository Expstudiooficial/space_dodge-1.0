#!/usr/bin/env python3
"""Checks the Pages tab: projects, the tunnel, and Cloudflare.

Three things that all talk to the outside world, so all three are driven
against stand-ins here: a fake tunnel service and a fake Cloudflare, both
running on loopback, recording what was sent and answering the way the real
ones do. That makes the shapes, the ordering and the error handling checkable
without an account or a connection - which is the most that can be checked
from a machine that is not a phone.

The pages themselves are real: real folders, real ports, a real HTTP server
answering a real request.
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import socketserver
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import pycmd_cloudflare  # noqa: E402
import pycmd_pages  # noqa: E402
import pycmd_runtime  # noqa: E402
import pycmd_servers  # noqa: E402
import pycmd_tunnel  # noqa: E402

FAILURES = []
REAL = sys.__stdout__


def say(text=""):
    REAL.write(str(text) + "\n")
    REAL.flush()


def check(name, condition, detail=""):
    if condition:
        say(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        say(f"  FAIL  {name}  {detail}")


class Sink:
    def onOutput(self, stream, text, channel):  # noqa: N802
        pass

    def onReadLine(self, channel):  # noqa: N802
        return None

    def onFinished(self, run_id, status, millis):  # noqa: N802
        pass


workspace = tempfile.mkdtemp(prefix="pycmd-pages-ws-")
pycmd_runtime.configure(Sink(), workspace, tempfile.mkdtemp())
pycmd_pages.configure(tempfile.mkdtemp(prefix="pycmd-pages-"))

say("== making pages ==")
made = pycmd_pages.create("My Site", "static", workspace)
check("a page is made", made.get("ok"), made)
page = made.get("page", {})
check("with a folder", os.path.isdir(page.get("folder", "")), page)
check("and an index.html in it",
      os.path.isfile(os.path.join(page.get("folder", ""), "index.html")), page)
check("and a port of its own", pycmd_pages.PORT_FROM <= page.get("port", 0) <= pycmd_pages.PORT_TO,
      page.get("port"))
check("and it is not running yet", page.get("running") is False, page)
check("the folder is at the top of the workspace, not in a pages/ folder",
      os.path.dirname(page.get("folder", "")) == workspace and
      not os.path.isdir(os.path.join(workspace, "pages")),
      page.get("folder"))

again = pycmd_pages.create("my site", "static", workspace)
check("the same name twice is refused", not again.get("ok"), again)
check("with the reason", "already" in again.get("error", ""), again)

nameless = pycmd_pages.create("   ", "static", workspace)
check("a page with no name is refused", not nameless.get("ok"), nameless)

unknown = pycmd_pages.create("Other", "nosuchtemplate", workspace)
check("an unknown template is refused", not unknown.get("ok"), unknown)
check("and says so", "template" in unknown.get("error", ""), unknown)

python_page = pycmd_pages.create("Flask One", "python", workspace)
check("a Python page is made", python_page.get("ok"), python_page)
folder = python_page["page"]["folder"]
check("with an app.py", os.path.isfile(os.path.join(folder, "app.py")), folder)
check("and templates beside it",
      os.path.isfile(os.path.join(folder, "templates", "index.html")), folder)
plan = pycmd_servers.folder_plan(folder)
check("and the Servers tab knows how to run it",
      plan["how"] == "script" and plan["entry"] == "app.py", plan)

api_page = pycmd_pages.create("Api One", "api", workspace)
check("an API page is made", api_page.get("ok"), api_page)
empty_page = pycmd_pages.create("Empty One", "empty", workspace)
check("an empty page is made", empty_page.get("ok"), empty_page)
check("and it really is empty",
      os.listdir(empty_page["page"]["folder"]) == [], empty_page)

say("\n== the limits are the limits ==")
counted = pycmd_pages.counts()
check("counts report the ceiling", counted["max_projects"] == 70, counted)
check("and the running ceiling", counted["max_active"] == 25, counted)

held = pycmd_pages.MAX_PROJECTS
# Lowered to exactly what is there, so the next one is the one too many.
pycmd_pages.MAX_PROJECTS = len(pycmd_pages.listing())
over = pycmd_pages.create("One Too Many", "empty", workspace)
check("past the project limit it stops", not over.get("ok"), over)
check("and says what the limit is",
      f"{pycmd_pages.MAX_PROJECTS} pages" in over.get("error", ""), over)
pycmd_pages.MAX_PROJECTS = held

say("\n== renaming and removing ==")
renamed = pycmd_pages.rename(page["id"], "Renamed Site")
check("a page renames", renamed.get("ok") and renamed["page"]["name"] == "Renamed Site", renamed)
clash = pycmd_pages.rename(page["id"], "Flask One")
check("but not onto another page's name", not clash.get("ok"), clash)
missing = pycmd_pages.rename("nope", "Anything")
check("and not one that is not there", not missing.get("ok"), missing)

kept_folder = empty_page["page"]["folder"]
dropped = pycmd_pages.remove(empty_page["page"]["id"])
check("a page is removed", dropped.get("ok"), dropped)
check("and its folder is left alone by default", os.path.isdir(kept_folder), kept_folder)
check("the listing is shorter", all(row["id"] != empty_page["page"]["id"]
                                    for row in pycmd_pages.listing()),
      [row["name"] for row in pycmd_pages.listing()])

throwaway = pycmd_pages.create("Throwaway", "static", workspace)["page"]
gone = pycmd_pages.remove(throwaway["id"], delete_files=True)
check("and asked to, it deletes the folder too",
      gone.get("files_deleted") and not os.path.isdir(throwaway["folder"]), gone)

say("\n== running one, for real ==")
started = pycmd_pages.start(page["id"])
check("a page starts", started.get("ok"), started)
time.sleep(0.6)
live = next(row for row in pycmd_pages.listing() if row["id"] == page["id"])
check("the listing says it is running", live["running"], live)
check("and gives an address", live["url"].startswith("http://"), live)

port = live["port"]
fetched = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode()
check("and it really serves the page", "Renamed Site" in fetched or "<h1>" in fetched,
      fetched[:120])

double = pycmd_pages.start(page["id"])
check("starting it twice changes nothing", double.get("already"), double)

held_active = pycmd_pages.MAX_ACTIVE
pycmd_pages.MAX_ACTIVE = 1
blocked = pycmd_pages.start(python_page["page"]["id"])
check("past the running limit it stops", not blocked.get("ok"), blocked)
check("and says which limit", "1 pages" in blocked.get("error", ""), blocked)
pycmd_pages.MAX_ACTIVE = held_active

stopped = pycmd_pages.stop(page["id"])
check("a page stops", stopped.get("ok"), stopped)
time.sleep(0.4)
after = next(row for row in pycmd_pages.listing() if row["id"] == page["id"])
check("and the listing agrees", not after["running"], after)

say("\n== picking a folder out of the workspace ==")
os.makedirs(os.path.join(workspace, "notes", "drafts"), exist_ok=True)
os.makedirs(os.path.join(workspace, "__pycache__"), exist_ok=True)
os.makedirs(os.path.join(workspace, ".hidden"), exist_ok=True)
offered = pycmd_pages.folders(workspace)
paths = [row["relative"] for row in offered]
check("the picker offers folders in the workspace", "notes" in paths, paths[:8])
check("and one level inside them", "notes/drafts" in paths, paths[:8])
check("caches are left out", "__pycache__" not in paths, paths[:8])
check("and so are hidden folders", ".hidden" not in paths, paths[:8])
check("a folder that is already a page says so",
      any(row["taken"] for row in offered), offered[:4])
check("every row says how much is in it",
      all("files" in row and "bytes" in row for row in offered), offered[:2])

say("\n== adopting a folder that already exists ==")
hand_made = os.path.join(workspace, "by-hand")
os.makedirs(hand_made, exist_ok=True)
with open(os.path.join(hand_made, "index.html"), "w", encoding="utf-8") as handle:
    handle.write("<h1>by hand</h1>")
adopted = pycmd_pages.adopt("By Hand", hand_made)
check("a folder becomes a page", adopted.get("ok"), adopted)
twice = pycmd_pages.adopt("Again", hand_made)
check("but only once", not twice.get("ok"), twice)
nowhere = pycmd_pages.adopt("Nowhere", os.path.join(workspace, "not-there"))
check("and a folder that is not there is refused", not nowhere.get("ok"), nowhere)

say("\n== where a page is hosted ==")
set_host = pycmd_pages.set_host(page["id"], "cloudflare")
check("a page can be marked for Cloudflare", set_host.get("ok"), set_host)
bad_host = pycmd_pages.set_host(page["id"], "somewhere-else")
check("and nowhere else", not bad_host.get("ok"), bad_host)
noted = pycmd_pages.note_deployment(page["id"], "https://x.pages.dev", "x", 3, 900)
check("a deployment is remembered", noted.get("ok"), noted)
check("and shows on the card",
      next(r for r in pycmd_pages.listing() if r["id"] == page["id"])
      .get("deployed_url") == "https://x.pages.dev",
      pycmd_pages.listing()[0])

say("\n== a page's own storage, outside the workspace ==")
store = pycmd_pages.store_dir(page["id"])
check("a page has a folder of its own", os.path.isdir(store), store)
check("and it is nowhere near the workspace",
      not store.startswith(workspace), store)

history = pycmd_pages.deployments(page["id"])
check("the deployment went into it", len(history["deployments"]) == 1, history)
check("with what was sent",
      history["deployments"][0]["files"] == 3 and
      history["deployments"][0]["bytes"] == 900,
      history["deployments"][0])

pycmd_pages.note_deployment(page["id"], "https://y.pages.dev", "y", 4, 1000)
history = pycmd_pages.deployments(page["id"])
check("the newest deployment is first",
      history["deployments"][0]["url"] == "https://y.pages.dev", history["deployments"][0])

staged = pycmd_pages.stage(page["id"])
check("a page can be packed for deployment", staged.get("ok"), staged)
check("the copy is in the page's own folder",
      staged.get("folder", "").startswith(store), staged)
check("and carries its files",
      os.path.isfile(os.path.join(staged["folder"], "index.html")), staged)
check("and it is not in the workspace",
      not staged.get("folder", "").startswith(workspace), staged)

junk = os.path.join(page["folder"], "__pycache__")
os.makedirs(junk, exist_ok=True)
with open(os.path.join(junk, "x.pyc"), "wb") as handle:
    handle.write(b"\0")
with open(os.path.join(page["folder"], ".hidden"), "w", encoding="utf-8") as handle:
    handle.write("x")
restaged = pycmd_pages.stage(page["id"])
check("caches are left out of the copy",
      not os.path.isdir(os.path.join(restaged["folder"], "__pycache__")), restaged)
check("and so are hidden files",
      not os.path.isfile(os.path.join(restaged["folder"], ".hidden")), restaged)

cleared = pycmd_pages.clear_build(page["id"])
check("the copy can be thrown away", cleared.get("ok") and cleared.get("freed", 0) > 0, cleared)
check("and it is gone", not os.path.isdir(restaged["folder"]), restaged)
check("but the history stayed",
      len(pycmd_pages.deployments(page["id"])["deployments"]) == 2)

empty_folder = os.path.join(workspace, "nothing-here")
os.makedirs(empty_folder, exist_ok=True)
empty_page_row = pycmd_pages.adopt("Nothing Here", empty_folder)["page"]
check("packing an empty folder is refused, not silently empty",
      not pycmd_pages.stage(empty_page_row["id"]).get("ok"),
      pycmd_pages.stage(empty_page_row["id"]))
check("and no half-made copy is left behind",
      not os.path.isdir(os.path.join(pycmd_pages.store_dir(empty_page_row["id"]), "build")))
gone_store = pycmd_pages.store_dir(empty_page_row["id"])
pycmd_pages.remove(empty_page_row["id"], False)
check("removing a page takes its own folder with it",
      not os.path.isdir(gone_store), gone_store)

# ---------------------------------------------------------------------------
say("\n== the tunnel, against a stand-in service ==")


class _Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b"<h1>from the phone</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # noqa: A003
        pass


class _Quiet(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


local_page = _Quiet(("127.0.0.1", 0), _Page)
threading.Thread(target=local_page.serve_forever, daemon=True).start()
local_port = local_page.server_address[1]

# The relay port the "service" tells the client to dial.
relay = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
relay.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
relay.bind(("127.0.0.1", 0))
relay.listen(8)
relay_port = relay.getsockname()[1]
handshakes = []


class _Service(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        handshakes.append(self.path)
        if self.path.startswith("/?new"):
            body = json.dumps({
                "id": "made-up-name",
                "port": relay_port,
                "max_conn_count": 2,
                "url": "https://made-up-name.loca.lt",
            }).encode()
            self.send_response(200)
        else:
            body = b"{}"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # noqa: A003
        pass


service = _Quiet(("127.0.0.1", 0), _Service)
threading.Thread(target=service.serve_forever, daemon=True).start()
pycmd_tunnel.point_at(f"http://127.0.0.1:{service.server_address[1]}")

opened = pycmd_tunnel.open_tunnel("test-page", local_port)
check("a tunnel opens", opened.get("ok"), opened)
check("and hands back the public URL", opened.get("url") == "https://made-up-name.loca.lt", opened)
check("the service was asked for a new one", handshakes and handshakes[0].startswith("/?new"),
      handshakes)

# Play the part of a visitor: the service pipes their bytes down a relay.
relay.settimeout(10)
visitor, _who = relay.accept()
visitor.sendall(b"GET / HTTP/1.1\r\nHost: made-up-name.loca.lt\r\n\r\n")
visitor.settimeout(10)
answer = b""
deadline = time.time() + 10
while b"</h1>" not in answer and time.time() < deadline:
    try:
        chunk = visitor.recv(4096)
    except socket.timeout:
        break
    if not chunk:
        break
    answer += chunk
check("a visitor's request reaches the page", b"from the phone" in answer, answer[:200])
check("with the page's own status line", answer.startswith(b"HTTP/1.0 200")
      or answer.startswith(b"HTTP/1.1 200"), answer[:40])
visitor.close()

state = pycmd_tunnel.status("test-page")
check("the tunnel counts what it served", state["served"] >= 1, state)
check("and reports itself alive", state["alive"], state)

closed = pycmd_tunnel.close("test-page")
check("a tunnel closes", closed.get("ok"), closed)
check("and is gone from the list", not pycmd_tunnel.listing(), pycmd_tunnel.listing())

pycmd_tunnel.point_at("http://127.0.0.1:1")
refused = pycmd_tunnel.open_tunnel("nowhere", local_port)
check("a service that is not there is a sentence, not a crash",
      not refused.get("ok") and "tunnel service" in refused.get("error", ""), refused)
check("https is required of a real service",
      not pycmd_tunnel.point_at("http://example.com").get("ok"),
      pycmd_tunnel.point_at("http://example.com"))
pycmd_tunnel.point_at("")
check("and the default comes back", pycmd_tunnel.SERVICE == pycmd_tunnel.DEFAULT_SERVICE,
      pycmd_tunnel.SERVICE)

# ---------------------------------------------------------------------------
say("\n== Cloudflare, against a stand-in API ==")

sent = {"uploads": [], "deployments": [], "workers": [], "auth": []}


class _Cloudflare(http.server.BaseHTTPRequestHandler):
    def _reply(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        return self.rfile.read(length) if length else b""

    def do_GET(self):  # noqa: N802
        sent["auth"].append(self.headers.get("Authorization", ""))
        if self.path.endswith("/upload-token"):
            self._reply({"success": True, "result": {"jwt": "an-upload-token"}})
        elif self.path.endswith("/pages/projects"):
            self._reply({"success": True, "result": [
                {"name": "already-there", "subdomain": "already-there.pages.dev"},
            ]})
        elif "/deployments" in self.path:
            self._reply({"success": True, "result": [
                {"id": "dep1", "url": "https://dep1.pages.dev",
                 "latest_stage": {"status": "success"}},
            ]})
        elif "/workers/scripts" in self.path:
            self._reply({"success": True, "result": [{"id": "hello"}]})
        elif self.path.startswith("/accounts/"):
            if "bad-account" in self.path:
                self._reply({"success": False, "errors": [
                    {"message": "Invalid account identifier"},
                ]}, code=400)
            else:
                self._reply({"success": True, "result": {"id": "acct", "name": "A Test Account"}})
        else:
            self._reply({"success": False, "errors": [{"message": "no such path"}]}, code=404)

    def do_POST(self):  # noqa: N802
        body = self._read()
        if self.path.endswith("/check-missing"):
            asked = json.loads(body)
            # Say one of them is already there, so the client has to upload
            # fewer files than it hashed.
            self._reply({"success": True, "result": asked["hashes"][1:]})
        elif self.path.endswith("/assets/upload"):
            sent["uploads"].append(json.loads(body))
            self._reply({"success": True, "result": {}})
        elif self.path.endswith("/deployments"):
            sent["deployments"].append(body.decode("utf-8", "replace"))
            self._reply({"success": True, "result": {
                "id": "dep2", "url": "https://my-page.pages.dev",
            }})
        elif self.path.endswith("/pages/projects"):
            made = json.loads(body)
            if made.get("name") == "taken":
                self._reply({"success": False, "errors": [
                    {"message": "A project with this name already exists"},
                ]}, code=409)
            else:
                self._reply({"success": True, "result": {
                    "name": made.get("name"), "subdomain": made.get("name") + ".pages.dev",
                }})
        else:
            self._reply({"success": False, "errors": [{"message": "no such path"}]}, code=404)

    def do_PUT(self):  # noqa: N802
        sent["workers"].append(self._read().decode("utf-8", "replace"))
        self._reply({"success": True, "result": {"id": self.path.rsplit("/", 1)[-1]}})

    def log_message(self, *args):  # noqa: A003
        pass


cloudflare = _Quiet(("127.0.0.1", 0), _Cloudflare)
threading.Thread(target=cloudflare.serve_forever, daemon=True).start()
pycmd_cloudflare.point_at(f"http://127.0.0.1:{cloudflare.server_address[1]}")
pycmd_cloudflare.configure_storage(tempfile.mkdtemp(prefix="pycmd-cf-"))

check("nothing is connected to begin with",
      pycmd_cloudflare.state()["connected"] is False, pycmd_cloudflare.state())

half = pycmd_cloudflare.connect("", "a-token")
check("an account with no id is refused", not half.get("ok"), half)

bad = pycmd_cloudflare.connect("bad-account", "a-token")
check("a token that cannot see the account is refused", not bad.get("ok"), bad)
check("with Cloudflare's own words", "Invalid account" in bad.get("error", ""), bad)
check("and nothing is remembered from it",
      pycmd_cloudflare.state()["connected"] is False, pycmd_cloudflare.state())

joined = pycmd_cloudflare.connect("acct", "cf-token-abcd")
check("a good account connects", joined.get("ok"), joined)
check("and is remembered", pycmd_cloudflare.state()["connected"], pycmd_cloudflare.state())
check("but the token is never handed back",
      "cf-token-abcd" not in json.dumps(pycmd_cloudflare.state()), pycmd_cloudflare.state())
check("only its last four characters",
      pycmd_cloudflare.state()["token_tail"] == "abcd", pycmd_cloudflare.state())
check("the token went in the header", any("Bearer cf-token-abcd" == value
                                          for value in sent["auth"]), sent["auth"][:2])

listed = pycmd_cloudflare.projects()
check("projects are listed", listed.get("ok") and listed["projects"], listed)

taken = pycmd_cloudflare.create_project("taken")
check("a name already in use is not an error", taken.get("ok") and taken.get("existed"), taken)

site = os.path.join(workspace, "to-deploy")
os.makedirs(os.path.join(site, "assets"), exist_ok=True)
with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as handle:
    handle.write("<h1>deployed</h1>")
with open(os.path.join(site, "assets", "style.css"), "w", encoding="utf-8") as handle:
    handle.write("body { color: red }")
with open(os.path.join(site, ".DS_Store"), "w", encoding="utf-8") as handle:
    handle.write("junk")
os.makedirs(os.path.join(site, "__pycache__"), exist_ok=True)
with open(os.path.join(site, "__pycache__", "x.pyc"), "w", encoding="utf-8") as handle:
    handle.write("junk")

deployed = pycmd_cloudflare.deploy_folder(site, "My Page!")
check("a folder deploys", deployed.get("ok"), deployed)
check("and comes back with the address", deployed.get("url") == "https://my-page.pages.dev",
      deployed)
check("the project name is made legal", deployed.get("project") == "my-page", deployed)
check("junk is not uploaded", deployed.get("files") == 2, deployed)
check("and only what Cloudflare was missing", deployed.get("uploaded") == 1, deployed)
check("the upload carried the file itself",
      sent["uploads"] and sent["uploads"][0][0].get("base64") is True, sent["uploads"][:1])
check("with its content type",
      "text/" in sent["uploads"][0][0]["metadata"]["contentType"], sent["uploads"][:1])

manifest_body = sent["deployments"][0]
check("the deployment carries a manifest", '"manifest"' in manifest_body, manifest_body[:200])
check("with web paths, not phone paths", '/index.html' in manifest_body, manifest_body[:400])
check("and no backslashes in them", "\\\\" not in manifest_body, manifest_body[:400])

history = pycmd_cloudflare.deployments("my-page")
check("past deployments are listed", history.get("ok") and history["deployments"], history)

published = pycmd_cloudflare.put_worker("hello worker",
                                        pycmd_cloudflare.WORKER_TEMPLATE)
check("a Worker publishes", published.get("ok"), published)
check("its script was sent", "Hello from PyCmd" in sent["workers"][0], sent["workers"][0][:120])
check("as a module", "main_module" in sent["workers"][0], sent["workers"][0][:200])
empty_worker = pycmd_cloudflare.put_worker("empty", "   ")
check("an empty Worker is refused", not empty_worker.get("ok"), empty_worker)

listed_workers = pycmd_cloudflare.workers()
check("Workers are listed", listed_workers.get("ok"), listed_workers)

forgotten = pycmd_cloudflare.forget()
check("the account can be forgotten", forgotten["connected"] is False, forgotten)
after_forget = pycmd_cloudflare.projects()
check("and then nothing talks to Cloudflare",
      not after_forget.get("ok") and "connected" in after_forget.get("error", ""), after_forget)

pycmd_pages.stop_all()
pycmd_servers.kill_all()
cloudflare.shutdown()
service.shutdown()
local_page.shutdown()
relay.close()

say()
if FAILURES:
    say(f"{len(FAILURES)} pages checks failed")
    sys.exit(1)
say("all pages checks passed")
