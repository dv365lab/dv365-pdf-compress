import errno
import json
from pathlib import Path
from queue import Queue
import socket
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import urllib.request

import pytest
from waitress import create_server

import app


class Parser:
    def __init__(self, no_browser=False, port=8765):
        self.no_browser = no_browser
        self.port = port

    def add_argument(self, *_args, **_kw):
        pass

    def parse_args(self):
        return SimpleNamespace(port=self.port, no_browser=self.no_browser)


def test_occupied_port_uses_os_assigned_port_and_opens_actual_url(monkeypatch, capsys):
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        preferred = occupied.getsockname()[1]
        monkeypatch.setattr(app, "argparse", SimpleNamespace(
            ArgumentParser=lambda **_kw: Parser(port=preferred)))
        open_browser = Mock()
        monkeypatch.setattr(app.webbrowser, "open", open_browser)

        class ImmediateTimer:
            def __init__(self, _delay, callback, args):
                self.callback, self.args = callback, args

            def start(self):
                self.callback(*self.args)

        monkeypatch.setattr(app.threading, "Timer", ImmediateTimer)
        servers = []

        def make_server(application, **kwargs):
            server = create_server(application, **kwargs)
            servers.append(server)
            monkeypatch.setattr(server, "run", Mock())
            return server

        monkeypatch.setattr(app, "create_server", make_server)
        app.main()
        actual = int(servers[0].effective_port)
        assert actual != preferred
        assert servers[0].effective_host == "127.0.0.1"
        url = f"http://127.0.0.1:{actual}"
        open_browser.assert_called_once_with(url)
        assert url in capsys.readouterr().out
        servers[0].run.assert_called_once()
        servers[0].task_dispatcher.shutdown()


def test_free_preferred_port_is_used():
    with app.bind_local_socket(0) as probe:
        preferred = probe.getsockname()[1]
    with app.bind_local_socket(preferred) as bound:
        assert bound.getsockname() == ("127.0.0.1", preferred)


def test_busy_port_starts_reachable_server():
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        preferred = occupied.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, str(Path(app.__file__)), "--no-browser", "--port", str(preferred)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        lines = Queue()

        def read_output():
            for line in process.stdout:
                lines.put(line)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            first = lines.get(timeout=15)
            second = lines.get(timeout=15)
            assert f"Port {preferred} unavailable" in first
            url = second.strip().removeprefix("PDF compressor ready: ")
            assert url.startswith("http://127.0.0.1:")
            assert int(url.rsplit(":", 1)[1]) != preferred
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                url + "/api/health", timeout=5
            ) as response:
                assert json.load(response)["app"] == app.APP_ID
        finally:
            process.terminate()
            process.wait(timeout=10)
            reader.join(timeout=5)
            process.stdout.close()
            process.stderr.close()


def test_other_bind_errors_are_not_hidden(monkeypatch):
    sock = Mock()
    sock.bind.side_effect = OSError(errno.ENETDOWN, "network unavailable")
    monkeypatch.setattr(app.socket, "socket", lambda *_args: sock)
    with pytest.raises(OSError) as exc:
        app.bind_local_socket(8765)
    assert exc.value.errno == errno.ENETDOWN
    assert sock.bind.call_count == 1
    sock.close.assert_called_once()


def test_server_creation_failure_closes_socket(monkeypatch):
    sock = Mock()
    sock.getsockname.return_value = ("127.0.0.1", 8765)
    monkeypatch.setattr(app, "bind_local_socket", lambda _port: sock)
    monkeypatch.setattr(app, "argparse", SimpleNamespace(
        ArgumentParser=lambda **_kw: Parser(no_browser=True)))
    monkeypatch.setattr(app, "create_server", Mock(side_effect=RuntimeError("failure")))
    with pytest.raises(RuntimeError, match="failure"):
        app.main()
    sock.close.assert_called_once()
