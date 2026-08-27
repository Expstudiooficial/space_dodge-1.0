"""Server Pro - the Servers tab, with the parts that were missing.

What the tab does on its own is start things and stop them. What you actually
want while something is running is to know whether it is *working*: whether the
port answers, how long it has been up, how many requests it has taken, and a
way to restart it without retyping the form. That is what this adds, in a panel
of its own and as console commands, because half the time your hands are
already in the console.

Nothing here is privileged. It imports the same modules the app does, which is
exactly what any plugin can do - see PLUGINS.md, and the warning that goes with
it.
"""

import os
import socket
import time

import pycmd_servers as servers

# What we started, so restart knows how to start it again. The app's own
# listing forgets a server the moment it stops, which is the one moment you
# most want to bring it back.
_history = {}


def setup(api):
    api.log("Server Pro is watching the Servers tab")

    # -------------------------------------------------------------- helpers

    def health(row):
        """Does the port actually answer? A running thread is not a service."""
        port = row.get("port") or 0
        if not port:
            return "no port"
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.4)
        try:
            probe.connect(("127.0.0.1", int(port)))
            return "answering"
        except OSError:
            return "not answering"
        finally:
            probe.close()

    def board():
        rows = []
        for row in servers.listing():
            row = dict(row)
            row["health"] = health(row)
            row["uptime_text"] = _uptime(row.get("uptime", 0))
            remembered = _history.get(row["handle"])
            row["restartable"] = bool(remembered)
            rows.append(row)
        return rows

    def remember(row):
        _history[row["handle"]] = {
            "kind": row.get("kind", ""),
            "target": row.get("target", ""),
            "port": row.get("port", 0),
            "host": row.get("host", "0.0.0.0"),
            "label": row.get("label", ""),
        }

    def start_again(spec):
        if spec["kind"] == "static":
            return servers.start_static(
                spec["target"], port=spec["port"] or 8000,
                host=spec["host"], label=spec["label"],
            )
        return servers.start_file(
            spec["target"], port=spec["port"], host=spec["host"], label=spec["label"],
        )

    def find(handle):
        for row in servers.listing():
            if row["handle"] == handle:
                return row
        return None

    # ------------------------------------------------------- panel exports

    @api.export
    def board_now(payload=None):
        """Everything running, plus whether each one is answering."""
        rows = board()
        return {
            "servers": rows,
            "address": servers.local_ip(),
            "running": sum(1 for row in rows if row["status"] == "running"),
            "at": time.strftime("%H:%M:%S"),
        }

    @api.export
    def stop_one(payload):
        handle = (payload or {}).get("handle", "")
        row = find(handle)
        if row is not None:
            remember(row)
        return servers.stop(handle)

    @api.export
    def kill_one(payload):
        handle = (payload or {}).get("handle", "")
        row = find(handle)
        if row is not None:
            remember(row)
        return servers.kill(handle)

    @api.export
    def restart_one(payload):
        """Stop it, then start the same thing again on the same port."""
        handle = (payload or {}).get("handle", "")
        row = find(handle)
        if row is not None:
            remember(row)
        spec = _history.get(handle)
        if spec is None:
            return {"ok": False, "error": "nothing remembered about that one"}

        result = servers.stop(handle)
        if not result.get("ok"):
            servers.kill(handle)
        # The socket needs a moment to come back, or the restart races the
        # shutdown and fails on a port that is about to be free.
        for _ in range(20):
            if not spec["port"] or servers.port_available(spec["port"], spec["host"]):
                break
            time.sleep(0.1)
        return start_again(spec)

    @api.export
    def free_ports(payload=None):
        start = int((payload or {}).get("from") or 8000)
        found = []
        candidate = start
        while len(found) < 8 and candidate < start + 200:
            if servers.port_available(candidate):
                found.append(candidate)
            candidate += 1
        return {"ports": found, "from": start}

    @api.export
    def write_index(payload):
        """Writes an index page listing a served folder that has none.

        The doctor offers to *rename* a page into place when there is exactly
        one. This is the other case: a folder full of files and no page at all.
        """
        folder = (payload or {}).get("folder", "")
        if not os.path.isdir(folder):
            return {"ok": False, "error": "that folder is not there"}
        target = os.path.join(folder, "index.html")
        if os.path.exists(target):
            return {"ok": False, "error": "index.html already exists"}

        names = sorted(
            name for name in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, name)) and not name.startswith(".")
        )
        links = "\n".join(
            f'    <li><a href="{name}">{name}</a></li>' for name in names
        )
        page = (
            "<!doctype html>\n<html>\n<head>\n<meta charset='utf-8'>\n"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
            f"<title>{os.path.basename(folder) or 'Files'}</title>\n"
            "<style>body{font:16px/1.6 system-ui,sans-serif;margin:2rem;}"
            "li{margin:.3rem 0}</style>\n</head>\n<body>\n"
            f"  <h1>{os.path.basename(folder) or 'Files'}</h1>\n  <ul>\n{links}\n  </ul>\n"
            "</body>\n</html>\n"
        )
        try:
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(page)
        except OSError as error:
            return {"ok": False, "error": str(error)}
        api.toast("Wrote index.html")
        return {"ok": True, "files": len(names), "path": target}

    # ----------------------------------------------------- console commands

    @api.command("servers", help="List everything running, with health")
    def servers_command(argument):
        rows = board()
        if not rows:
            return "Nothing is running."
        lines = [f"{len(rows)} server(s), local address {servers.local_ip()}"]
        for row in rows:
            lines.append(
                f"  {row['handle']}  {row['label'][:28]:<28} {row['status']:<8} "
                f"{row['health']:<14} up {row['uptime_text']}  {row.get('url', '')}"
            )
        return "\n".join(lines)

    @api.command("serve", help="serve <file-or-folder> [port] - start anything")
    def serve_command(argument):
        args = argument.split()
        if not args:
            return "serve <file-or-folder> [port]"
        target = args[0]
        if not os.path.isabs(target):
            target = api.workspace_path(target)
        port = int(args[1]) if len(args) > 1 and args[1].isdigit() else 0

        if os.path.isdir(target):
            result = servers.start_static(target, port=port or servers.suggest_port(8000))
        elif os.path.isfile(target):
            plan = servers.how_to_run(target)
            result = servers.start_file(target, port=port)
            if result.get("ok"):
                result["note"] = plan["note"]
        else:
            return f"No such file or folder: {target}"

        if not result.get("ok"):
            return f"Could not start it: {result.get('error', '')}"
        note = result.get("note", "")
        return (f"Started {result['handle']} - {result.get('url') or 'no port'}"
                + (f"\n{note}" if note else ""))

    @api.command("restart", help="restart <handle|all> - stop it and start it again")
    def restart_command(argument):
        args = argument.split()
        if not args:
            return "restart <handle|all>"
        handles = [row["handle"] for row in servers.listing()] if args[0] == "all" else [args[0]]
        if not handles:
            return "Nothing is running."
        lines = []
        for handle in handles:
            result = restart_one({"handle": handle})
            lines.append(
                f"{handle}: restarted as {result['handle']}" if result.get("ok")
                else f"{handle}: {result.get('error', 'could not restart')}"
            )
        return "\n".join(lines)

    @api.command("shut", help="shut <handle|all> - stop, then kill if it will not go")
    def shut_command(argument):
        args = argument.split()
        if not args:
            return "shut <handle|all>"
        handles = [row["handle"] for row in servers.listing()] if args[0] == "all" else [args[0]]
        if not handles:
            return "Nothing is running."
        lines = []
        for handle in handles:
            result = servers.stop(handle)
            if result.get("ok"):
                lines.append(f"{handle}: stopped")
                continue
            killed = servers.kill(handle)
            lines.append(
                f"{handle}: killed" + (" (thread still finishing)" if killed.get("detached") else "")
            )
        return "\n".join(lines)

    @api.command("ports", help="ports [from] - which ports are free")
    def ports_command(argument):
        args = argument.split()
        start = int(args[0]) if args and args[0].isdigit() else 8000
        found = free_ports({"from": start})["ports"]
        return "Free from {}: {}".format(start, ", ".join(str(p) for p in found))

    # -------------------------------------------------------------- events

    @api.on("server_started")
    def on_started(event):
        handle = (event or {}).get("handle", "")
        row = find(handle)
        if row is None:
            return
        remember(row)
        api.log(f"{row['label']} is up", row.get("url", ""))

    @api.on("server_stopped")
    def on_stopped(event):
        handle = (event or {}).get("handle", "")
        if handle in _history:
            api.log(f"{handle} stopped; Server Pro can restart it")


def _uptime(seconds):
    seconds = int(seconds or 0)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
