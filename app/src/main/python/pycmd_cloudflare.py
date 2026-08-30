"""Cloudflare Pages and Workers, from the phone.

A tunnel gives a page a random address that lasts as long as the app is open.
That is the right answer for showing somebody what you just built and the wrong
one for anything you want to *keep*. This is the other door: upload the page to
Cloudflare and it gets a real address, served by them, up when the phone is
not.

Everything here is the public REST API over plain HTTPS - no wrangler, no Node,
no CLI, because none of those exist on Android. Three flows are covered:

* **Pages, direct upload.** Ask for an upload token, tell Cloudflare which file
  hashes it is missing, upload those, then create a deployment from a manifest
  of path to hash. That is what `wrangler pages deploy` does underneath.
* **Workers.** One PUT with the script. A Worker is a file, so this is a file
  upload with a content type.
* **Reading back.** Projects, deployments and the account itself, so the app
  can show what is there rather than asking the user to remember.

## The token

Cloudflare's own advice, and this app's: use a **scoped API token**, not the
Global API Key. A token can be given "Cloudflare Pages: Edit" and
"Workers Scripts: Edit" on one account and nothing else, and revoked on its own
when a phone is lost. The Global Key is every permission on every zone and
cannot be scoped or revoked separately, which is a great deal of power to keep
on a device that lives in a pocket.

Either works here. The token is kept in the app's private storage, never in the
workspace, and is never handed back to the UI whole - only its last four
characters, so you can tell which one is loaded.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

__all__ = [
    "configure_storage",
    "connect",
    "forget",
    "state",
    "verify",
    "projects",
    "create_project",
    "deploy_folder",
    "deployments",
    "put_worker",
    "workers",
]

DEFAULT_API = "https://api.cloudflare.com/client/v4"
API = DEFAULT_API

TIMEOUT = 45

# Cloudflare Pages' own ceiling per file, and a sane one for a phone's upload.
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES = 2000

# Files that have no business on a website, skipped rather than uploaded.
SKIP_NAMES = {".DS_Store", "Thumbs.db", "pages.json", "installed.json"}
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".idea", "venv", ".venv"}

_store = ""
_account = ""
_token = ""


def point_at(api: str = "") -> dict:
    """Uses a different API base. For tests, and for nothing else."""
    global API

    api = (api or "").strip().rstrip("/")
    if not api:
        API = DEFAULT_API
        return {"ok": True, "api": API}
    local = api.startswith("http://127.0.0.1") or api.startswith("http://localhost")
    if not local and not api.startswith("https://"):
        return {"ok": False, "error": "the API base has to be https"}
    API = api
    return {"ok": True, "api": API}


# ---------------------------------------------------------------------------
# The account
# ---------------------------------------------------------------------------


def configure_storage(directory: str) -> str:
    """Where the token is kept. The app's private storage, never the workspace."""
    global _store

    _store = os.path.abspath(directory)
    os.makedirs(_store, exist_ok=True)
    _load()
    return _store


def _path() -> str:
    return os.path.join(_store or ".", "cloudflare.json")


def _load() -> None:
    global _account, _token

    try:
        with open(_path(), "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        _account = saved.get("account", "")
        _token = saved.get("token", "")
    except (OSError, ValueError):
        _account, _token = "", ""


def _save() -> None:
    if not _store:
        return
    try:
        with open(_path(), "w", encoding="utf-8") as handle:
            json.dump({"account": _account, "token": _token}, handle)
        os.chmod(_path(), 0o600)
    except OSError:
        pass


def connect(account_id: str, token: str) -> dict:
    """Remembers an account and a token, after checking they work together."""
    global _account, _token

    account_id = (account_id or "").strip()
    token = (token or "").strip()
    if not account_id or not token:
        return {"ok": False, "error": "Both the account id and the token are needed."}

    was = (_account, _token)
    _account, _token = account_id, token
    checked = verify()
    if not checked.get("ok"):
        _account, _token = was
        return checked
    _save()
    return {"ok": True, **state()}


def forget() -> dict:
    """Removes the token from this device."""
    global _account, _token

    _account, _token = "", ""
    try:
        os.remove(_path())
    except OSError:
        pass
    return {"ok": True, **state()}


def state() -> dict:
    """What is connected, without ever handing the token back."""
    return {
        "connected": bool(_account and _token),
        "account": _account,
        "token_tail": _token[-4:] if len(_token) >= 4 else "",
    }


# ---------------------------------------------------------------------------
# Talking to the API
# ---------------------------------------------------------------------------


class CloudflareError(Exception):
    """An error Cloudflare itself reported, with their message in it."""


def _headers(extra: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {_token}",
        "User-Agent": "PyCmd",
        "Accept": "application/json",
    }
    headers.update(extra or {})
    return headers


def _call(method: str, path: str, body=None, headers=None, raw: bytes = b"") -> dict:
    """One API call. Returns the `result`, or raises with Cloudflare's message."""
    if not _token:
        raise CloudflareError("No Cloudflare account is connected.")

    url = path if path.startswith("http") else f"{API}{path}"
    data = raw
    sending = dict(headers or {})
    if body is not None and not raw:
        data = json.dumps(body).encode("utf-8")
        sending.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(url, data=data or None, method=method,
                                     headers=_headers(sending))
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", "replace")
        raise CloudflareError(_explain(text, error.code)) from error
    except urllib.error.URLError as error:
        raise CloudflareError(f"Could not reach Cloudflare: {error.reason}") from error

    try:
        payload = json.loads(text)
    except ValueError as error:
        raise CloudflareError("Cloudflare answered with something that is not JSON.") from error

    if not payload.get("success", True):
        raise CloudflareError(_explain(text, 200))
    return payload.get("result", payload)


def _explain(text: str, code: int) -> str:
    """Cloudflare's own words where there are any, and the status where not."""
    try:
        payload = json.loads(text)
    except ValueError:
        return f"Cloudflare returned HTTP {code}."
    messages = [row.get("message", "") for row in payload.get("errors", []) if row.get("message")]
    if messages:
        return "; ".join(messages)
    return f"Cloudflare returned HTTP {code}."


def verify() -> dict:
    """Checks the token can see the account it was given."""
    try:
        result = _call("GET", f"/accounts/{urllib.parse.quote(_account)}")
    except CloudflareError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "account": result.get("name", _account), "id": result.get("id", _account)}


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def projects() -> dict:
    """Every Pages project on the account."""
    try:
        rows = _call("GET", f"/accounts/{urllib.parse.quote(_account)}/pages/projects")
    except CloudflareError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "projects": [
        {
            "name": row.get("name", ""),
            "subdomain": row.get("subdomain", ""),
            "domains": row.get("domains", []),
            "created": row.get("created_on", ""),
        }
        for row in (rows or [])
    ]}


