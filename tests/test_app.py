from io import BytesIO

import pytest

from app import create_app


@pytest.fixture
def app():
    return create_app({"TESTING": True, "MAX_CONTENT_LENGTH": 2 * 1024 * 1024})


@pytest.fixture
def client(app):
    return app.test_client()


def token(app):
    return {"X-Request-Token": app.config["REQUEST_TOKEN"]}


def small_pdf():
    import pikepdf
    output = BytesIO()
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page()
        pdf.save(output)
    return output.getvalue()


def test_home_and_health(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "拖拽" in response.get_data(as_text=True)
    assert client.get("/api/health").json["app"] == "dv365-pdf-compress"


def test_single_file_download(client, app):
    source = small_pdf()
    response = client.post("/api/compress", headers=token(app),
                           data={"file": (BytesIO(source), "测试文档.pdf")})
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF-")
    assert len(response.data) <= len(source)
    assert response.headers["X-Original-Size"] == str(len(source))
    assert response.headers["X-Page-Count"] == "1"
    assert "filename*=UTF-8''" in response.headers["Content-Disposition"]
    response.close()


def test_missing_and_multiple_files(client, app):
    assert client.post("/api/compress", headers=token(app)).status_code == 400
    response = client.post("/api/compress", headers=token(app), data={
        "file": [(BytesIO(small_pdf()), "one.pdf"), (BytesIO(small_pdf()), "two.pdf")]})
    assert response.status_code == 400
    assert "一个" in response.json["error"]


@pytest.mark.parametrize("data,name", [(b"junk", "wrong.pdf"), (b"junk", "wrong.txt")])
def test_bad_file(client, app, data, name):
    response = client.post("/api/compress", headers=token(app),
                           data={"file": (BytesIO(data), name)})
    assert response.status_code == 400
    assert "error" in response.json


def test_request_size_limit(client, app):
    response = client.post("/api/compress", headers=token(app), data={
        "file": (BytesIO(b"x" * (2 * 1024 * 1024 + 1)), "large.pdf")})
    assert response.status_code == 413
    assert "error" in response.json


def test_local_request_protection(client, app):
    assert client.post("/api/compress").status_code == 403
    assert client.get("/", headers={"Host": "untrusted.example"}).status_code == 400


def test_temp_files_removed_after_download(client, app, tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    response = client.post("/api/compress", headers=token(app), data={
        "file": (BytesIO(small_pdf()), "one.pdf")})
    assert response.status_code == 200
    assert response.data
    response.close()
    assert list(tmp_path.iterdir()) == []
