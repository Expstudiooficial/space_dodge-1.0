"""The Python half of a panel plugin.

Everything decorated with @api.export can be called from ui.html with
`await pycmd.call('name', payload)`.
"""

import os


def setup(api):
    api.log("workspace stats is ready")

    @api.export
    def scan(payload=None):
        pattern = (payload or {}).get("pattern", "*")
        rows = []
        total_lines = 0
        total_bytes = 0

        for path in api.files(pattern):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    lines = sum(1 for _ in handle)
                size = os.path.getsize(path)
            except OSError:
                continue
            total_lines += lines
            total_bytes += size
            rows.append({
                "name": os.path.relpath(path, api.workspace_path()),
                "lines": lines,
                "bytes": size,
            })

        rows.sort(key=lambda row: -row["lines"])
        return {
            "files": rows[:40],
            "count": len(rows),
            "lines": total_lines,
            "kilobytes": round(total_bytes / 1024, 1),
        }

    @api.export
    def greet_from_panel(payload):
        name = (payload or {}).get("name", "there")
        api.toast(f"hello {name}, from Python")
        return f"Python says hello, {name}"