def create_project(name: str, branch: str = "main") -> dict:
    """Makes a direct-upload project, or reports the one already there."""
    name = _project_name(name)
    try:
        result = _call("POST", f"/accounts/{urllib.parse.quote(_account)}/pages/projects",
                       {"name": name, "production_branch": branch})
    except CloudflareError as error:
        message = str(error).lower()
        if "already" in message or "unique" in message or "exists" in message:
            return {"ok": True, "name": name, "existed": True}
        return {"ok": False, "error": str(error)}
    return {"ok": True, "name": result.get("name", name),
            "subdomain": result.get("subdomain", "")}


def _project_name(name: str) -> str:
    """Cloudflare's rules: lowercase letters, digits and dashes, 58 max."""
    cleaned = "".join(c if c.isalnum() else "-" for c in str(name).lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:58] or "pycmd-page"


def _collect(folder: str) -> list:
    """Every file that belongs on a website, with its hash and content type."""
    found = []
    for walk, folders, names in os.walk(folder):
        folders[:] = [d for d in folders if d not in SKIP_DIRS and not d.startswith(".")]
        for name in sorted(names):
            if name in SKIP_NAMES or name.startswith("."):
                continue
            full = os.path.join(walk, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                continue
            relative = os.path.relpath(full, folder).replace(os.sep, "/")
            found.append({"path": "/" + relative, "full": full, "size": size})
            if len(found) >= MAX_FILES:
                return found
    return found


def _hash_of(path: str, content_type: str) -> str:
    """Cloudflare's file id: the blake3 of content plus extension, in their client.

    Their API only requires that the id is stable, 32 hex characters, and the
    same one used in the manifest and the upload - it is a key, not a checksum
    they recompute. MD5 of the bytes and the extension gives exactly that, and
    is in the standard library, which blake3 is not.
    """
    digest = hashlib.md5()  # noqa: S324 - an id, not a security check
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    digest.update(content_type.encode("utf-8"))
    return digest.hexdigest()[:32]


def deploy_folder(folder: str, project: str, branch: str = "main", on_progress=None) -> dict:
    """Uploads a folder to Cloudflare Pages and makes it live.

    The flow is wrangler's, because it is the only one the API supports for a
    direct-upload project: a token for the asset endpoints, a list of what
    Cloudflare is missing, the upload of those, then a deployment built from a
    manifest of path to id.
    """
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        return {"ok": False, "error": "That folder is not there."}

    def say(message: str) -> None:
        if on_progress is not None:
            try:
                on_progress.onProgress(message)
            except Exception:  # noqa: BLE001 - progress must never break a deploy
                pass

    name = _project_name(project)
    made = create_project(name, branch)
    if not made.get("ok"):
        return made

    files = _collect(folder)
    if not files:
        return {"ok": False, "error": "There is nothing in that folder to upload."}

    say(f"Hashing {len(files)} files...")
    manifest = {}
    by_hash = {}
    for row in files:
        content_type = mimetypes.guess_type(row["path"])[0] or "application/octet-stream"
        key = _hash_of(row["full"], content_type)
        manifest[row["path"]] = key
        by_hash[key] = {**row, "type": content_type}

    account = urllib.parse.quote(_account)
    try:
        say("Asking Cloudflare for an upload token...")
        token = _call("GET", f"/accounts/{account}/pages/projects/{name}/upload-token")
        jwt = token.get("jwt", "")
        if not jwt:
            return {"ok": False, "error": "Cloudflare did not hand back an upload token."}

        say("Checking what is already there...")
        missing = _assets("POST", "/pages/assets/check-missing", jwt,
                          {"hashes": list(by_hash)})
        wanted = missing if isinstance(missing, list) else list(by_hash)

        say(f"Uploading {len(wanted)} of {len(files)} files...")
        _upload(wanted, by_hash, jwt, say)

        say("Publishing...")
        deployment = _deployment(account, name, branch, manifest)
    except CloudflareError as error:
        return {"ok": False, "error": str(error)}

    url = deployment.get("url", "")
    return {
        "ok": True,
        "project": name,
        "url": url,
        "files": len(files),
        "uploaded": len(wanted),
        "id": deployment.get("id", ""),
        "at": int(time.time()),
    }


def _assets(method: str, path: str, jwt: str, body: dict):
    """The asset endpoints take the upload token rather than the API token."""
    url = f"{API}{path}"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method=method,
        headers={
            "Authorization": f"Bearer {jwt}",
            "Content-Type": "application/json",
            "User-Agent": "PyCmd",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        raise CloudflareError(_explain(error.read().decode("utf-8", "replace"),
                                       error.code)) from error
    except (urllib.error.URLError, ValueError) as error:
        raise CloudflareError(f"Could not reach Cloudflare: {error}") from error
    if not payload.get("success", True):
        raise CloudflareError(_explain(json.dumps(payload), 200))
    return payload.get("result")


def _upload(wanted: list, by_hash: dict, jwt: str, say) -> None:
    """Sends the files Cloudflare said it is missing, in small batches."""
    import base64

    batch = []
    sent = 0
    for key in wanted:
        row = by_hash.get(key)
        if row is None:
            continue
        with open(row["full"], "rb") as handle:
            blob = base64.b64encode(handle.read()).decode("ascii")
        batch.append({
            "key": key,
            "value": blob,
            "metadata": {"contentType": row["type"]},
            "base64": True,
        })
        # Cloudflare's own client batches by size rather than count; a phone
        # cares more about not holding fifty files in memory at once.
        if len(batch) >= 20 or sum(len(item["value"]) for item in batch) > 8 * 1024 * 1024:
            _assets("POST", "/pages/assets/upload", jwt, batch)
            sent += len(batch)
            say(f"Uploaded {sent} of {len(wanted)}...")
            batch = []
    if batch:
        _assets("POST", "/pages/assets/upload", jwt, batch)


def _deployment(account: str, name: str, branch: str, manifest: dict) -> dict:
    """Creates the deployment itself, as multipart, which this endpoint wants."""
    boundary = uuid.uuid4().hex
    parts = []

    def add(field: str, value: str) -> None:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"\r\n\r\n"
            f"{value}\r\n".encode("utf-8")
        )

    add("manifest", json.dumps(manifest))
    add("branch", branch)
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)

    return _call(
        "POST",
        f"/accounts/{account}/pages/projects/{name}/deployments",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        raw=body,
    )


