// Exercise the shipped browser event handlers without external JS dependencies.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function page(fetchImpl) {
  const elements = new Map();
  const revoked = [];
  function element(id) {
    if (!elements.has(id)) {
      const listeners = new Map();
      const classes = new Set();
      elements.set(id, {
        hidden: ["file-card", "result", "error-message", "progress"].includes(id),
        disabled: id === "compress-button", textContent: "", value: "", attributes: {},
        firstChild: {textContent: ""},
        classList: {
          add: (name) => classes.add(name), remove: (name) => classes.delete(name),
          toggle: (name, value) => value ? classes.add(name) : classes.delete(name)
        },
        addEventListener: (name, callback) => listeners.set(name, callback),
        setAttribute(name, value) { this.attributes[name] = value; },
        removeAttribute(name) { delete this.attributes[name]; },
        contains: () => false,
        click: () => {},
        trigger(name, event = {}) { return listeners.get(name)?.({
          preventDefault() {}, stopPropagation() {}, ...event
        }); }
      });
    }
    return elements.get(id);
  }
  const context = vm.createContext({
    document: {getElementById: element, addEventListener() {},
      querySelector: () => ({content: "test-token"})},
    window: {addEventListener() {}},
    FormData: class { constructor() { this.values = []; } append(...value) { this.values.push(value); } },
    URL: {createObjectURL: () => "blob:test-pdf", revokeObjectURL: (url) => revoked.push(url)},
    fetch: fetchImpl, Date, setInterval, clearInterval, console,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8"), context);
  return {element, revoked, drop: (files) => element("drop-zone").trigger("drop", {
    dataTransfer: {files}
  }), compress: () => element("compress-button").trigger("click")};
}

function result(status = "compressed", data = {original: 1000, output: 500, pages: 2}) {
  return {ok: true,
    blob: async () => ({type: "application/pdf", size: data.output}),
    headers: {get: (name) => ({"X-Original-Size": String(data.original),
      "X-Output-Size": String(data.output), "X-Page-Count": String(data.pages),
      "X-Compression-Status": status})[name]}
  };
}

test("dragging one PDF enables compression; removing it resets the form", () => {
  const p = page();
  p.drop([{name: "课程.pdf", size: 1000}]);
  assert.equal(p.element("file-name").textContent, "课程.pdf");
  assert.equal(p.element("compress-button").disabled, false);
  p.element("remove-button").trigger("click");
  assert.equal(p.element("compress-button").disabled, true);
  assert.equal(p.element("file-card").hidden, true);
});

test("multiple dropped files are rejected, without silently choosing the first", () => {
  const p = page();
  p.drop([{name: "one.pdf", size: 1000}, {name: "two.pdf", size: 1000}]);
  assert.match(p.element("error-message").textContent, /一个/);
  assert.equal(p.element("compress-button").disabled, true);
});

test("invalid, empty and oversized files leave the form unselected", () => {
  for (const file of [{name: "not.txt", size: 10}, {name: "empty.pdf", size: 0},
                      {name: "huge.pdf", size: 512 * 1024 * 1024 + 1}]) {
    const p = page(); p.drop([file]);
    assert.equal(p.element("error-message").hidden, false);
    assert.equal(p.element("compress-button").disabled, true);
  }
});

test("while processing, the selected file cannot be replaced or submitted twice", async () => {
  let complete;
  let requests = 0;
  const p = page(() => { requests++; return new Promise((resolve) => { complete = resolve; }); });
  p.drop([{name: "one.pdf", size: 1000}]);
  const processing = p.compress();
  assert.equal(p.element("progress").hidden, false);
  assert.equal(p.element("compress-button").disabled, true);
  p.drop([{name: "two.pdf", size: 1000}]);
  await p.compress();
  assert.equal(p.element("file-name").textContent, "one.pdf");
  assert.equal(requests, 1);
  complete(result());
  await processing;
  assert.equal(p.element("progress").hidden, true);
  assert.equal(p.element("compress-button").disabled, false);
});

test("successful compression exposes a named PDF download and accurate savings", async () => {
  let request;
  const p = page(async (url, options) => { request = {url, options}; return result(); });
  p.drop([{name: "课程.PDF", size: 1000}]);
  await p.compress();
  assert.equal(request.url, "/api/compress");
  assert.equal(request.options.headers["X-Request-Token"], "test-token");
  assert.equal(request.options.body.values[0][0], "file");
  assert.equal(p.element("result").hidden, false);
  assert.equal(p.element("saving").textContent, "50.0%");
  assert.equal(p.element("download-button").href, "blob:test-pdf");
  assert.equal(p.element("download-button").download, "课程_compressed.pdf");
  p.drop([{name: "next.pdf", size: 1000}]);
  assert.equal(p.element("result").hidden, true);
  assert.deepEqual(p.revoked, ["blob:test-pdf"]);
});

test("unchanged and signed results explain why the original is returned", async () => {
  for (const status of ["unchanged", "signed"]) {
    const p = page(async () => result(status, {original: 1000, output: 1000, pages: 1}));
    p.drop([{name: "one.pdf", size: 1000}]); await p.compress();
    assert.equal(p.element("saving").textContent, "0%");
    assert.equal(p.element("download-button").download, "one_original.pdf");
    assert.match(p.element("result-title").textContent, /保留原文件/);
  }
});

test("server errors leave the page ready for a retry", async () => {
  const p = page(async () => ({ok: false, json: async () => ({error: "文件已损坏"})}));
  p.drop([{name: "bad.pdf", size: 1000}]); await p.compress();
  assert.equal(p.element("error-message").textContent, "文件已损坏");
  assert.equal(p.element("result").hidden, true);
  assert.equal(p.element("progress").hidden, true);
  assert.equal(p.element("compress-button").disabled, false);
});

test("incomplete downloads do not expose a misleading success state", async () => {
  const p = page(async () => {
    const response = result(); response.blob = async () => ({type: "application/pdf", size: 400});
    return response;
  });
  p.drop([{name: "one.pdf", size: 1000}]); await p.compress();
  assert.match(p.element("error-message").textContent, /不完整/);
  assert.equal(p.element("result").hidden, true);
});
