"use strict";

const $ = (id) => document.getElementById(id);
const input = $("file-input");
const dropZone = $("drop-zone");
const button = $("compress-button");
let selectedFile = null;
let busy = false;
let downloadUrl = null;

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let size = bytes / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit++; }
  return `${size.toFixed(size < 10 ? 2 : 1)} ${units[unit]}`;
}

function error(message) {
  $("error-message").textContent = message;
  $("error-message").hidden = !message;
}

function clearResult() {
  $("result").hidden = true;
  $("download-button").removeAttribute("href");
  if (downloadUrl) URL.revokeObjectURL(downloadUrl);
  downloadUrl = null;
}

function choose(files) {
  if (busy || !files.length) return;
  if (files.length !== 1) { error("每次只能处理一个 PDF，请重新选择一个文件。"); return; }
  const file = files[0];
  if (!/\.pdf$/i.test(file.name)) { error("请选择 .pdf 格式的文件。"); return; }
  if (!file.size) { error("这个文件是空的，请选择有效的 PDF。"); return; }
  if (file.size > 512 * 1024 * 1024) { error("文件过大，单个 PDF 最大支持 512 MB。"); return; }
  selectedFile = file;
  clearResult();
  error("");
  $("file-name").textContent = file.name;
  $("file-name").title = file.name;
  $("file-size").textContent = `${formatSize(file.size)} · 已准备就绪`;
  $("file-card").hidden = false;
  button.disabled = false;
  $("compress-label").textContent = "开始无损压缩";
}

function browse() { if (!busy) input.click(); }
$("browse-button").addEventListener("click", (event) => { event.stopPropagation(); browse(); });
dropZone.addEventListener("click", browse);
dropZone.addEventListener("keydown", (event) => {
  if (event.target === dropZone && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault(); browse();
  }
});
input.addEventListener("change", () => { choose(input.files); input.value = ""; });

// Prevent dropped files from navigating away from the app, including outside the drop zone.
document.addEventListener("dragover", (event) => event.preventDefault());
document.addEventListener("drop", (event) => event.preventDefault());
dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  if (!busy) { dropZone.classList.add("dragover"); event.dataTransfer.dropEffect = "copy"; }
});
dropZone.addEventListener("dragleave", (event) => {
  if (!dropZone.contains(event.relatedTarget)) dropZone.classList.remove("dragover");
});
dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragover");
  choose(event.dataTransfer.files);
});

$("remove-button").addEventListener("click", () => {
  if (busy) return;
  selectedFile = null;
  $("file-card").hidden = true;
  button.disabled = true;
  clearResult();
  error("");
});

function setBusy(value) {
  busy = value;
  button.disabled = value || !selectedFile;
  input.disabled = value;
  $("browse-button").disabled = value;
  $("remove-button").disabled = value;
  dropZone.classList.toggle("busy", value);
  dropZone.setAttribute("aria-disabled", String(value));
  $("progress").hidden = !value;
  $("compress-label").textContent = value ? "正在处理，请稍候…" : "开始无损压缩";
}

button.addEventListener("click", async () => {
  if (!selectedFile || busy) return;
  error("");
  clearResult();
  const file = selectedFile;
  const form = new FormData();
  form.append("file", file);
  setBusy(true);
  const start = Date.now();
  $("elapsed").textContent = "0 秒";
  const timer = setInterval(() => {
    $("elapsed").textContent = `${Math.floor((Date.now() - start) / 1000)} 秒`;
  }, 1000);
  try {
    const response = await fetch("/api/compress", {
      method: "POST", body: form,
      headers: { "X-Request-Token": document.querySelector('meta[name="request-token"]').content }
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.error || `处理失败（${response.status}），请重试。`);
    }
    const blob = await response.blob();
    const original = Number(response.headers.get("X-Original-Size"));
    const output = Number(response.headers.get("X-Output-Size"));
    const pages = Number(response.headers.get("X-Page-Count"));
    const status = response.headers.get("X-Compression-Status");
    if (blob.type !== "application/pdf" || !original || output !== blob.size || !pages) {
      throw new Error("下载数据不完整，请重新处理。");
    }
    downloadUrl = URL.createObjectURL(blob);
    const link = $("download-button");
    link.href = downloadUrl;
    link.download = `${file.name.slice(0, -4)}${status === "compressed" ? "_compressed" : "_original"}.pdf`;
    link.firstChild.textContent = status === "compressed" ? "下载压缩文件 " : "下载原文件 ";
    const saved = original - output;
    const percent = (saved / original) * 100;
    $("original-size").textContent = formatSize(original);
    $("output-size").textContent = formatSize(output);
    $("saving").textContent = saved ? (percent < 0.1 ? "< 0.1%" : `${percent.toFixed(1)}%`) : "0%";
    $("page-count").textContent = `${pages} 页 · ${saved ? `节省 ${formatSize(saved)}` : "保留原始文件"}`;
    if (status === "compressed") {
      $("result-title").textContent = "压缩完成，细节如初";
      $("result-description").textContent = "已优化文件结构和无损数据流，未降低图片分辨率。";
    } else if (status === "signed") {
      $("result-title").textContent = "检测到数字签名，已保留原文件";
      $("result-description").textContent = "重写 PDF 会使数字签名失效，因此本次未做压缩。";
    } else {
      $("result-title").textContent = "已经很精简，保留原文件";
      $("result-description").textContent = "无损优化没有得到更小的文件，已返回原始数据。";
    }
    $("result").hidden = false;
    $("file-size").textContent = `${formatSize(file.size)} · 处理完成`;
  } catch (exception) {
    error(exception instanceof TypeError ? "无法连接本地服务，请确认启动窗口仍在运行后重试。" : exception.message);
  } finally {
    clearInterval(timer);
    setBusy(false);
  }
});

window.addEventListener("beforeunload", (event) => {
  if (busy) { event.preventDefault(); event.returnValue = ""; }
});
window.addEventListener("pagehide", () => { if (downloadUrl) URL.revokeObjectURL(downloadUrl); });
