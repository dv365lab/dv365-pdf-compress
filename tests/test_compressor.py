from io import BytesIO

import pikepdf
import pymupdf
import pytest
from PIL import Image

from compressor import CompressionError, compress_pdf


@pytest.fixture
def rich_pdf():
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((40, 50), "Lossless PDF: searchable text and vectors", fontsize=16)
    for y in range(90, 320, 4):
        page.draw_line((40, y), (560, y), color=(0.2, 0.4, 0.7), width=0.5)
    image = Image.new("RGB", (800, 400), (242, 246, 250))
    for x in range(100, 700):
        image.putpixel((x, 200), (0, 90, 160))
    image_bytes = BytesIO()
    image.save(image_bytes, format="PNG")
    page.insert_image(pymupdf.Rect(40, 360, 560, 620), stream=image_bytes.getvalue())
    jpeg_bytes = BytesIO()
    image.save(jpeg_bytes, format="JPEG", quality=93)
    page.insert_image(pymupdf.Rect(40, 640, 240, 740), stream=jpeg_bytes.getvalue())
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(40, 30, 560, 55),
                      "uri": "https://example.com"})
    page.add_text_annot((570, 100), "Keep this annotation")
    widget = pymupdf.Widget()
    widget.field_name = "name"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.field_value = "Keep this form value"
    widget.rect = pymupdf.Rect(300, 650, 560, 685)
    page.add_widget(widget)
    page = doc.new_page(width=600, height=800)
    page.insert_text((40, 50), "Second page", fontsize=18)
    page.set_rotation(90)
    doc.set_toc([[1, "Chapter 1", 1], [1, "Chapter 2", 2]])
    doc.set_metadata({"title": "Preserve metadata", "author": "DV365"})
    doc.embfile_add("notes.txt", b"Attachment must survive", filename="notes.txt")
    data = doc.tobytes(garbage=0, deflate=False)
    doc.close()
    return data


def run_compression(tmp_path, data):
    source = tmp_path / "source.pdf"
    target = tmp_path / "result.pdf"
    source.write_bytes(data)
    result = compress_pdf(source, target)
    return result, result.path.read_bytes()


def test_lossless_rendering_and_document_features(tmp_path, rich_pdf):
    result, output = run_compression(tmp_path, rich_pdf)
    assert result.output_size < result.original_size * 0.5
    assert result.status == "compressed"
    assert result.pages == 2
    original = pymupdf.open(stream=rich_pdf, filetype="pdf")
    compressed = pymupdf.open(stream=output, filetype="pdf")
    assert compressed.get_toc() == original.get_toc()
    assert compressed.metadata["title"] == original.metadata["title"]
    assert compressed.embfile_get("notes.txt") == b"Attachment must survive"
    for old, new in zip(original, compressed):
        assert old.get_text() == new.get_text()
        assert old.rect == new.rect
        assert old.rotation == new.rotation
        # Structural optimization may renumber PDF objects; compare link behavior.
        assert [{k: v for k, v in link.items() if k != "xref"} for link in old.get_links()] == [
            {k: v for k, v in link.items() if k != "xref"} for link in new.get_links()]
        assert [a.info for a in old.annots()] == [a.info for a in new.annots()]
        assert [(w.field_name, w.field_value) for w in old.widgets()] == [
            (w.field_name, w.field_value) for w in new.widgets()]
        for zoom in (1, 2):
            before = old.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
            after = new.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
            assert (before.width, before.height, before.samples) == (
                after.width, after.height, after.samples)
    original.close()
    compressed.close()
    with pikepdf.open(BytesIO(rich_pdf)) as before, pikepdf.open(BytesIO(output)) as after:
        def images(pdf):
            return [obj for obj in pdf.objects if isinstance(obj, pikepdf.Stream)
                    and obj.get("/Subtype") == pikepdf.Name.Image]
        old_images, new_images = images(before), images(after)
        assert len(old_images) == len(new_images) == 2
        for old, new in zip(old_images, new_images):
            assert (old.Width, old.Height) == (new.Width, new.Height)
            if old.get("/Filter") == pikepdf.Name.DCTDecode:
                assert old.read_raw_bytes() == new.read_raw_bytes()
            else:
                assert old.read_bytes() == new.read_bytes()


def test_never_returns_larger_file(tmp_path, rich_pdf):
    _, optimized = run_compression(tmp_path, rich_pdf)
    result, output = run_compression(tmp_path, optimized)
    assert len(output) <= len(optimized)
    if result.status == "unchanged":
        assert output == optimized


def test_encrypted_pdf_is_rejected(tmp_path, rich_pdf):
    encrypted = BytesIO()
    with pikepdf.open(BytesIO(rich_pdf)) as pdf:
        pdf.save(encrypted, encryption=pikepdf.Encryption(owner="owner", user="secret"))
    with pytest.raises(CompressionError, match="加密"):
        run_compression(tmp_path, encrypted.getvalue())


def test_empty_password_encryption_is_also_rejected(tmp_path, rich_pdf):
    encrypted = BytesIO()
    with pikepdf.open(BytesIO(rich_pdf)) as pdf:
        pdf.save(encrypted, encryption=pikepdf.Encryption(owner="owner", user=""))
    with pytest.raises(CompressionError, match="加密"):
        run_compression(tmp_path, encrypted.getvalue())


def test_signed_pdf_is_returned_byte_for_byte(tmp_path, rich_pdf):
    signed = BytesIO()
    with pikepdf.open(BytesIO(rich_pdf)) as pdf:
        signature = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Sig, ByteRange=[0, 100, 200, 100], Contents=b"test-signature"))
        field = pdf.make_indirect(pikepdf.Dictionary(
            FT=pikepdf.Name.Sig, T="Signature1", V=signature))
        pdf.Root.AcroForm.Fields.append(field)
        pdf.save(signed)
    data = signed.getvalue()
    result, output = run_compression(tmp_path, data)
    assert result.status == "signed"
    assert output == data


@pytest.mark.parametrize("data", [b"", b"not a PDF", b"%PDF-1.7\ntruncated"])
def test_invalid_pdf_is_rejected(tmp_path, data):
    with pytest.raises(CompressionError):
        run_compression(tmp_path, data)
