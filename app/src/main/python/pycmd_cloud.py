"""Supabase and Firebase, over their REST APIs, with nothing to install.

Both of these are HTTP services with an official SDK nobody can pip install
onto a phone without a compiler, so this talks to them the way the SDKs do -
plain JSON over HTTPS with `urllib` - and gives you the same shape of API.

    import pycmd_cloud

    sb = pycmd_cloud.supabase()
    rows = sb.table("notes").select("*").eq("done", False).order("id").limit(10).run()
    sb.table("notes").insert({"text": "from my phone"})

    fb = pycmd_cloud.firebase()
    fb.firestore.set("notes/today", {"text": "from my phone", "done": False})
    print(fb.firestore.get("notes/today"))

Credentials are saved once - in the app's own storage, never in the workspace -
and every entry point picks them up, so a script, a server and a console
command all reach the same project without repeating a key.

What is deliberately missing: Supabase realtime and Firestore listeners. Both
are WebSocket protocols, `urllib` does not speak WebSocket, and a fake built
out of polling would be a worse thing to have than an honest gap. Poll it
yourself if you need to; the read calls are cheap.
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request

__all__ = [
    "CloudError",
    "configure",
    "settings",
    "forget",
    "supabase",
    "firebase",
    "Supabase",
    "Firebase",
]

TIMEOUT = 30
USER_AGENT = "PyCmd-Android/2.0"
MAX_BODY = 32 * 1024 * 1024

_settings_dir = None
_cache: dict | None = None


class CloudError(Exception):
    """Anything the service refused, with the status and its own message.

    Carries the parsed body when there is one: these APIs put the useful part
    of a failure in the body, and a bare "HTTP 400" helps nobody.
    """

    def __init__(self, message: str, status: int = 0, body=None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body

    def as_dict(self) -> dict:
        return {"ok": False, "error": str(self), "status": self.status, "body": self.body}


# ---------------------------------------------------------------------------
# Where the keys live
# ---------------------------------------------------------------------------


def configure_storage(directory: str) -> None:
    """Called once from the app. Says where the saved keys go."""
    global _settings_dir, _cache

    _settings_dir = directory
    os.makedirs(directory, exist_ok=True)
    _cache = None


def _settings_path() -> str:
    base = _settings_dir or os.path.join(os.path.expanduser("~"), ".pycmd")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "cloud.json")


def settings() -> dict:
    """Everything saved, with the secrets included - this is a local file."""
    global _cache

    if _cache is None:
        try:
            with open(_settings_path(), "r", encoding="utf-8") as handle:
                _cache = json.load(handle)
        except (OSError, ValueError):
            _cache = {}
    return dict(_cache)


def configure(provider: str, **values) -> dict:
    """Saves the keys for `supabase` or `firebase`. Returns what is now saved.

    Only the fields you pass are changed, so setting an access token later does
    not wipe the project URL.
    """
    global _cache

    provider = provider.strip().lower()
    if provider not in ("supabase", "firebase"):
        raise CloudError(f"unknown provider {provider!r}")

    current = settings()
    entry = dict(current.get(provider) or {})
    for key, value in values.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = str(value).strip()
    current[provider] = entry

    try:
        with open(_settings_path(), "w", encoding="utf-8") as handle:
            json.dump(current, handle, indent=2)
    except OSError as error:
        raise CloudError(f"could not save the settings: {error}") from None
    _cache = current
    return entry


def forget(provider: str = "") -> None:
    """Drops the saved keys - for one provider, or all of them."""
    global _cache

    current = settings()
    if provider:
        current.pop(provider.strip().lower(), None)
    else:
        current = {}
    try:
        with open(_settings_path(), "w", encoding="utf-8") as handle:
            json.dump(current, handle, indent=2)
    except OSError:
        pass
    _cache = current


def status() -> dict:
    """What is configured, without showing the keys themselves."""
    saved = settings()

    def mask(value: str) -> str:
        value = str(value or "")
        if len(value) <= 8:
            return "set" if value else ""
        return f"{value[:4]}...{value[-4:]}"

    supa = saved.get("supabase") or {}
    fire = saved.get("firebase") or {}
    return {
        "supabase": {
            "configured": bool(supa.get("url") and supa.get("key")),
            "url": supa.get("url", ""),
            "key": mask(supa.get("key", "")),
            "service_key": mask(supa.get("service_key", "")),
            "signed_in": bool(supa.get("access_token")),
            "user": supa.get("user_email", ""),
        },
        "firebase": {
            "configured": bool(fire.get("project_id") and fire.get("api_key")),
            "project_id": fire.get("project_id", ""),
            "api_key": mask(fire.get("api_key", "")),
            "database_url": fire.get("database_url", ""),
            "storage_bucket": fire.get("storage_bucket", ""),
            "signed_in": bool(fire.get("id_token")),
            "user": fire.get("user_email", ""),
        },
    }


# ---------------------------------------------------------------------------
# The one place that speaks HTTP
# ---------------------------------------------------------------------------


def _request(
    method: str,
    url: str,
    headers: dict | None = None,
    body=None,
    raw: bool = False,
    timeout: int = TIMEOUT,
):
    """One request. Returns parsed JSON, or bytes when `raw`."""
    payload = None
    sending = dict(headers or {})
    sending.setdefault("User-Agent", USER_AGENT)

    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            payload = bytes(body)
        else:
            payload = json.dumps(body).encode("utf-8")
            sending.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(url, data=payload, headers=sending, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(MAX_BODY)
            if raw:
                return data
            if not data:
                return None
            try:
                return json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return data.decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        detail = error.read(64 * 1024)
        parsed = None
        try:
            parsed = json.loads(detail.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            parsed = detail.decode("utf-8", "replace") if detail else None
        raise CloudError(_message_from(parsed, error.code), error.code, parsed) from None
    except urllib.error.URLError as error:
        raise CloudError(f"could not reach it: {getattr(error, 'reason', error)}") from None
    except TimeoutError:
        raise CloudError("the request timed out") from None


def _message_from(body, code: int) -> str:
    """Digs the human-readable half out of whichever error shape came back."""
    if isinstance(body, dict):
        for key in ("message", "msg", "error_description", "hint", "details"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
        error = body.get("error")
        if isinstance(error, str) and error:
            return error
        if isinstance(error, dict):
            for key in ("message", "status"):
                value = error.get(key)
                if isinstance(value, str) and value:
                    return value
    if isinstance(body, str) and body.strip():
        return body.strip()[:300]
    return f"HTTP {code}"


def _query(params: dict) -> str:
    clean = {k: v for k, v in params.items() if v is not None and v != ""}
    return ("?" + urllib.parse.urlencode(clean, doseq=True)) if clean else ""


# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------


class Query:
    """A PostgREST query, built up a filter at a time.

    Every method returns `self`, so the whole thing reads the way the official
    client does, and nothing is sent until `run()`.
    """

    def __init__(self, client: "Supabase", table: str) -> None:
        self._client = client
        self._table = table
        self._filters: list[tuple[str, str]] = []
        self._select = "*"
        self._order = None
        self._limit = None
        self._offset = None
        self._single = False
        self._count = None

    # -- filters ------------------------------------------------------------
    def _add(self, column: str, operator: str, value) -> "Query":
        self._filters.append((column, f"{operator}.{_pg_value(value)}"))
        return self

    def eq(self, column, value): return self._add(column, "eq", value)
    def neq(self, column, value): return self._add(column, "neq", value)
    def gt(self, column, value): return self._add(column, "gt", value)
    def gte(self, column, value): return self._add(column, "gte", value)
    def lt(self, column, value): return self._add(column, "lt", value)
    def lte(self, column, value): return self._add(column, "lte", value)
    def like(self, column, pattern): return self._add(column, "like", pattern)
    def ilike(self, column, pattern): return self._add(column, "ilike", pattern)
    def is_(self, column, value): return self._add(column, "is", value)
    def contains(self, column, value): return self._add(column, "cs", value)
    def contained_by(self, column, value): return self._add(column, "cd", value)
    def match(self, values: dict):
        for column, value in (values or {}).items():
            self.eq(column, value)
        return self

    def in_(self, column, values):
        joined = ",".join(str(v) for v in values)
        self._filters.append((column, f"in.({joined})"))
        return self

    def not_(self, column, operator, value):
        self._filters.append((column, f"not.{operator}.{_pg_value(value)}"))
        return self

    def text_search(self, column, phrase):
        self._filters.append((column, f"fts.{phrase}"))
        return self

    # -- shaping ------------------------------------------------------------
    def select(self, columns: str = "*") -> "Query":
        self._select = columns or "*"
        return self

    def order(self, column: str, ascending: bool = True) -> "Query":
        self._order = f"{column}.{'asc' if ascending else 'desc'}"
        return self

    def limit(self, count: int) -> "Query":
        self._limit = int(count)
        return self

    def offset(self, count: int) -> "Query":
        self._offset = int(count)
        return self

    def range(self, start: int, end: int) -> "Query":
        self._offset = int(start)
        self._limit = int(end) - int(start) + 1
        return self

    def single(self) -> "Query":
        """Return one row instead of a list, and fail if there is not exactly one."""
        self._single = True
        return self

    def with_count(self, kind: str = "exact") -> "Query":
        self._count = kind
        return self

    # -- running ------------------------------------------------------------
    def _url(self) -> str:
        params = {"select": self._select}
        if self._order:
            params["order"] = self._order
        if self._limit is not None:
            params["limit"] = self._limit
        if self._offset is not None:
            params["offset"] = self._offset
        pairs = list(params.items()) + self._filters
        query = urllib.parse.urlencode(pairs)
        return f"{self._client.rest_url}/{self._table}?{query}"

    def run(self):
        """Sends it. The name every other client spells `execute`."""
        headers = self._client.headers()
        if self._single:
            headers["Accept"] = "application/vnd.pgrst.object+json"
        if self._count:
            headers["Prefer"] = f"count={self._count}"
        return _request("GET", self._url(), headers)

    execute = run

    def count(self) -> int:
        """How many rows match, without fetching them."""
        headers = self._client.headers()
        headers["Prefer"] = "count=exact"
        headers["Range"] = "0-0"
        params = list({"select": "*"}.items()) + self._filters
        url = f"{self._client.rest_url}/{self._table}?{urllib.parse.urlencode(params)}"
        # PostgREST puts the total in Content-Range: the body is one row.
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                response.read(MAX_BODY)
                content_range = response.headers.get("Content-Range", "")
        except urllib.error.HTTPError as error:
            raise CloudError(f"count failed: HTTP {error.code}", error.code) from None
        except urllib.error.URLError as error:
            raise CloudError(f"could not reach it: {getattr(error, 'reason', error)}") from None
        total = content_range.split("/")[-1]
        return int(total) if total.isdigit() else 0

    def update(self, values: dict):
        headers = self._client.headers()
        headers["Prefer"] = "return=representation"
        return _request("PATCH", self._url(), headers, values)

    def delete(self):
        headers = self._client.headers()
        headers["Prefer"] = "return=representation"
        return _request("DELETE", self._url(), headers)


def _pg_value(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class SupabaseAuth:
    """GoTrue: everything about who is signed in."""

    def __init__(self, client: "Supabase") -> None:
        self._client = client

    @property
    def _base(self) -> str:
        return f"{self._client.url}/auth/v1"

    def _headers(self, authorised: bool = False) -> dict:
        headers = {"apikey": self._client.key}
        if authorised and self._client.access_token:
            headers["Authorization"] = f"Bearer {self._client.access_token}"
        return headers

    def sign_up(self, email: str, password: str, data: dict | None = None):
        body = {"email": email, "password": password}
        if data:
            body["data"] = data
        result = _request("POST", f"{self._base}/signup", self._headers(), body)
        self._remember(result)
        return result

    def sign_in(self, email: str, password: str):
        result = _request(
            "POST",
            f"{self._base}/token?grant_type=password",
            self._headers(),
            {"email": email, "password": password},
        )
        self._remember(result)
        return result

    def sign_in_with_phone(self, phone: str, password: str):
        result = _request(
            "POST",
            f"{self._base}/token?grant_type=password",
            self._headers(),
            {"phone": phone, "password": password},
        )
        self._remember(result)
        return result

    def sign_in_with_otp(self, email: str):
        return _request("POST", f"{self._base}/otp", self._headers(), {"email": email})

    def verify_otp(self, email: str, token: str, kind: str = "email"):
        result = _request(
            "POST", f"{self._base}/verify", self._headers(),
            {"email": email, "token": token, "type": kind},
        )
        self._remember(result)
        return result

    def refresh(self, refresh_token: str = ""):
        token = refresh_token or self._client.refresh_token
        if not token:
            raise CloudError("no refresh token saved")
        result = _request(
            "POST", f"{self._base}/token?grant_type=refresh_token",
            self._headers(), {"refresh_token": token},
        )
        self._remember(result)
        return result

    def user(self):
        return _request("GET", f"{self._base}/user", self._headers(True))

    def update_user(self, values: dict):
        return _request("PUT", f"{self._base}/user", self._headers(True), values)

    def reset_password(self, email: str):
        return _request("POST", f"{self._base}/recover", self._headers(), {"email": email})

    def sign_out(self):
        try:
            if self._client.access_token:
                _request("POST", f"{self._base}/logout", self._headers(True), {})
        except CloudError:
            # The token may already be dead; forgetting it locally is the point.
            pass
        self._client.set_session("", "")
        configure("supabase", access_token=None, refresh_token=None, user_email=None)
        return {"ok": True}

    def admin_list_users(self, page: int = 1, per_page: int = 50):
        return _request(
            "GET",
            f"{self._base}/admin/users{_query({'page': page, 'per_page': per_page})}",
            self._client.service_headers(),
        )

    def admin_create_user(self, email: str, password: str, confirm: bool = True):
        return _request(
            "POST", f"{self._base}/admin/users", self._client.service_headers(),
            {"email": email, "password": password, "email_confirm": confirm},
        )

    def admin_delete_user(self, user_id: str):
        return _request(
            "DELETE", f"{self._base}/admin/users/{user_id}", self._client.service_headers(),
        )

    def _remember(self, result) -> None:
        """Keeps the session, so the next script does not have to sign in again."""
        if not isinstance(result, dict):
            return
        access = result.get("access_token")
        refresh = result.get("refresh_token")
        if not access:
            return
        self._client.set_session(access, refresh or "")
        email = ""
        user = result.get("user")
        if isinstance(user, dict):
            email = user.get("email") or ""
        configure("supabase", access_token=access, refresh_token=refresh or "",
                  user_email=email)


class SupabaseStorage:
    """Buckets and the files in them."""

    def __init__(self, client: "Supabase") -> None:
        self._client = client

    @property
    def _base(self) -> str:
        return f"{self._client.url}/storage/v1"

    def list_buckets(self):
        return _request("GET", f"{self._base}/bucket", self._client.headers())

    def get_bucket(self, name: str):
        return _request("GET", f"{self._base}/bucket/{name}", self._client.headers())

    def create_bucket(self, name: str, public: bool = False):
        return _request(
            "POST", f"{self._base}/bucket", self._client.headers(),
            {"name": name, "id": name, "public": public},
        )

    def empty_bucket(self, name: str):
        return _request("POST", f"{self._base}/bucket/{name}/empty", self._client.headers(), {})

    def delete_bucket(self, name: str):
        return _request("DELETE", f"{self._base}/bucket/{name}", self._client.headers())

    def list(self, bucket: str, prefix: str = "", limit: int = 100):
        return _request(
            "POST", f"{self._base}/object/list/{bucket}", self._client.headers(),
            {"prefix": prefix, "limit": limit, "offset": 0},
        )

    def upload(self, bucket: str, path: str, data, content_type: str = "") -> dict:
        if isinstance(data, str):
            data = data.encode("utf-8")
            content_type = content_type or "text/plain"
        headers = self._client.headers()
        headers["Content-Type"] = content_type or _guess_type(path)
        headers["x-upsert"] = "true"
        _request("POST", f"{self._base}/object/{bucket}/{path}", headers, data)
        return {"ok": True, "bucket": bucket, "path": path, "bytes": len(data)}

    def upload_file(self, bucket: str, path: str, local_path: str) -> dict:
        with open(local_path, "rb") as handle:
            return self.upload(bucket, path, handle.read(), _guess_type(local_path))

    def download(self, bucket: str, path: str) -> bytes:
        return _request(
            "GET", f"{self._base}/object/{bucket}/{path}", self._client.headers(), raw=True,
        )

    def download_to(self, bucket: str, path: str, local_path: str) -> dict:
        data = self.download(bucket, path)
        os.makedirs(os.path.dirname(os.path.abspath(local_path)) or ".", exist_ok=True)
        with open(local_path, "wb") as handle:
            handle.write(data)
        return {"ok": True, "path": local_path, "bytes": len(data)}

    def remove(self, bucket: str, paths):
        if isinstance(paths, str):
            paths = [paths]
        return _request(
            "DELETE", f"{self._base}/object/{bucket}", self._client.headers(),
            {"prefixes": list(paths)},
        )

    def move(self, bucket: str, source: str, target: str):
        return _request(
            "POST", f"{self._base}/object/move", self._client.headers(),
            {"bucketId": bucket, "sourceKey": source, "destinationKey": target},
        )

    def copy(self, bucket: str, source: str, target: str):
        return _request(
            "POST", f"{self._base}/object/copy", self._client.headers(),
            {"bucketId": bucket, "sourceKey": source, "destinationKey": target},
        )

    def public_url(self, bucket: str, path: str) -> str:
        return f"{self._base}/object/public/{bucket}/{path}"

    def signed_url(self, bucket: str, path: str, seconds: int = 3600) -> str:
        result = _request(
            "POST", f"{self._base}/object/sign/{bucket}/{path}", self._client.headers(),
            {"expiresIn": int(seconds)},
        )
        signed = (result or {}).get("signedURL", "")
        return f"{self._client.url}/storage/v1{signed}" if signed else ""


class Supabase:
    """A Supabase project."""

    def __init__(self, url: str, key: str, access_token: str = "",
                 refresh_token: str = "", service_key: str = "") -> None:
        if not url or not key:
            raise CloudError("Supabase needs a project URL and an anon key")
        self.url = url.rstrip("/")
        self.key = key
        self.service_key = service_key
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.auth = SupabaseAuth(self)
        self.storage = SupabaseStorage(self)

    @property
    def rest_url(self) -> str:
        return f"{self.url}/rest/v1"

    def headers(self) -> dict:
        token = self.access_token or self.key
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def service_headers(self) -> dict:
        """For the admin endpoints, which the anon key cannot touch."""
        if not self.service_key:
            raise CloudError("that needs the service key, which is not configured")
        return {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json",
        }

    def set_session(self, access_token: str, refresh_token: str = "") -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token

    # -- database -----------------------------------------------------------
    def table(self, name: str) -> Query:
        return Query(self, name)

    def select(self, table: str, columns: str = "*", **filters):
        query = Query(self, table).select(columns)
        return query.match(filters).run()

    def insert(self, table: str, rows, upsert: bool = False):
        headers = self.headers()
        prefer = ["return=representation"]
        if upsert:
            prefer.append("resolution=merge-duplicates")
        headers["Prefer"] = ",".join(prefer)
        return _request("POST", f"{self.rest_url}/{table}", headers, rows)

    def upsert(self, table: str, rows):
        return self.insert(table, rows, upsert=True)

    def update(self, table: str, values: dict, **filters):
        return Query(self, table).match(filters).update(values)

    def delete(self, table: str, **filters):
        return Query(self, table).match(filters).delete()

    def rpc(self, function: str, params: dict | None = None):
        """Calls a Postgres function you defined in the project."""
        return _request("POST", f"{self.rest_url}/rpc/{function}", self.headers(), params or {})

    def invoke(self, function: str, payload=None):
        """Calls an edge function."""
        return _request(
            "POST", f"{self.url}/functions/v1/{function}", self.headers(), payload or {},
        )

    def ping(self) -> dict:
        """Is the project reachable and is the key accepted?"""
        started = time.monotonic()
        _request("GET", f"{self.rest_url}/", self.headers())
        return {"ok": True, "millis": int((time.monotonic() - started) * 1000)}


# ---------------------------------------------------------------------------
# Firebase
# ---------------------------------------------------------------------------


def _to_firestore(value):
    """Turns a Python value into Firestore's typed JSON."""
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, (bytes, bytearray)):
        import base64

        return {"bytesValue": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_to_firestore(item) for item in value]}}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {k: _to_firestore(v) for k, v in value.items()}}}
    return {"stringValue": str(value)}


