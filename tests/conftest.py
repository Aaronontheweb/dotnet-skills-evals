"""External-service tests require explicit local opt-in; CI never spends API credits."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest


def pytest_addoption(parser):
    parser.addoption("--run-openrouter", action="store_true", help="Run paid OpenRouter integration tests locally")
    parser.addoption("--run-network", action="store_true", help="Run live public GitHub/symbol-server tests locally")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if item.get_closest_marker("openrouter") and (os.getenv("CI") or not config.getoption("--run-openrouter")):
            item.add_marker(pytest.mark.skip(reason="OpenRouter API tests are opt-in locally and disabled in CI"))
        if item.get_closest_marker("network") and (os.getenv("CI") or not config.getoption("--run-network")):
            item.add_marker(pytest.mark.skip(reason="Live public network tests require --run-network outside CI"))


@pytest.fixture
def serve_http():
    servers = []

    def create(routes):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def handle_request(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                requests.append({"method": self.command, "path": self.path,
                                 "headers": dict(self.headers), "body": body})
                value = routes.get(self.path, (404, {}, b"missing"))
                if callable(value):
                    value = value(requests[-1])
                status, headers, content = value
                if isinstance(content, (dict, list)):
                    content = json.dumps(content).encode()
                    headers = {"Content-Type": "application/json", **headers}
                elif isinstance(content, str):
                    content = content.encode()
                self.send_response(status)
                for key, data in headers.items():
                    self.send_header(key, data)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            do_GET = handle_request
            do_POST = handle_request

            def log_message(self, *args):
                pass  # Keep deterministic local-server tests quiet.

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}", requests=requests)

    yield create
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