def deployments(project: str, limit: int = 5) -> dict:
    """The last few deployments of a project."""
    name = _project_name(project)
    try:
        rows = _call("GET", f"/accounts/{urllib.parse.quote(_account)}"
                            f"/pages/projects/{name}/deployments")
    except CloudflareError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "deployments": [
        {
            "id": row.get("id", ""),
            "url": row.get("url", ""),
            "created": row.get("created_on", ""),
            "status": (row.get("latest_stage") or {}).get("status", ""),
        }
        for row in (rows or [])[:limit]
    ]}


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


WORKER_TEMPLATE = """export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/api") {
      return Response.json({ ok: true, from: "a Worker written on a phone" });
    }
    return new Response("Hello from PyCmd", {
      headers: { "content-type": "text/plain" },
    });
  },
};
"""


def put_worker(name: str, script: str) -> dict:
    """Publishes a Worker. A Worker is one file, so this is one PUT."""
    name = _project_name(name)
    if not script.strip():
        return {"ok": False, "error": "The Worker has no code in it."}

    boundary = uuid.uuid4().hex
    metadata = json.dumps({"main_module": "worker.js", "compatibility_date": "2024-01-01"})
    body = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"metadata\"\r\n"
        f"Content-Type: application/json\r\n\r\n{metadata}\r\n"
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"worker.js\"; filename=\"worker.js\"\r\n"
        f"Content-Type: application/javascript+module\r\n\r\n{script}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    try:
        result = _call(
            "PUT",
            f"/accounts/{urllib.parse.quote(_account)}/workers/scripts/{name}",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            raw=body,
        )
    except CloudflareError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "name": result.get("id", name),
            "url": f"https://{name}.workers.dev",
            "note": "workers.dev has to be switched on for the account before "
                    "that address answers."}


def workers() -> dict:
    """Every Worker script on the account."""
    try:
        rows = _call("GET", f"/accounts/{urllib.parse.quote(_account)}/workers/scripts")
    except CloudflareError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "workers": [
        {"name": row.get("id", ""), "modified": row.get("modified_on", "")}
        for row in (rows or [])
    ]}
