"""Scheduler - run a script again every so often.

A server runs until you stop it. A script runs once. The thing in between -
"do this every five minutes for as long as the app is open" - had nowhere to
live, and writing `while True: sleep(300)` at the top of a script means you
cannot run that script any other way.

Each job is a thread that sleeps between runs, so a job that is between runs
costs nothing, and stopping one takes effect at the next tick rather than
whenever the sleep happens to end.

Jobs do not survive the app closing, and this says so rather than pretending
otherwise: Android gives an app no promise of being alive later, so a schedule
that claimed to be reliable would be lying.
"""

import os
import threading
import time
import traceback

_jobs = {}
_lock = threading.RLock()
_counter = 0


class Job:
    def __init__(self, job_id, path, seconds, label):
        self.id = job_id
        self.path = path
        self.seconds = seconds
        self.label = label
        self.runs = 0
        self.failures = 0
        self.last_run = 0.0
        self.last_status = "waiting"
        self.last_error = ""
        self.created = time.time()
        self.stop = threading.Event()
        self.thread = None

    def as_dict(self):
        due = max(0, int(self.seconds - (time.time() - self.last_run))) if self.last_run else 0
        return {
            "id": self.id,
            "label": self.label,
            "path": self.path,
            "every": self.seconds,
            "runs": self.runs,
            "failures": self.failures,
            "status": self.last_status,
            "error": self.last_error,
            "next_in": due,
            "alive": bool(self.thread and self.thread.is_alive()),
        }


def setup(api):
    api.log("Scheduler is ready")

    def resolve(path):
        return path if os.path.isabs(path) else api.workspace_path(path)

    def start(path, seconds, label=""):
        global _counter

        path = resolve(path)
        if not os.path.isfile(path):
            return {"ok": False, "error": f"no such file: {path}"}
        seconds = max(5, int(seconds))

        with _lock:
            _counter += 1
            job = Job(f"job{_counter}", path, seconds, label or os.path.basename(path))
            _jobs[job.id] = job

        def loop():
            import pycmd_runtime

            while not job.stop.is_set():
                job.last_run = time.time()
                job.runs += 1
                job.last_status = "running"
                try:
                    pycmd_runtime.exec_isolated(job.path)
                    job.last_status = "ok"
                    job.last_error = ""
                except BaseException as error:  # noqa: BLE001
                    job.failures += 1
                    job.last_status = "error"
                    job.last_error = f"{type(error).__name__}: {error}"
                    api.error(f"{job.label} failed", traceback.format_exc(limit=3))
                # wait() rather than sleep(): stopping a job should not have to
                # wait out the rest of an interval it is in the middle of.
                job.stop.wait(job.seconds)
            job.last_status = "stopped"

        job.thread = threading.Thread(target=loop, name=f"pycmd-{job.id}", daemon=True)
        job.thread.start()
        return {"ok": True, **job.as_dict()}

    def stop(job_id):
        with _lock:
            job = _jobs.get(job_id)
        if job is None:
            return {"ok": False, "error": "no such job"}
        job.stop.set()
        with _lock:
            _jobs.pop(job_id, None)
        return {"ok": True, "id": job_id}

    # -------------------------------------------------------- panel exports

    @api.export
    def jobs(payload=None):
        with _lock:
            rows = [job.as_dict() for job in _jobs.values()]
        return {"jobs": rows, "at": time.strftime("%H:%M:%S")}

    @api.export
    def add(payload):
        payload = payload or {}
        return start(
            payload.get("path", ""),
            payload.get("seconds", 300),
            payload.get("label", ""),
        )

    @api.export
    def remove(payload):
        return stop((payload or {}).get("id", ""))

    @api.export
    def remove_all(payload=None):
        with _lock:
            ids = list(_jobs)
        for job_id in ids:
            stop(job_id)
        return {"ok": True, "stopped": len(ids)}

    @api.export
    def run_now(payload):
        """Runs a job's script immediately, without disturbing its schedule."""
        with _lock:
            job = _jobs.get((payload or {}).get("id", ""))
        if job is None:
            return {"ok": False, "error": "no such job"}

        def once():
            import pycmd_runtime

            try:
                pycmd_runtime.exec_isolated(job.path)
            except BaseException as error:  # noqa: BLE001
                api.error(f"{job.label} failed", str(error))

        threading.Thread(target=once, daemon=True).start()
        return {"ok": True}

    # ------------------------------------------------------ console commands

    @api.command("every", help="every <seconds> <script> - run it again and again")
    def every_command(argument):
        args = argument.split()
        if len(args) < 2:
            return "every <seconds> <script>   e.g. every 300 backup.py"
        if not args[0].isdigit():
            return "the first argument is how many seconds to wait between runs"
        result = start(args[1], int(args[0]), " ".join(args[2:]))
        if not result.get("ok"):
            return result["error"]
        return (f"{result['id']}: {result['label']} every {result['every']}s. "
                f"Stop it with: jobs stop {result['id']}")

    @api.command("jobs", help="jobs [stop <id>|stop all] - what is scheduled")
    def jobs_command(argument):
        args = argument.split()
        if args and args[0] == "stop":
            if len(args) > 1 and args[1] == "all":
                return f"Stopped {remove_all()['stopped']} job(s)."
            if len(args) > 1:
                return "Stopped." if stop(args[1]).get("ok") else "No such job."
            return "jobs stop <id>, or jobs stop all"

        rows = jobs()["jobs"]
        if not rows:
            return "Nothing is scheduled. Try: every 300 backup.py"
        lines = [f"{len(rows)} job(s):"]
        for row in rows:
            lines.append(
                f"  {row['id']}  {row['label'][:24]:<24} every {row['every']}s  "
                f"{row['runs']} run(s), {row['failures']} failed  next in {row['next_in']}s"
            )
        return "\n".join(lines)