def _from_firestore(value):
    """And back again."""
    if not isinstance(value, dict):
        return value
    if "nullValue" in value:
        return None
    if "booleanValue" in value:
        return value["booleanValue"]
    if "integerValue" in value:
        try:
            return int(value["integerValue"])
        except (TypeError, ValueError):
            return value["integerValue"]
    if "doubleValue" in value:
        return value["doubleValue"]
    if "stringValue" in value:
        return value["stringValue"]
    if "timestampValue" in value:
        return value["timestampValue"]
    if "bytesValue" in value:
        import base64

        return base64.b64decode(value["bytesValue"])
    if "referenceValue" in value:
        return value["referenceValue"]
    if "geoPointValue" in value:
        return value["geoPointValue"]
    if "arrayValue" in value:
        return [_from_firestore(item) for item in value["arrayValue"].get("values", [])]
    if "mapValue" in value:
        fields = value["mapValue"].get("fields", {})
        return {k: _from_firestore(v) for k, v in fields.items()}
    return value


def _document_to_dict(document: dict) -> dict:
    """A Firestore document, flattened, with its id and timestamps kept."""
    if not isinstance(document, dict):
        return {}
    fields = document.get("fields") or {}
    out = {k: _from_firestore(v) for k, v in fields.items()}
    name = document.get("name", "")
    if name:
        out["_id"] = name.rsplit("/", 1)[-1]
        out["_path"] = name.split("/documents/", 1)[-1] if "/documents/" in name else name
    for key in ("createTime", "updateTime"):
        if document.get(key):
            out["_" + key] = document[key]
    return out


