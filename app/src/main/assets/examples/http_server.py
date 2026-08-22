"""Serve the workspace folder over your Wi-Fi network.

Run it, then open the printed URL on any device on the same network.
Stop it from the Servers tab.
"""

import http.server
import os
import socketserver

PORT = 8000
DIRECTORY = os.getcwd()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)


class ReusableServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


with ReusableServer(("0.0.0.0", PORT), Handler) as httpd:
    print(f"Serving {DIRECTORY} on port {PORT}")
    print("Press Stop to shut it down.")
    httpd.serve_forever()
