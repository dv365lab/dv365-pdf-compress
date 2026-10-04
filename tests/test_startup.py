from types import SimpleNamespace
from unittest.mock import Mock

import app


def test_repeated_start_opens_existing_app(monkeypatch):
    monkeypatch.setattr(app, "existing_app", lambda url: True)
    open_browser = Mock()
    create_server = Mock()
    monkeypatch.setattr(app.webbrowser, "open", open_browser)
    monkeypatch.setattr(app, "create_server", create_server)
    monkeypatch.setattr(app, "argparse", SimpleNamespace(ArgumentParser=lambda **_kw: Parser(False)))
    app.main()
    open_browser.assert_called_once_with("http://127.0.0.1:8765")
    create_server.assert_not_called()


class Parser:
    def __init__(self, no_browser):
        self.no_browser = no_browser

    def add_argument(self, *_args, **_kw):
        pass

    def parse_args(self):
        return SimpleNamespace(port=8765, no_browser=self.no_browser)


def test_new_server_switches_busy_port_and_automatically_opens_browser(monkeypatch):
    monkeypatch.setattr(app, "existing_app", lambda _url: False)
    server = Mock()
    create_server = Mock(side_effect=[OSError("occupied"), server])
    open_browser = Mock()
    monkeypatch.setattr(app, "create_server", create_server)
    monkeypatch.setattr(app.webbrowser, "open", open_browser)
    monkeypatch.setattr(app, "argparse", SimpleNamespace(ArgumentParser=lambda **_kw: Parser(False)))

    class ImmediateTimer:
        def __init__(self, _delay, callback, args):
            self.callback, self.args = callback, args

        def start(self):
            self.callback(*self.args)

    monkeypatch.setattr(app.threading, "Timer", ImmediateTimer)
    app.main()
    assert create_server.call_args.kwargs["host"] == "127.0.0.1"
    assert create_server.call_args.kwargs["port"] == 8766
    open_browser.assert_called_once_with("http://127.0.0.1:8766")
    server.run.assert_called_once()
    server.close.assert_called_once()
