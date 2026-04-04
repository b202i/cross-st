import subprocess
import sys
import os
from http.server import SimpleHTTPRequestHandler
import socketserver
import markdown
import threading
import webbrowser

"""This server is currently unused, it is a candidate to replace grip.
While it is a bit messey, grip displays updates to the source.
The user can make changes to the source and immediately see
updated Markdown. This python server only serves HTML, requiring
a markdown conversion."""

class MarkdownServer:
    def __init__(self, port=8000):
        self.port = port
        self.httpd = None
        self.server_thread = None
        self.html_content = ""

    def start_server(self, html_content):
        """Start the HTTP server with the given HTML content."""
        self.html_content = html_content

        class CustomHandler(SimpleHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(self.html_content.encode())

        # Start the server
        self.httpd = socketserver.TCPServer(("", self.port), CustomHandler)
        print(f"Serving at http://localhost:{self.port}")

        # Run server in a separate thread
        self.server_thread = threading.Thread(target=self.httpd.serve_forever)
        self.server_thread.daemon = True  # Still daemon for safety if stop fails
        self.server_thread.start()

    def stop_server(self):
        """Stop the HTTP server cleanly."""
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            if self.server_thread:
                self.server_thread.join(timeout=1)  # Wait for thread to finish
            print("Server stopped.")
        self.httpd = None
        self.server_thread = None

    def is_running(self):
        """Check if the server is currently running."""
        return self.httpd is not None and self.server_thread is not None


# Dark mode CSS (simple example)
DARK_MODE_CSS = """
<style>
    body {
        font-family: Arial, sans-serif;
        margin: 20px;
    }
    @media (prefers-color-scheme: dark) {
        body {
            background-color: #1a1a1a;
            color: #f0f0f0;
        }
        a {
            color: #4da8da;
        }
        h1, h2, h3, h4, h5, h6 {
            color: #ffffff;
        }
    }
    @media (prefers-color-scheme: light) {
        body {
            background-color: #ffffff;
            color: #000000;
        }
        a {
            color: #1a73e8;
        }
    }
</style>
"""