class Firestore:
    """The document database."""

    def __init__(self, client: "Firebase") -> None:
        self._client = client

    @property
    def _base(self) -> str:
        return (
            f"https://firestore.googleapis.com/v1/projects/"
            f"{self._client.project_id}/databases/(default)/documents"
        )

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._client.id_token:
            headers["Authorization"] = f"Bearer {self._client.id_token}"
        return headers

    def _auth_query(self) -> str:
        # Without a signed-in user the API key is what identifies the project.
        return "" if self._client.id_token else f"?key={self._client.api_key}"

    def get(self, path: str) -> dict:
        result = _request("GET", f"{self._base}/{path}{self._auth_query()}", self._headers())
        return _document_to_dict(result)

    def exists(self, path: str) -> bool:
        try:
            self.get(path)
            return True
        except CloudError as error:
            if error.status == 404:
                return False
            raise

    def list(self, collection: str, page_size: int = 50, page_token: str = "") -> list:
        params = {"pageSize": page_size, "pageToken": page_token or None}
        if not self._client.id_token:
            params["key"] = self._client.api_key
        result = _request("GET", f"{self._base}/{collection}{_query(params)}", self._headers())
        return [_document_to_dict(doc) for doc in (result or {}).get("documents", [])]

    def create(self, collection: str, data: dict, document_id: str = "") -> dict:
        params = {"documentId": document_id or None}
        if not self._client.id_token:
            params["key"] = self._client.api_key
        body = {"fields": {k: _to_firestore(v) for k, v in data.items()}}
        result = _request(
            "POST", f"{self._base}/{collection}{_query(params)}", self._headers(), body,
        )
        return _document_to_dict(result)

    def set(self, path: str, data: dict) -> dict:
        """Replaces the whole document, creating it if it is not there."""
        body = {"fields": {k: _to_firestore(v) for k, v in data.items()}}
        result = _request(
            "PATCH", f"{self._base}/{path}{self._auth_query()}", self._headers(), body,
        )
        return _document_to_dict(result)

    def update(self, path: str, data: dict) -> dict:
        """Changes only the fields you pass, leaving the rest alone."""
        params = [("updateMask.fieldPaths", key) for key in data]
        if not self._client.id_token:
            params.append(("key", self._client.api_key))
        body = {"fields": {k: _to_firestore(v) for k, v in data.items()}}
        url = f"{self._base}/{path}?{urllib.parse.urlencode(params)}"
        return _document_to_dict(_request("PATCH", url, self._headers(), body))

    def delete(self, path: str) -> dict:
        _request("DELETE", f"{self._base}/{path}{self._auth_query()}", self._headers())
        return {"ok": True, "path": path}

    def query(
        self,
        collection: str,
        where: list | None = None,
        order_by: str = "",
        descending: bool = False,
        limit: int = 0,
    ) -> list:
        """A structured query. `where` is a list of (field, op, value).

        Operators are the ones Firestore names: EQUAL, NOT_EQUAL, LESS_THAN,
        LESS_THAN_OR_EQUAL, GREATER_THAN, GREATER_THAN_OR_EQUAL, ARRAY_CONTAINS,
        IN, ARRAY_CONTAINS_ANY, NOT_IN. Lower case and `==`, `!=`, `<`, `<=`,
        `>`, `>=` are accepted too, because nobody wants to type the long ones.
        """
        query: dict = {"from": [{"collectionId": collection}]}

        filters = []
        for field, operator, value in (where or []):
            filters.append({
                "fieldFilter": {
                    "field": {"fieldPath": field},
                    "op": _firestore_op(operator),
                    "value": _to_firestore(value),
                }
            })
        if len(filters) == 1:
            query["where"] = filters[0]
        elif filters:
            query["where"] = {"compositeFilter": {"op": "AND", "filters": filters}}

        if order_by:
            query["orderBy"] = [{
                "field": {"fieldPath": order_by},
                "direction": "DESCENDING" if descending else "ASCENDING",
            }]
        if limit:
            query["limit"] = int(limit)

        url = f"{self._base}:runQuery{self._auth_query()}"
        result = _request("POST", url, self._headers(), {"structuredQuery": query})
        rows = []
        for entry in result or []:
            document = entry.get("document") if isinstance(entry, dict) else None
            if document:
                rows.append(_document_to_dict(document))
        return rows

    def count(self, collection: str, where: list | None = None) -> int:
        return len(self.query(collection, where=where))

    def batch_get(self, paths: list) -> list:
        """Several documents in one round trip."""
        # Built from _base like every other call here. Spelling the host out a
        # second time meant this one method ignored where the rest were
        # pointed, which is exactly the kind of thing that is only ever found
        # by a test that redirects them.
        body = {"documents": [f"{self._base}/{path}" for path in paths]}
        result = _request("POST", f"{self._base}:batchGet{self._auth_query()}",
                          self._headers(), body)
        rows = []
        for entry in result or []:
            found = entry.get("found") if isinstance(entry, dict) else None
            if found:
                rows.append(_document_to_dict(found))
        return rows


