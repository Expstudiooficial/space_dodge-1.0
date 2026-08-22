"""A tiny JSON API, running on your phone.

Flask is bundled with PyCmd, so this needs no install.
"""

import platform
import time

from flask import Flask, jsonify

app = Flask(__name__)
STARTED = time.time()


@app.get("/")
def index():
    return jsonify(
        service="PyCmd demo API",
        uptime_seconds=round(time.time() - STARTED, 1),
        device=platform.machine(),
    )


@app.get("/echo/<message>")
def echo(message: str):
    return jsonify(you_said=message, length=len(message))


if __name__ == "__main__":
    # threaded=False keeps the reloader out of the way inside the app.
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
