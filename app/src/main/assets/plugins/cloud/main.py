"""Cloud - Supabase and Firebase, from the console and from a panel.

The client itself lives in `pycmd_cloud`, which any script or server can import
directly. This plugin is the part you touch: a panel to connect a project and
poke at it, and console commands so you do not have to leave the console to
read a row.

    sb select notes 5
    fb get notes/today
    cloud

Everything here goes through the same saved keys, so a script you write, a
server you run and a command you type all reach the same project.
"""

import json
import os

import pycmd_cloud as cloud


def setup(api):
    api.log("Cloud is ready", "supabase + firebase")

    # ------------------------------------------------------------- helpers

    def pretty(value) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, indent=2, default=str)
        return str(value)

    def parse_json(text: str, what: str):
        try:
            return json.loads(text)
        except ValueError as error:
            raise ValueError(f"{what} is not valid JSON: {error}") from None

    def resolve(path: str) -> str:
        return path if os.path.isabs(path) else api.workspace_path(path)

    # ------------------------------------------------------- panel exports

    @api.export
    def state(payload=None):
        """What is connected, with the keys masked."""
        return cloud.status()

    @api.export
    def save_supabase(payload):
        payload = payload or {}
        cloud.configure(
            "supabase",
            url=payload.get("url", ""),
            key=payload.get("key", ""),
            service_key=payload.get("service_key", ""),
        )
        return cloud.status()

    @api.export
    def save_firebase(payload):
        payload = payload or {}
        cloud.configure(
            "firebase",
            project_id=payload.get("project_id", ""),
            api_key=payload.get("api_key", ""),
            database_url=payload.get("database_url", ""),
            storage_bucket=payload.get("storage_bucket", ""),
        )
        return cloud.status()

    @api.export
    def forget(payload):
        cloud.forget((payload or {}).get("provider", ""))
        return cloud.status()

    @api.export
    def ping(payload):
        provider = (payload or {}).get("provider", "supabase")
        try:
            client = cloud.supabase() if provider == "supabase" else cloud.firebase()
            return {"ok": True, **client.ping()}
        except cloud.CloudError as error:
            return error.as_dict()

    @api.export
    def run_query(payload):
        """The panel's read: a table for Supabase, a collection for Firebase."""
        payload = payload or {}
        provider = payload.get("provider", "supabase")
        name = (payload.get("name") or "").strip()
        limit = int(payload.get("limit") or 25)
        if not name:
            return {"ok": False, "error": "name a table or a collection"}

        try:
            if provider == "supabase":
                query = cloud.supabase().table(name).select(payload.get("columns") or "*")
                if payload.get("order"):
                    query = query.order(payload["order"], not payload.get("descending"))
                if payload.get("where_column"):
                    query = query.eq(payload["where_column"], _coerce(payload.get("where_value")))
                rows = query.limit(limit).run()
            else:
                where = []
                if payload.get("where_column"):
                    where.append((payload["where_column"], "==",
                                  _coerce(payload.get("where_value"))))
                if where or payload.get("order"):
                    rows = cloud.firebase().firestore.query(
                        name, where=where, order_by=payload.get("order") or "",
                        descending=bool(payload.get("descending")), limit=limit,
                    )
                else:
                    rows = cloud.firebase().firestore.list(name, page_size=limit)
            rows = rows if isinstance(rows, list) else [rows]
            return {"ok": True, "rows": rows, "count": len(rows)}
        except cloud.CloudError as error:
            return error.as_dict()

    @api.export
    def write_row(payload):
        """Insert into a table, or set a document."""
        payload = payload or {}
        provider = payload.get("provider", "supabase")
        name = (payload.get("name") or "").strip()
        try:
            data = parse_json(payload.get("json") or "{}", "that")
        except ValueError as error:
            return {"ok": False, "error": str(error)}

        try:
            if provider == "supabase":
                return {"ok": True, "result": cloud.supabase().insert(name, data)}
            path = payload.get("path") or name
            return {"ok": True, "result": cloud.firebase().firestore.set(path, data)}
        except cloud.CloudError as error:
            return error.as_dict()

    @api.export
    def delete_row(payload):
        payload = payload or {}
        provider = payload.get("provider", "supabase")
        try:
            if provider == "supabase":
                name = payload.get("name", "")
                column = payload.get("where_column") or "id"
                value = _coerce(payload.get("where_value"))
                return {"ok": True, "result": cloud.supabase().delete(name, **{column: value})}
            return {"ok": True,
                    "result": cloud.firebase().firestore.delete(payload.get("path", ""))}
        except cloud.CloudError as error:
            return error.as_dict()

    @api.export
    def sign_in(payload):
        """The 'verify this user' half: sign in and keep the session."""
        payload = payload or {}
        provider = payload.get("provider", "supabase")
        email = payload.get("email", "")
        password = payload.get("password", "")
        try:
            if provider == "supabase":
                result = cloud.supabase().auth.sign_in(email, password)
                user = result.get("user") or {}
            else:
                result = cloud.firebase().auth.sign_in(email, password)
                user = {"email": result.get("email"), "id": result.get("localId")}
            return {"ok": True, "user": user}
        except cloud.CloudError as error:
            return error.as_dict()

    @api.export
    def sign_up(payload):
        payload = payload or {}
        provider = payload.get("provider", "supabase")
        try:
            if provider == "supabase":
                cloud.supabase().auth.sign_up(payload.get("email", ""),
                                              payload.get("password", ""))
            else:
                cloud.firebase().auth.sign_up(payload.get("email", ""),
                                              payload.get("password", ""))
            return {"ok": True}
        except cloud.CloudError as error:
            return error.as_dict()

    @api.export
    def sign_out(payload):
        provider = (payload or {}).get("provider", "supabase")
        client = cloud.supabase() if provider == "supabase" else cloud.firebase()
        client.auth.sign_out()
        return cloud.status()

    @api.export
    def whoami(payload):
        provider = (payload or {}).get("provider", "supabase")
        try:
            if provider == "supabase":
                return {"ok": True, "user": cloud.supabase().auth.user()}
            return {"ok": True, "user": cloud.firebase().auth.lookup()}
        except cloud.CloudError as error:
            return error.as_dict()

    @api.export
    def list_files(payload):
        payload = payload or {}
        provider = payload.get("provider", "supabase")
        try:
            if provider == "supabase":
                bucket = payload.get("bucket") or ""
                if not bucket:
                    return {"ok": True, "buckets": cloud.supabase().storage.list_buckets()}
                return {"ok": True,
                        "files": cloud.supabase().storage.list(bucket, payload.get("prefix", ""))}
            return {"ok": True, "files": cloud.firebase().storage.list(payload.get("prefix", ""))}
        except cloud.CloudError as error:
            return error.as_dict()

    @api.export
    def upload(payload):
        """Sends a workspace file up."""
        payload = payload or {}
        provider = payload.get("provider", "supabase")
        local = resolve(payload.get("local", ""))
        if not os.path.isfile(local):
            return {"ok": False, "error": f"no such file: {local}"}
        remote = payload.get("remote") or os.path.basename(local)
        try:
            if provider == "supabase":
                result = cloud.supabase().storage.upload_file(
                    payload.get("bucket", ""), remote, local,
                )
            else:
                result = cloud.firebase().storage.upload_file(remote, local)
            api.toast(f"Uploaded {os.path.basename(local)}")
            return {"ok": True, "result": result}
        except cloud.CloudError as error:
            return error.as_dict()

    @api.export
    def download(payload):
        """Brings a file down into the workspace."""
        payload = payload or {}
        provider = payload.get("provider", "supabase")
        remote = payload.get("remote", "")
        local = resolve(payload.get("local") or os.path.basename(remote) or "download.bin")
        try:
            if provider == "supabase":
                result = cloud.supabase().storage.download_to(
                    payload.get("bucket", ""), remote, local,
                )
            else:
                result = cloud.firebase().storage.download_to(remote, local)
            api.toast(f"Saved {os.path.basename(local)}")
            return {"ok": True, "result": result}
        except cloud.CloudError as error:
            return error.as_dict()

    @api.export
    def realtime(payload):
        """Read or write the Firebase Realtime Database."""
        payload = payload or {}
        action = payload.get("action", "get")
        path = payload.get("path", "")
        try:
            rtdb = cloud.firebase().rtdb
            if action == "get":
                return {"ok": True, "value": rtdb.get(path)}
            value = parse_json(payload.get("json") or "null", "the value")
            if action == "set":
                return {"ok": True, "value": rtdb.set(path, value)}
            if action == "push":
                return {"ok": True, "value": rtdb.push(path, value)}
            if action == "update":
                return {"ok": True, "value": rtdb.update(path, value)}
            if action == "delete":
                return {"ok": True, "value": rtdb.delete(path)}
            return {"ok": False, "error": f"unknown action {action!r}"}
        except cloud.CloudError as error:
            return error.as_dict()
        except ValueError as error:
            return {"ok": False, "error": str(error)}

    @api.export
    def call_function(payload):
        """An RPC on Supabase, or nothing on Firebase - it has no equivalent here."""
        payload = payload or {}
        try:
            body = parse_json(payload.get("json") or "{}", "the payload")
            return {"ok": True,
                    "result": cloud.supabase().rpc(payload.get("name", ""), body)}
        except cloud.CloudError as error:
            return error.as_dict()
        except ValueError as error:
            return {"ok": False, "error": str(error)}

    # ----------------------------------------------------- console commands

    @api.command("cloud", help="cloud - what is connected, and how to connect it")
    def cloud_command(argument):
        state = cloud.status()
        lines = []
        for name in ("supabase", "firebase"):
            row = state[name]
            if row["configured"]:
                who = f", signed in as {row['user']}" if row["signed_in"] else ""
                target = row.get("url") or row.get("project_id")
                lines.append(f"{name}: {target}{who}")
            else:
                lines.append(f"{name}: not configured")
        lines.append("")
        lines.append("Connect one in More -> Cloud, or from a script:")
        lines.append("  import pycmd_cloud")
        lines.append("  pycmd_cloud.configure('supabase', url='https://x.supabase.co', key='...')")
        return "\n".join(lines)

    @api.command("sb", help="sb select|insert|delete|rpc|signin|signout|buckets|up|down")
    def supabase_command(argument):
        args = argument.split()
        if not args:
            return "sb <what> ... - try: sb select notes 5"
        what = args[0]
        try:
            client = cloud.supabase()
            if what == "select":
                if len(args) < 2:
                    return "sb select <table> [limit]"
                limit = int(args[2]) if len(args) > 2 and args[2].isdigit() else 10
                return pretty(client.table(args[1]).limit(limit).run())
            if what == "insert":
                if len(args) < 3:
                    return 'sb insert <table> {"col": "value"}'
                return pretty(client.insert(args[1], parse_json(" ".join(args[2:]), "the row")))
            if what == "delete":
                if len(args) < 3 or "=" not in args[2]:
                    return "sb delete <table> <column>=<value>"
                column, value = args[2].split("=", 1)
                return pretty(client.delete(args[1], **{column: _coerce(value)}))
            if what == "rpc":
                if len(args) < 2:
                    return "sb rpc <function> [json]"
                body = parse_json(" ".join(args[2:]) or "{}", "the payload")
                return pretty(client.rpc(args[1], body))
            if what == "count":
                if len(args) < 2:
                    return "sb count <table>"
                return f"{client.table(args[1]).count()} rows"
            if what == "signin":
                if len(args) < 3:
                    return "sb signin <email> <password>"
                client.auth.sign_in(args[1], args[2])
                return f"Signed in as {args[1]}"
            if what == "signout":
                client.auth.sign_out()
                return "Signed out"
            if what == "whoami":
                return pretty(client.auth.user())
            if what == "buckets":
                return pretty(client.storage.list_buckets())
            if what == "ls":
                if len(args) < 2:
                    return "sb ls <bucket> [prefix]"
                return pretty(client.storage.list(args[1], args[2] if len(args) > 2 else ""))
            if what == "up":
                if len(args) < 3:
                    return "sb up <bucket> <file> [remote-name]"
                local = resolve(args[2])
                remote = args[3] if len(args) > 3 else os.path.basename(local)
                return pretty(client.storage.upload_file(args[1], remote, local))
            if what == "down":
                if len(args) < 3:
                    return "sb down <bucket> <remote> [local]"
                local = resolve(args[3] if len(args) > 3 else os.path.basename(args[2]))
                return pretty(client.storage.download_to(args[1], args[2], local))
            if what == "ping":
                return pretty(client.ping())
            return f"sb: no idea what {what!r} means. Try select, insert, delete, rpc, up, down."
        except (cloud.CloudError, ValueError) as error:
            return f"sb: {error}"

    @api.command("fb", help="fb get|set|list|query|del|rt|signin|up|down")
    def firebase_command(argument):
        args = argument.split()
        if not args:
            return "fb <what> ... - try: fb list notes"
        what = args[0]
        try:
            client = cloud.firebase()
            if what == "get":
                if len(args) < 2:
                    return "fb get <collection/document>"
                return pretty(client.firestore.get(args[1]))
            if what == "set":
                if len(args) < 3:
                    return 'fb set <collection/document> {"field": "value"}'
                return pretty(client.firestore.set(args[1],
                                                   parse_json(" ".join(args[2:]), "the document")))
            if what == "update":
                if len(args) < 3:
                    return 'fb update <collection/document> {"field": "value"}'
                return pretty(client.firestore.update(
                    args[1], parse_json(" ".join(args[2:]), "the changes")))
            if what == "list":
                if len(args) < 2:
                    return "fb list <collection> [limit]"
                limit = int(args[2]) if len(args) > 2 and args[2].isdigit() else 20
                return pretty(client.firestore.list(args[1], page_size=limit))
            if what == "query":
                if len(args) < 5:
                    return "fb query <collection> <field> <op> <value>"
                rows = client.firestore.query(
                    args[1], where=[(args[2], args[3], _coerce(args[4]))],
                )
                return pretty(rows)
            if what == "del":
                if len(args) < 2:
                    return "fb del <collection/document>"
                return pretty(client.firestore.delete(args[1]))
            if what == "rt":
                if len(args) < 3:
                    return "fb rt get|set|push|update|delete <path> [json]"
                action, path = args[1], args[2]
                rest = " ".join(args[3:])
                if action == "get":
                    return pretty(client.rtdb.get(path))
                value = parse_json(rest or "null", "the value")
                return pretty(getattr(client.rtdb, action)(path, value))
            if what == "signin":
                if len(args) < 3:
                    return "fb signin <email> <password>"
                client.auth.sign_in(args[1], args[2])
                return f"Signed in as {args[1]}"
            if what == "signout":
                client.auth.sign_out()
                return "Signed out"
            if what == "whoami":
                return pretty(client.auth.lookup())
            if what == "ls":
                return pretty(client.storage.list(args[1] if len(args) > 1 else ""))
            if what == "up":
                if len(args) < 2:
                    return "fb up <file> [remote-name]"
                local = resolve(args[1])
                remote = args[2] if len(args) > 2 else os.path.basename(local)
                return pretty(client.storage.upload_file(remote, local))
            if what == "down":
                if len(args) < 2:
                    return "fb down <remote> [local]"
                local = resolve(args[2] if len(args) > 2 else os.path.basename(args[1]))
                return pretty(client.storage.download_to(args[1], local))
            return f"fb: no idea what {what!r} means. Try get, set, list, query, rt, up, down."
        except (cloud.CloudError, ValueError) as error:
            return f"fb: {error}"


def _coerce(value):
    """Turns a typed-in word into the value it obviously means."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "none"):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text