FIRESTORE_OPS = {
    "==": "EQUAL", "=": "EQUAL", "eq": "EQUAL",
    "!=": "NOT_EQUAL", "neq": "NOT_EQUAL",
    "<": "LESS_THAN", "lt": "LESS_THAN",
    "<=": "LESS_THAN_OR_EQUAL", "lte": "LESS_THAN_OR_EQUAL",
    ">": "GREATER_THAN", "gt": "GREATER_THAN",
    ">=": "GREATER_THAN_OR_EQUAL", "gte": "GREATER_THAN_OR_EQUAL",
    "in": "IN", "not-in": "NOT_IN", "not_in": "NOT_IN",
    "contains": "ARRAY_CONTAINS", "array_contains": "ARRAY_CONTAINS",
    "contains_any": "ARRAY_CONTAINS_ANY", "array_contains_any": "ARRAY_CONTAINS_ANY",
}


def _firestore_op(operator: str) -> str:
    key = str(operator).strip()
    return FIRESTORE_OPS.get(key.lower(), key.upper().replace(" ", "_"))


class FirebaseAuth:
    """Identity Toolkit: sign-up, sign-in and everything after."""

    BASE = "https://identitytoolkit.googleapis.com/v1/accounts"

    def __init__(self, client: "Firebase") -> None:
        self._client = client

    def _post(self, action: str, body: dict):
        url = f"{self.BASE}:{action}?key={self._client.api_key}"
        return _request("POST", url, {"Content-Type": "application/json"}, body)

    def sign_up(self, email: str, password: str):
        result = self._post("signUp", {
            "email": email, "password": password, "returnSecureToken": True,
        })
        self._remember(result)
        return result

    def sign_in(self, email: str, password: str):
        result = self._post("signInWithPassword", {
            "email": email, "password": password, "returnSecureToken": True,
        })
        self._remember(result)
        return result

    def sign_in_anonymous(self):
        result = self._post("signUp", {"returnSecureToken": True})
        self._remember(result)
        return result

    def sign_in_with_custom_token(self, token: str):
        result = self._post("signInWithCustomToken", {
            "token": token, "returnSecureToken": True,
        })
        self._remember(result)
        return result

    def refresh(self, refresh_token: str = ""):
        token = refresh_token or self._client.refresh_token
        if not token:
            raise CloudError("no refresh token saved")
        url = f"https://securetoken.googleapis.com/v1/token?key={self._client.api_key}"
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token", "refresh_token": token,
        }).encode("utf-8")
        result = _request(
            "POST", url, {"Content-Type": "application/x-www-form-urlencoded"}, body,
        )
        if isinstance(result, dict) and result.get("id_token"):
            self._client.set_session(result["id_token"], result.get("refresh_token", ""))
            configure("firebase", id_token=result["id_token"],
                      refresh_token=result.get("refresh_token", ""))
        return result

    def lookup(self, id_token: str = ""):
        return self._post("lookup", {"idToken": id_token or self._client.id_token})

    def update(self, values: dict):
        body = dict(values)
        body["idToken"] = self._client.id_token
        body.setdefault("returnSecureToken", True)
        return self._post("update", body)

    def change_email(self, email: str):
        return self.update({"email": email})

    def change_password(self, password: str):
        return self.update({"password": password})

    def send_verification(self):
        return self._post("sendOobCode", {
            "requestType": "VERIFY_EMAIL", "idToken": self._client.id_token,
        })

    def send_password_reset(self, email: str):
        return self._post("sendOobCode", {"requestType": "PASSWORD_RESET", "email": email})

    def confirm_password_reset(self, code: str, new_password: str):
        return self._post("resetPassword", {"oobCode": code, "newPassword": new_password})

    def delete_account(self):
        result = self._post("delete", {"idToken": self._client.id_token})
        self.sign_out()
        return result

    def sign_out(self):
        self._client.set_session("", "")
        configure("firebase", id_token=None, refresh_token=None, user_email=None)
        return {"ok": True}

    def _remember(self, result) -> None:
        if not isinstance(result, dict):
            return
        token = result.get("idToken")
        if not token:
            return
        self._client.set_session(token, result.get("refreshToken", ""))
        configure("firebase", id_token=token,
                  refresh_token=result.get("refreshToken", ""),
                  user_email=result.get("email", ""))


