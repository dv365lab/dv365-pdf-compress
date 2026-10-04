"""Conservative structural PDF compression. No image resampling or lossy codecs."""

from dataclasses import dataclass
from pathlib import Path

import pikepdf


class CompressionError(ValueError):
    """An input that cannot safely be processed."""


@dataclass(frozen=True)
class CompressionResult:
    path: Path
    original_size: int
    output_size: int
    pages: int
    status: str


def compress_pdf(source: Path, target: Path) -> CompressionResult:
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        raise CompressionError("输出路径不能覆盖原文件。")
    original_size = source.stat().st_size
    try:
        with pikepdf.open(source, attempt_recovery=False) as pdf:
            if pdf.is_encrypted:
                raise CompressionError("暂不支持加密 PDF，请先使用原软件解密后再试。")
            pages = len(pdf.pages)
            if not pages:
                raise CompressionError("此 PDF 没有页面，无法压缩。")
            # Rewriting signed bytes invalidates signatures, even if appearance is identical.
            for obj in pdf.objects:
                if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
                    if "/ByteRange" in obj or (
                        obj.get("/FT") == pikepdf.Name.Sig and obj.get("/V") is not None
                    ):
                        return CompressionResult(source, original_size, original_size, pages, "signed")
            if pdf.check_pdf_syntax():
                raise CompressionError("此 PDF 存在结构错误，请先用原软件重新导出后再试。")
            # PDF/A-1 prohibits object streams. Keep archival files conservative.
            metadata = pdf.Root.get("/Metadata")
            archival = isinstance(metadata, pikepdf.Stream) and b"pdfa/ns/id" in metadata.read_bytes()
            pdf.save(
                target,
                compress_streams=True,
                recompress_flate=True,
                stream_decode_level=pikepdf.StreamDecodeLevel.generalized,
                object_stream_mode=(pikepdf.ObjectStreamMode.preserve if archival
                                    else pikepdf.ObjectStreamMode.generate),
                normalize_content=False,
                preserve_pdfa=True,
            )
        with pikepdf.open(target, attempt_recovery=False) as check:
            if len(check.pages) != pages or check.check_pdf_syntax():
                raise CompressionError("压缩结果未通过结构检查，原文件未改动。")
        size = target.stat().st_size
        if size >= original_size:
            target.unlink()
            return CompressionResult(source, original_size, original_size, pages, "unchanged")
        return CompressionResult(target, original_size, size, pages, "compressed")
    except pikepdf.PasswordError as exc:
        raise CompressionError("暂不支持加密 PDF，请先使用原软件解密后再试。") from exc
    except (pikepdf.PdfError, RuntimeError) as exc:
        raise CompressionError("无法读取此 PDF，文件可能损坏或并非有效的 PDF。") from exc
