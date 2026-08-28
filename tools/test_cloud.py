"""Checks the Supabase and Firebase clients against a stand-in for each service.

Neither real service can be reached from a test run, and a client that is only
"probably right" is worse than no client - so a local HTTP server plays both of
them: it records exactly what was sent, and answers the way the real API does.
That is what makes the URL shapes, the filter syntax and Firestore's typed
values checkable rather than hopeful.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import pycmd_cloud as cloud  # noqa: E402

FAILURES = []
SEEN = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


class Handler(BaseHTTPRequestHandler):
    """Answers like whichever service the path belongs to."""

    def log_message(self, *args):
        pass

    def _record(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
        except (ValueError, UnicodeDecodeError):
            body = raw
        entry = {
            "method": self.command,
            "path": self.path,
            # urllib title-cases what it sends, so the lookup cannot be
            # case-sensitive without testing urllib rather than the client.
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": body,
        }
        SEEN.append(entry)
        return entry

    def _send(self, payload, status=200, extra=None):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _answer(self):
        entry = self._record()
        path = entry["path"]

        if "/rest/v1/rpc/" in path:
            return self._send({"called": path.rsplit("/", 1)[-1]})
        if "range" in entry["headers"] and "/rest/v1/" in path:
            return self._send([{"id": 1}], extra={"Content-Range": "0-0/42"})
        if "/rest/v1/" in path:
            if entry["method"] == "GET" and "vnd.pgrst.object" in entry["headers"].get("accept", ""):
                return self._send({"id": 1, "text": "one"})
            if entry["method"] == "GET":
                return self._send([{"id": 1, "text": "one"}, {"id": 2, "text": "two"}])
            return self._send([{"id": 3, "ok": True}])
        if "/auth/v1/admin/users" in path:
            return self._send([{"id": "u1", "email": "a@b.c"}])
        if "/auth/v1/token" in path or "/auth/v1/signup" in path:
            return self._send({
                "access_token": "at-123", "refresh_token": "rt-456",
                "user": {"email": "a@b.c", "id": "u1"},
            })
        if "/auth/v1/user" in path:
            return self._send({"id": "u1", "email": "a@b.c"})
        if "/storage/v1/bucket" in path:
            return self._send([{"name": "media", "public": True}])
        if "/storage/v1/object/sign/" in path:
            return self._send({"signedURL": "/object/sign/media/a.txt?token=xyz"})
        if "/storage/v1/object/" in path and entry["method"] == "GET":
            return self._send(b"file-bytes")
        if "/storage/v1/object" in path:
            return self._send({"Key": "media/a.txt"})

        # ---- Firebase ----
        if ":runQuery" in path:
            return self._send([
                {"document": {"name": "p/d/documents/notes/n1",
                              "fields": {"text": {"stringValue": "hi"},
                                         "done": {"booleanValue": False}}}},
                {"readTime": "2024-01-01T00:00:00Z"},
            ])
        if ":batchGet" in path:
            return self._send([
                {"found": {"name": "p/d/documents/notes/n1",
                           "fields": {"text": {"stringValue": "hi"}}}},
            ])
        if "/documents/" in path or path.rstrip("/").endswith("/documents"):
            if entry["method"] == "DELETE":
                return self._send({})
            if entry["method"] == "GET" and "pageSize" in path:
                return self._send({"documents": [
                    {"name": "p/d/documents/notes/n1",
                     "fields": {"text": {"stringValue": "hi"}, "n": {"integerValue": "7"}}},
                ]})
            return self._send({
                "name": "p/d/documents/notes/n1",
                "fields": (entry["body"] or {}).get("fields", {"text": {"stringValue": "hi"}}),
                "createTime": "2024-01-01T00:00:00Z",
            })
        if "identitytoolkit" in path or ":signUp" in path or ":signInWithPassword" in path:
            return self._send({"idToken": "id-1", "refreshToken": "re-1", "email": "a@b.c"})
        if path.endswith(".json") or ".json?" in path:
            if entry["method"] == "GET":
                return self._send({"a": 1, "b": 2})
            return self._send({"name": "-Nkey123"})
        if "/v0/b/" in path:
            if entry["method"] == "GET" and "alt=media" in path:
                return self._send(b"stored-bytes")
            return self._send({"name": "a.txt", "bucket": "b"})

        return self._send({"error": {"message": "no route"}}, 404)

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _answer


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"

scratch = tempfile.mkdtemp(prefix="pycmd-cloud-")
cloud.configure_storage(scratch)


def last(match: str):
    """The most recent request whose path contains `match`."""
    for entry in reversed(SEEN):
        if match in entry["path"]:
            return entry
    return None


print("\n== saving the keys ==")
cloud.configure("supabase", url=BASE, key="anon-key", service_key="service-key")
check("settings round-trip", cloud.settings()["supabase"]["url"] == BASE, cloud.settings())
masked = cloud.status()["supabase"]
check("status says it is configured", masked["configured"] is True, masked)
check("and never shows the whole key", "anon-key" not in json.dumps(masked), masked)

print("\n== supabase: reading a table ==")
sb = cloud.supabase()
rows = sb.table("notes").select("id,text").eq("done", False).order("id").limit(5).run()
check("rows come back", len(rows) == 2, rows)
sent = last("/rest/v1/notes")
check("the filter is PostgREST's own syntax", "done=eq.false" in sent["path"], sent["path"])
check("select is passed through", "select=id%2Ctext" in sent["path"], sent["path"])
check("so are order and limit",
      "order=id.asc" in urllib.parse.unquote(sent["path"]) and "limit=5" in sent["path"],
      sent["path"])
check("the anon key is sent", sent["headers"].get("apikey") == "anon-key", sent["headers"])

one = sb.table("notes").eq("id", 1).single().run()
check("single() returns one row, not a list", isinstance(one, dict), one)
check("asking for it uses the object header",
      "vnd.pgrst.object" in last("/rest/v1/notes")["headers"].get("accept", ""))

print("\n== supabase: writing ==")
sb.insert("notes", {"text": "new"})
sent = last("/rest/v1/notes")
check("insert posts the row", sent["method"] == "POST" and sent["body"]["text"] == "new", sent)
check("and asks for the row back", "return=representation" in sent["headers"].get("prefer", ""))
sb.upsert("notes", {"id": 1, "text": "changed"})
check("upsert says merge-duplicates",
      "merge-duplicates" in last("/rest/v1/notes")["headers"].get("prefer", ""))
sb.update("notes", {"text": "edited"}, id=1)
sent = last("/rest/v1/notes")
check("update patches the matching rows",
      sent["method"] == "PATCH" and "id=eq.1" in sent["path"], sent)
sb.delete("notes", id=2)
sent = last("/rest/v1/notes")
check("delete filters too", sent["method"] == "DELETE" and "id=eq.2" in sent["path"], sent)

total = sb.table("notes").gt("id", 0).count()
check("count reads the Content-Range total", total == 42, total)

sb.rpc("do_thing", {"a": 1})
check("rpc posts to the function", last("/rpc/do_thing") is not None)

print("\n== supabase: auth ==")
session = sb.auth.sign_in("a@b.c", "secret")
check("signing in returns a session", session["access_token"] == "at-123", session)
check("and it is remembered for next time",
      cloud.settings()["supabase"]["access_token"] == "at-123")
check("the client now sends the user's token, not the anon key",
      cloud.supabase().headers()["Authorization"] == "Bearer at-123")
sb.auth.user()
check("the user endpoint is authorised",
      last("/auth/v1/user")["headers"].get("authorization") == "Bearer at-123")
sb.auth.admin_list_users()
check("admin calls use the service key",
      last("/admin/users")["headers"].get("apikey") == "service-key")
sb.auth.sign_out()
check("signing out forgets the token",
      not cloud.settings()["supabase"].get("access_token"), cloud.settings())

print("\n== supabase: storage ==")
sb = cloud.supabase()
sb.storage.upload("media", "a.txt", "hello")
sent = last("/storage/v1/object/media/a.txt")
check("upload sends the bytes", sent["body"] == b"hello", sent["body"])
check("with a guessed content type",
      sent["headers"].get("content-type") == "text/plain", sent["headers"])
data = sb.storage.download("media", "a.txt")
check("download returns bytes", data == b"file-bytes", data)
target = os.path.join(scratch, "out.txt")
sb.storage.download_to("media", "a.txt", target)
check("download_to writes the file", open(target, "rb").read() == b"file-bytes")
signed = sb.storage.signed_url("media", "a.txt")
check("a signed URL is absolute", signed.startswith(BASE), signed)
check("public_url points at the public route",
      sb.storage.public_url("media", "a.txt").endswith("/object/public/media/a.txt"))

print("\n== firebase: typed values both ways ==")
original = {
    "text": "hi", "n": 7, "pi": 1.5, "done": False, "nothing": None,
    "tags": ["a", "b"], "nested": {"deep": {"x": 1}},
}
encoded = {k: cloud._to_firestore(v) for k, v in original.items()}
check("integers are sent as strings, as Firestore requires",
      encoded["n"] == {"integerValue": "7"}, encoded["n"])
check("floats are not", encoded["pi"] == {"doubleValue": 1.5}, encoded["pi"])
check("null is a value, not a missing key", encoded["nothing"] == {"nullValue": None})
check("lists become arrayValue",
      encoded["tags"]["arrayValue"]["values"][0] == {"stringValue": "a"}, encoded["tags"])
check("dicts nest as mapValue",
      encoded["nested"]["mapValue"]["fields"]["deep"]["mapValue"]["fields"]["x"]
      == {"integerValue": "1"}, encoded["nested"])
decoded = {k: cloud._from_firestore(v) for k, v in encoded.items()}
check("and everything survives the round trip", decoded == original, decoded)

print("\n== firebase: firestore ==")
cloud.configure("firebase", project_id="proj", api_key="web-key",
                database_url=BASE, storage_bucket="proj.appspot.com")
fb = cloud.firebase()
# Point the document API at the stand-in rather than Google.
Firestore = type(fb.firestore)
Firestore._base = property(lambda self: f"{BASE}/v1/projects/proj/databases/(default)/documents")
FirebaseAuth = type(fb.auth)
FirebaseAuth.BASE = f"{BASE}/v1/accounts"
FirebaseStorage = type(fb.storage)
FirebaseStorage._base = lambda self: f"{BASE}/v0/b/proj.appspot.com/o"

doc = fb.firestore.set("notes/n1", {"text": "hi", "n": 7})
check("set writes typed fields",
      last("/documents/notes/n1")["body"]["fields"]["n"] == {"integerValue": "7"},
      last("/documents/notes/n1")["body"])
check("and reads back as plain Python", doc["text"] == "hi" and doc["n"] == 7, doc)
check("with the document id kept", doc["_id"] == "n1", doc)

fb.firestore.update("notes/n1", {"text": "changed"})
sent = last("/documents/notes/n1")
check("update sends a field mask",
      "updateMask.fieldPaths=text" in urllib.parse.unquote(sent["path"]), sent["path"])

fb.firestore.create("notes", {"text": "new"}, document_id="n2")
check("create names the document", "documentId=n2" in last("/documents/notes")["path"])

listed = fb.firestore.list("notes", page_size=10)
check("list flattens the documents", listed[0]["text"] == "hi" and listed[0]["n"] == 7, listed)

found = fb.firestore.query("notes", where=[("done", "==", False)], order_by="text", limit=3)
sent = last(":runQuery")
where = sent["body"]["structuredQuery"]["where"]["fieldFilter"]
check("a single filter is not wrapped in a composite", where["op"] == "EQUAL", where)
check("the value is typed", where["value"] == {"booleanValue": False}, where)
check("order and limit are sent",
      sent["body"]["structuredQuery"]["orderBy"][0]["field"]["fieldPath"] == "text"
      and sent["body"]["structuredQuery"]["limit"] == 3, sent["body"])
check("and readTime entries are skipped", len(found) == 1, found)

fb.firestore.query("notes", where=[("done", "==", False), ("n", ">", 3)])
composite = last(":runQuery")["body"]["structuredQuery"]["where"]["compositeFilter"]
check("two filters become an AND", composite["op"] == "AND" and len(composite["filters"]) == 2)
check("shorthand operators are translated",
      composite["filters"][1]["fieldFilter"]["op"] == "GREATER_THAN", composite)

got = fb.firestore.batch_get(["notes/n1"])
check("batch_get flattens what it found", got[0]["text"] == "hi", got)

fb.firestore.delete("notes/n1")
check("delete is a DELETE", last("/documents/notes/n1")["method"] == "DELETE")

print("\n== firebase: auth ==")
session = fb.auth.sign_in("a@b.c", "secret")
check("signing in returns a token", session["idToken"] == "id-1", session)
check("which is saved", cloud.settings()["firebase"]["id_token"] == "id-1")
check("and used by firestore afterwards",
      cloud.firebase().firestore._headers()["Authorization"] == "Bearer id-1")
fb.auth.sign_out()
check("signing out forgets it", not cloud.settings()["firebase"].get("id_token"))

print("\n== firebase: realtime database ==")
fb = cloud.firebase()
value = fb.rtdb.get("rooms")
check("get returns the JSON", value == {"a": 1, "b": 2}, value)
check("the path becomes a .json URL", last("/rooms.json") is not None)
fb.rtdb.push("rooms", {"name": "new"})
check("push posts", last("/rooms.json")["method"] == "POST")
fb.rtdb.update("rooms/a", {"name": "x"})
check("update patches", last("/rooms/a.json")["method"] == "PATCH")
fb.rtdb.query("rooms", order_by="name", limit_to_first=5, equal_to="x")
sent = urllib.parse.unquote(last("/rooms.json")["path"])
check("query sends JSON-quoted parameters",
      'orderBy="name"' in sent and "limitToFirst=5" in sent and 'equalTo="x"' in sent, sent)
fb.rtdb.delete("rooms/a")
check("delete is a DELETE", last("/rooms/a.json")["method"] == "DELETE")

print("\n== firebase: storage ==")
fb.storage.upload("pics/a.png", b"\x89PNG")
sent = last("/v0/b/")
check("upload names the object", "name=pics%2Fa.png" in sent["path"], sent["path"])
check("and guesses the type", sent["headers"].get("content-type") == "image/png", sent["headers"])
check("download returns bytes", fb.storage.download("pics/a.png") == b"stored-bytes")

print("\n== failures are explained, not swallowed ==")
try:
    cloud._request("GET", f"{BASE}/nope/missing", {})
    check("a 404 raises", False, "no exception")
except cloud.CloudError as error:
    check("a 404 raises", True)
    check("with the status", error.status == 404, error.status)
    check("and the service's own message", "no route" in str(error), str(error))

try:
    cloud.Supabase("", "")
    check("a missing URL is refused", False)
except cloud.CloudError as error:
    check("a missing URL is refused", "project URL" in str(error), str(error))

cloud.configure("supabase", url=BASE, key="anon-key", service_key=None)
try:
    cloud.supabase().service_headers()
    check("an admin call without the service key is refused", False, "no exception")
except cloud.CloudError as error:
    check("an admin call without the service key is refused",
          "service key" in str(error), str(error))

cloud.forget()
check("forgetting clears everything", cloud.settings() == {}, cloud.settings())

server.shutdown()
print()
if FAILURES:
    print(f"{len(FAILURES)} cloud checks failed")
    sys.exit(1)
print("all cloud checks passed")