class Realtime:
    """The Realtime Database, read and written as plain JSON."""

    def __init__(self, client: "Firebase") -> None:
        self._client = client

    def _url(self, path: str, params: dict | None = None) -> str:
        base = (self._client.database_url or "").rstrip("/")
        if not base:
            raise CloudError("no Realtime Database URL is configured")
        params = dict(params or {})
        if self._client.id_token:
            params["auth"] = self._client.id_token
        return f"{base}/{path.strip('/')}.json{_query(params)}"

    def get(self, path: str = ""):
        return _request("GET", self._url(path), {})

    def set(self, path: str, value):
        return _request("PUT", self._url(path), {}, value)

    def update(self, path: str, value: dict):
        return _request("PATCH", self._url(path), {}, value)

    def push(self, path: str, value):
        """Appends under a generated key, the way the SDK's push does."""
        return _request("POST", self._url(path), {}, value)

    def delete(self, path: str):
        _request("DELETE", self._url(path), {})
        return {"ok": True, "path": path}

    def query(
        self,
        path: str,
        order_by: str = "",
        limit_to_first: int = 0,
        limit_to_last: int = 0,
        start_at=None,
        end_at=None,
        equal_to=None,
    ):
        params: dict = {}
        if order_by:
            params["orderBy"] = json.dumps(order_by)
        if limit_to_first:
            params["limitToFirst"] = limit_to_first
        if limit_to_last:
            params["limitToLast"] = limit_to_last
        if start_at is not None:
            params["startAt"] = json.dumps(start_at)
        if end_at is not None:
            params["endAt"] = json.dumps(end_at)
        if equal_to is not None:
            params["equalTo"] = json.dumps(equal_to)
        return _request("GET", self._url(path, params), {})

    def keys(self, path: str = "") -> list:
        result = _request("GET", self._url(path, {"shallow": "true"}), {})
        return sorted(result.keys()) if isinstance(result, dict) else []


