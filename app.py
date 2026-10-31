"""Local-only web GUI and streaming, temporary-file-backed compression endpoint."""

import argparse
import errno
import hmac
import logging
import os
import secrets
import socket
import tempfile
import threading
import webbrowser
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from waitress import create_server
from werkzeug.exceptions import RequestEntityTooLarge

from compressor import CompressionError, compress_pdf

APP_ID = "dv365-pdf-compress"
MAX_FILE_BYTES = 512 * 1024 * 1024


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_FILE_BYTES + 1024 * 1024,
        TRUSTED_HOSTS=["127.0.0.1", "localhost"],
        REQUEST_TOKEN=secrets.token_urlsafe(32),
    )
    if config:
        app.config.update(config)

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @app.get("/")
    def home():
        return render_template("index.html", request_token=app.config["REQUEST_TOKEN"])

    @app.get("/api/health")
    def health():
        return jsonify(app=APP_ID, version=1)

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        return jsonify(error="文件过大，单个 PDF 最大支持 512 MB。"), 413

    @app.post("/api/compress")
    def compress():
        if not hmac.compare_digest(request.headers.get("X-Request-Token", ""),
                                   app.config["REQUEST_TOKEN"]):
            return jsonify(error="页面已失效，请刷新页面后重试。"), 403
        uploads = list(request.files.items(multi=True))
        if len(uploads) != 1 or uploads[0][0] != "file":
            return jsonify(error="每次请选择一个 PDF 文件。"), 400
        uploaded = uploads[0][1]
        if not uploaded.filename or not uploaded.filename.lower().endswith(".pdf"):
            return jsonify(error="请选择 .pdf 格式的文件。"), 400
        temporary = tempfile.TemporaryDirectory(prefix="dv365-pdf-")
        directory = Path(temporary.name)
        try:
            source = directory / "input.pdf"
            uploaded.save(source)
            if source.stat().st_size > MAX_FILE_BYTES:
                temporary.cleanup()
                return too_large(None)
            result = compress_pdf(source, directory / "compressed.pdf")
        except CompressionError as exc:
            temporary.cleanup()
            return jsonify(error=str(exc)), 400
        except Exception:
            temporary.cleanup()
            app.logger.exception("PDF compression failed")
            return jsonify(error="处理失败，请检查可用磁盘空间，或换一个 PDF 后重试。"), 500

        @stream_with_context
        def download():
            try:
                with result.path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        yield chunk
            finally:
                temporary.cleanup()

        filename = uploaded.filename.replace("\\", "/").rsplit("/", 1)[-1]
        stem = "".join(c for c in filename[:-4] if ord(c) >= 32 and ord(c) != 127)[:160] or "document"
        suffix = "_compressed" if result.status == "compressed" else "_original"
        response = Response(download(), mimetype="application/pdf", headers={
            "Content-Disposition": f"attachment; filename=\"document{suffix}.pdf\"; "
                                   f"filename*=UTF-8''{quote(stem + suffix + '.pdf', safe='')}",
            "X-Original-Size": str(result.original_size),
            "X-Output-Size": str(result.output_size),
            "X-Page-Count": str(result.pages),
            "X-Compression-Status": result.status,
        })
        response.content_length = result.output_size
        response.call_on_close(temporary.cleanup)
        return response

    return app


def bind_local_socket(port):
    """Bind once and pass the same socket to Waitress, avoiding port selection races."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Windows SO_REUSEADDR can allow multiple listeners on the same port.
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE and not (
                os.name == "nt" and exc.errno == errno.EACCES
            ):
                raise
            # Port 0 asks the OS to select and atomically bind a free port.
            sock.bind(("127.0.0.1", 0))
        return sock
    except BaseException:
        sock.close()
        raise


def main():
    parser = argparse.ArgumentParser(description="DV365 local lossless PDF compressor")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    app = create_app()
    sock = bind_local_socket(args.port)
    port = sock.getsockname()[1]
    try:
        server = create_server(app, sockets=[sock], threads=2,
                               max_request_body_size=app.config["MAX_CONTENT_LENGTH"] + 1024 * 1024,
                               channel_timeout=600)
    except BaseException:
        sock.close()
        raise
    url = f"http://127.0.0.1:{port}"
    if port != args.port:
        print(f"Port {args.port} unavailable; using {port} instead.", flush=True)
    print(f"PDF compressor ready: {url}", flush=True)
    print("Keep this window open. Press Ctrl+C to stop.", flush=True)
    if not args.no_browser:
        timer = threading.Timer(0.5, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
    try:
        server.run()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
