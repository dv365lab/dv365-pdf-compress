# 轻一点 · PDF 无损压缩

一个在 Windows 本机运行的中文 Web GUI：拖拽或选择单个 PDF，进行无损压缩，然后下载结果。

## 启动

1. 安装 **Python 3.10 或更新版本**，安装时勾选 `Add Python to PATH`。
2. 双击项目目录中的 **`start.bat`**。
3. 首次启动会在项目的 `.venv` 中安装依赖，需要联网。依赖准备完成后自动打开浏览器；后续运行不需要联网。
4. 拖入一个 PDF，点击「开始无损压缩」，完成后点击下载。

默认地址是 `http://127.0.0.1:8765`。端口被其他程序占用时自动尝试后续 19 个端口；重复启动会打开已经运行的工具。地址也会显示在启动窗口中。

**使用期间保持启动窗口打开。按 Ctrl+C 或关闭启动窗口可停止服务。** 浏览器关闭不代表服务停止。原文件不会被覆盖；下载文件的保存位置由浏览器决定。

## 清晰度与压缩范围

- 使用 pikepdf / QPDF 压缩未压缩的数据流、无损重压缩 Flate 数据，并采用更紧凑的 PDF 对象存储。
- 不降低 DPI、不缩小图片、不转灰度、不将页面转为图片，不重新编码 JPEG。
- 保留文字、矢量图形、字体、书签、链接、批注、表单和附件，不主动删除元数据。
- 如果处理结果更大或一样大，直接返回原文件。**已经充分压缩、主要由 JPEG 扫描图组成的 PDF，可能几乎无法缩小。严格无损与固定的大幅压缩率无法同时保证。**
- 检测到数字签名时返回原文件，避免重写破坏签名；加密 PDF 暂不支持，需先用原软件解密。
- 每次一个文件，最大 512 MB。复杂或较大的文件可能需要几分钟，同时需要足够的临时磁盘空间与内存。
- 文件传到本机 `127.0.0.1` 服务处理，不发送到云端。临时文件在下载响应结束或正常失败后清理；若强制结束进程，系统临时目录中可能残留以 `dv365-pdf-` 开头的目录。
- 输出会进行 PDF 结构检查；测试样本使用两个倍率的逐像素渲染对比。不同 PDF 阅读器、所有特殊 PDF 格式不可能通过有限样本穷尽验证；有归档认证要求的 PDF/A 应在专用验证器中复核。

原理参考：[pikepdf 保存参数](https://pikepdf.readthedocs.io/en/stable/api/main.html)、[QPDF 文件优化说明](https://qpdf.readthedocs.io/en/12.2/cli.html#optimizing-file-size)。

## 开发与验证

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/frontend.test.cjs
```

不打开浏览器启动，或指定起始端口：

```powershell
.\.venv\Scripts\python.exe app.py --no-browser --port 9000
```

也可使用 `start.bat --no-browser`。服务只监听本机，不用于互联网部署。网页无外部字体、脚本或 CDN 依赖。

前端事件测试使用 Node.js 内置测试运行器；运行工具本身不需要 Node.js。

项目结构：`compressor.py` 为压缩逻辑，`app.py` 为本地服务，`templates/` 和 `static/` 为网页，`bootstrap.py` 与 `start.bat` 为一键启动入口，`tests/` 为验证用例。