class FirebaseStorage:
    """Cloud Storage for Firebase."""

    def __init__(self, client: "Firebase") -> None:
        self._client = client

    @property
    def _bucket(self) -> str:
        bucket = self._client.storage_bucket
        if not bucket:
            raise CloudError("no storage bucket is configured")
        return bucket

    def _base(self) -> str:
        return f"https://firebasestorage.googleapis.com/v0/b/{self._bucket}/o"

    def _headers(self) -> dict:
        headers = {}
        if self._client.id_token:
            headers["Authorization"] = f"Firebase {self._client.id_token}"
        return headers

    def upload(self, path: str, data, content_type: str = ""):
        if isinstance(data, str):
            data = data.encode("utf-8")
            content_type = content_type or "text/plain"
        headers = self._headers()
        headers["Content-Type"] = content_type or _guess_type(path)
        url = f"{self._base()}?name={urllib.parse.quote(path, safe='')}"
        return _request("POST", url, headers, data)

    def upload_file(self, path: str, local_path: str):
        with open(local_path, "rb") as handle:
            return self.upload(path, handle.read(), _guess_type(local_path))

    def download(self, path: str) -> bytes:
        url = f"{self._base()}/{urllib.parse.quote(path, safe='')}?alt=media"
        return _request("GET", url, self._headers(), raw=True)

    def download_to(self, path: str, local_path: str) -> dict:
        data = self.download(path)
        os.makedirs(os.path.dirname(os.path.abspath(local_path)) or ".", exist_ok=True)
        with open(local_path, "wb") as handle:
            handle.write(data)
        return {"ok": True, "path": local_path, "bytes": len(data)}

    def metadata(self, path: str):
        url = f"{self._base()}/{urllib.parse.quote(path, safe='')}"
        return _request("GET", url, self._headers())

    def delete(self, path: str):
        url = f"{self._base()}/{urllib.parse.quote(path, safe='')}"
        _request("DELETE", url, self._headers())
        return {"ok": True, "path": path}

    def list(self, prefix: str = "", limit: int = 100):
        params = {"prefix": prefix or None, "maxResults": limit}
        return _request("GET", f"{self._base()}{_query(params)}", self._headers())

    def url(self, path: str) -> str:
        return f"{self._base()}/{urllib.parse.quote(path, safe='')}?alt=media"


class Firebase:
    """A Firebase project."""

    def __init__(self, project_id: str, api_key: str, database_url: str = "",
                 storage_bucket: str = "", id_token: str = "",
                 refresh_token: str = "") -> None:
        if not project_id or not api_key:
            raise CloudError("Firebase needs a project id and a web API key")
        self.project_id = project_id
        self.api_key = api_key
        self.database_url = database_url
        self.storage_bucket = storage_bucket or f"{project_id}.appspot.com"
        self.id_token = id_token
        self.refresh_token = refresh_token
        self.firestore = Firestore(self)
        self.auth = FirebaseAuth(self)
        self.rtdb = Realtime(self)
        self.storage = FirebaseStorage(self)

    def set_session(self, id_token: str, refresh_token: str = "") -> None:
        self.id_token = id_token
        self.refresh_token = refresh_token

    def ping(self) -> dict:
        started = time.monotonic()
        self.firestore.list("__pycmd_ping__", page_size=1)
        return {"ok": True, "millis": int((time.monotonic() - started) * 1000)}


def _guess_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


# ---------------------------------------------------------------------------
# The two front doors
# ---------------------------------------------------------------------------


def supabase(url: str = "", key: str = "") -> Supabase:
    """The configured project, or one you name here."""
    saved = settings().get("supabase") or {}
    return Supabase(
        url or saved.get("url", ""),
        key or saved.get("key", ""),
        access_token=saved.get("access_token", ""),
        refresh_token=saved.get("refresh_token", ""),
        service_key=saved.get("service_key", ""),
    )


def firebase(project_id: str = "", api_key: str = "") -> Firebase:
    """The configured project, or one you name here."""
    saved = settings().get("firebase") or {}
    return Firebase(
        project_id or saved.get("project_id", ""),
        api_key or saved.get("api_key", ""),
        database_url=saved.get("database_url", ""),
        storage_bucket=saved.get("storage_bucket", ""),
        id_token=saved.get("id_token", ""),
        refresh_token=saved.get("refresh_token", ""),
    )
