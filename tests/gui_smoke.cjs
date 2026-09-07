// Optional UI regression test. Usage: node tests/gui_smoke.cjs [playwright module path] [artifact folder]
const { chromium } = require(process.argv[2] || "playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");
const root = path.resolve(__dirname, "..");
const artifacts = process.argv[3] || fs.mkdtempSync(path.join(os.tmpdir(), "emailtools-ui-"));
fs.mkdirSync(artifacts, { recursive: true });

(async () => {
  const child = spawn(path.join(root, "runtime/python/python.exe"),
    ["-X", "utf8", path.join(root, "main.py"), "--no-browser"], { cwd: os.tmpdir(), windowsHide: true });
  let output = "", browser, url;
  child.stdout.on("data", data => output += data.toString());
  child.stderr.on("data", data => output += data.toString());
  try {
    url = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => { clearInterval(timer); reject(new Error(output || "Server startup timeout")); }, 15000);
      const timer = setInterval(() => {
        const match = output.match(/http:\/\/127\.0\.0\.1:\d+\/[^\s]+\//);
        if (match) { clearInterval(timer); clearTimeout(timeout); resolve(match[0]); }
      }, 50);
    });
    browser = await chromium.launch({ headless: true, channel: process.env.EMAILTOOLS_BROWSER || "msedge" });
    const context = await browser.newContext({ viewport: { width: 1440, height: 1120 }, acceptDownloads: true });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
    page.on("dialog", dialog => dialog.accept());
    async function assertViewportFits(label, inspectControls = false) {
      const dimensions = await page.evaluate(() => ({
        viewport: window.innerWidth,
        document: document.documentElement.scrollWidth,
      }));
      assert(dimensions.document <= dimensions.viewport,
        `${label}: page overflows horizontally (${dimensions.document}px > ${dimensions.viewport}px)`);
      if (!inspectControls) return;
      // A page can avoid body overflow while hiding controls inside clipped cards.
      const controls = page.locator(".operation-grid > label, #export");
      assert.equal(await controls.count(), 5);
      for (const control of await controls.all()) {
        await control.scrollIntoViewIfNeeded();
        const bounds = await control.boundingBox();
        const viewport = page.viewportSize();
        assert(bounds && bounds.width > 0 && bounds.height > 0, `${label}: control has no visible size`);
        assert(bounds.x >= -1 && bounds.x + bounds.width <= viewport.width + 1,
          `${label}: control extends outside viewport: ${(await control.textContent()).trim()}`);
        assert(bounds.y >= -1 && bounds.y + bounds.height <= viewport.height + 1,
          `${label}: control is clipped after scrolling into view`);
      }
    }
    async function screenshot(filename) {
      // Presentation images should show the resting UI, without transient focus overlays.
      await page.evaluate(() => {
        if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
        window.scrollTo(0, 0);
      });
      await page.screenshot({ path: path.join(artifacts, filename), fullPage: true });
    }
    await page.goto(url);
    await assertViewportFits("initial desktop", true);
    await screenshot("initial-desktop.png");
    await page.setViewportSize({ width: 390, height: 844 });
    await assertViewportFits("initial mobile", true);
    await screenshot("initial-mobile.png");
    await page.setViewportSize({ width: 1440, height: 1120 });
    const emptyWorkspaceHeight = (await page.locator("#table-workspace").boundingBox()).height;
    const workspace = page.locator("#table-workspace");
    const columns = page.locator("#column-panel");
    const toggleColumns = page.locator("#toggle-columns");
    const resizer = page.locator("#workspace-resizer");
    const manyFieldsMail = ["Subject: Many fields", "From: test@example.com", "MIME-Version: 1.0",
      "Content-Type: text/html; charset=utf-8", "", "<table>" + Array.from({ length: 20 }, (_, index) =>
        `<tr><td>Field ${index + 1}</td><td>Value ${index + 1}</td></tr>`).join("") + "</table>"].join("\r\n");
    await page.locator("#files-input").setInputFiles({ name: "many-fields.eml", mimeType: "message/rfc822", buffer: Buffer.from(manyFieldsMail) });
    await page.waitForFunction(() => document.getElementById("metric-rows").textContent === "1" && !document.getElementById("export").disabled);
    assert(await page.locator("#column-list .column-row").count() > 15,
      "The many-field fixture must exercise a column list long enough to require scrolling");
    const columnListSize = await page.locator("#column-list").evaluate(list => ({
      content: list.scrollHeight, visible: list.clientHeight,
    }));
    assert(columnListSize.visible > 0 && columnListSize.content > columnListSize.visible,
      "Long column lists must scroll inside the desktop panel");
    assert((await workspace.boundingBox()).height <= emptyWorkspaceHeight + 2,
      "Loading many columns must not expand the desktop workspace");
    await page.locator("#demo").click();
    await page.waitForFunction(() => document.getElementById("metric-rows").textContent === "3" && !document.getElementById("export").disabled);
    assert.equal(await toggleColumns.getAttribute("aria-expanded"), "true");
    await toggleColumns.click();
    await page.waitForFunction(() => document.getElementById("table-workspace").classList.contains("columns-collapsed"));
    assert.equal(await toggleColumns.getAttribute("aria-expanded"), "false");
    assert(await columns.isHidden());
    await toggleColumns.click();
    await page.waitForFunction(() => !document.getElementById("table-workspace").classList.contains("columns-collapsed"));
    assert.equal(await toggleColumns.getAttribute("aria-expanded"), "true");
    assert(await columns.isVisible());
    assert.equal(await resizer.getAttribute("role"), "separator");
    await resizer.focus();
    await resizer.press("Home");
    await page.waitForFunction(() => Math.abs(document.getElementById("column-panel").getBoundingClientRect().width - 240) < 2);
    const minimumWidth = (await columns.boundingBox()).width;
    await resizer.press("ArrowRight");
    await page.waitForFunction(width => document.getElementById("column-panel").getBoundingClientRect().width > width + 1, minimumWidth);
    const increasedWidth = (await columns.boundingBox()).width;
    assert(increasedWidth <= 420, "ArrowRight must respect the column width limit");
    await resizer.press("ArrowLeft");
    await page.waitForFunction(width => document.getElementById("column-panel").getBoundingClientRect().width < width - 1, increasedWidth);
    assert((await columns.boundingBox()).width >= 239, "ArrowLeft must respect the column width limit");
    await resizer.press("End");
    await page.waitForFunction(() => Math.abs(document.getElementById("column-panel").getBoundingClientRect().width - 420) < 2);
    await resizer.press("ArrowRight");
    assert((await columns.boundingBox()).width <= 421, "The panel cannot grow beyond its maximum");
    await resizer.press("Home");
    await page.waitForFunction(() => Math.abs(document.getElementById("column-panel").getBoundingClientRect().width - 240) < 2);
    await resizer.press("ArrowLeft");
    assert((await columns.boundingBox()).width >= 239, "The panel cannot shrink below its minimum");
    await resizer.press("ArrowRight");
    const beforeDrag = (await columns.boundingBox()).width;
    await resizer.scrollIntoViewIfNeeded();
    const handle = await resizer.boundingBox();
    await page.mouse.move(handle.x + handle.width / 2, handle.y + Math.min(handle.height / 2, 32));
    await page.mouse.down();
    await page.mouse.move(handle.x + handle.width / 2 + 48, handle.y + Math.min(handle.height / 2, 32), { steps: 4 });
    await page.mouse.up();
    await page.waitForFunction(width => document.getElementById("column-panel").getBoundingClientRect().width > width + 20, beforeDrag);
    assert((await columns.boundingBox()).width <= 421, "Pointer dragging must respect the column width limit");
    // At narrow widths the panels stack and the desktop-only resize control disappears.
    for (const width of [1920, 1440, 1024, 800, 390, 320]) {
      await page.setViewportSize({ width, height: width <= 800 ? 844 : 1120 });
      await assertViewportFits(`loaded ${width}px`, width === 1440 || width === 390);
      if (width <= 800) {
        assert(await resizer.isHidden(), `${width}px: a stacked layout must not expose a horizontal resizer`);
        const columnBounds = await columns.boundingBox();
        const previewBounds = await workspace.locator(".preview-panel").boundingBox();
        assert(previewBounds.y >= columnBounds.y + columnBounds.height - 1,
          `${width}px: preview must follow the column panel vertically`);
      }
    }
    await page.setViewportSize({ width: 1280, height: 600 });
    await assertViewportFits("short desktop 1280x600", true);
    assert(await page.locator("#column-list").evaluate(list => list.scrollHeight > list.clientHeight),
      "The column list must remain scrollable in a short desktop window");
    const shortWorkspace = await workspace.boundingBox();
    const shortFooter = await page.locator("#preview-footer").boundingBox();
    assert(shortFooter && shortFooter.y >= shortWorkspace.y - 1 &&
      shortFooter.y + shortFooter.height <= shortWorkspace.y + shortWorkspace.height + 1,
      "Preview pagination must remain inside the workspace in a short window");
    await page.setViewportSize({ width: 1440, height: 1120 });
    await page.locator("#output-path").fill(path.join(artifacts, "saved-jobs"));
    await page.locator("#data-only").click();
    await page.getByRole("checkbox", { name: "교육일 열 포함", exact: true }).uncheck();
    await page.locator("#add-column").click();
    await page.locator("#custom-name").fill("검토 상태");
    await page.locator("#custom-value").fill("검토 대기");
    await page.getByRole("button", { name: "미리보기에 반영" }).click();
    await page.waitForFunction(() => document.querySelector("#preview-table thead").textContent.includes("검토 상태") && !document.getElementById("export").disabled);
    let headers = await page.locator("#preview-table th").allTextContents();
    assert(!headers.includes("교육일"));
    assert(headers.includes("검토 상태"));
    assert.equal(await page.locator("#preview-table tbody tr").count(), 3);
    assert.equal(await page.getByRole("button", { name: "검토 상태: 검토 대기", exact: true }).count(), 3);
    // Duplicate names are rejected; custom values are editable.
    await page.locator("#add-column").click();
    await page.locator("#custom-name").fill("검토 상태");
    await page.getByRole("button", { name: "미리보기에 반영" }).click();
    assert((await page.locator("#column-error").textContent()).includes("이미 있는"));
    await page.locator("#cancel-column").click();
    await page.getByRole("button", { name: "검토 상태 위로 이동", exact: true }).click();
    await page.waitForFunction(() => [...document.querySelectorAll("#preview-table th")].at(-2)?.textContent === "검토 상태");
    await page.locator("#view-original").click();
    await page.waitForFunction(() => document.querySelector("#preview-table thead").textContent.includes("source_eml"));
    assert(!(await page.locator("#preview-table th").allTextContents()).includes("검토 상태"));
    await page.locator("#view-result").click();
    await page.waitForFunction(() => document.querySelector("#preview-table thead").textContent.includes("검토 상태") && !document.getElementById("export").disabled);
    await screenshot("table-preview.png");
    // Download the actual workbook and compare its content with the visible result.
    const previewRows = await page.locator("#preview-table tbody tr").evaluateAll(rows => rows.map(row =>
      [...row.querySelectorAll("td button.cell-content")].map(cell => cell.textContent === "—" ? "" : cell.textContent)));
    headers = (await page.locator("#preview-table th").allTextContents()).slice(1);
    const downloading = page.waitForEvent("download");
    await page.locator("#export").click();
    const download = await downloading;
    assert.equal(download.suggestedFilename(), "EML_Table_Result.xlsx");
    const outputFile = path.join(artifacts, "preview-result.xlsx");
    await download.saveAs(outputFile);
    const check = spawn(path.join(root, "runtime/python/python.exe"), ["-X", "utf8", "-c",
      "import sys,json;sys.path.insert(0,sys.argv[1]);from openpyxl import load_workbook;w=load_workbook(sys.argv[2]);print(json.dumps([[v or '' for v in r] for r in w.active.values],ensure_ascii=False));w.close()",
      path.join(root, "vendor"), outputFile], { windowsHide: true });
    let workbookJson = "";
    check.stdout.on("data", data => workbookJson += data.toString());
    await new Promise((resolve, reject) => { check.on("exit", code => code === 0 ? resolve() : reject(new Error(`Workbook check exit ${code}`))); check.on("error", reject); });
    assert.deepEqual(JSON.parse(workbookJson), [headers, ...previewRows]);
    // Empty selection cannot export, restoring a column restores its data.
    await page.locator("#select-none").click();
    await page.waitForFunction(() => document.getElementById("preview-empty").offsetParent !== null);
    assert(await page.locator("#export").isDisabled());
    await page.getByRole("checkbox", { name: "교육명 열 포함", exact: true }).check();
    await page.waitForFunction(() => !document.getElementById("export").disabled);
    assert.equal(await page.getByRole("button", { name: "교육명: AI 업무 활용", exact: true }).count(), 1);
    // Browser file selection reaches the real Python parser and keeps markup inert.
    const eml = ["Subject: UI file input", "From: test@example.com", "MIME-Version: 1.0", "Content-Type: text/html; charset=utf-8", "",
      "<table><tr><td>Field</td><td>&lt;img src=x onerror=alert(1)&gt;</td></tr></table>"].join("\r\n");
    await page.locator("#files-input").setInputFiles({ name: "메일.eml", mimeType: "message/rfc822", buffer: Buffer.from(eml) });
    await page.waitForFunction(() => document.getElementById("metric-rows").textContent === "1" && !document.getElementById("export").disabled);
    await page.locator("#data-only").click();
    await page.waitForFunction(() => document.querySelector("#preview-table thead").textContent === "#Field");
    assert.equal(await page.locator("#preview-table tbody img").count(), 0);
    assert((await page.locator("#preview-table tbody").textContent()).includes("<img"));
    // Invalid input removes stale data and offers a recoverable error.
    await page.locator("#source-path").fill(path.join(artifacts, "does-not-exist"));
    await page.locator("#load-path").click();
    await page.waitForFunction(() => document.getElementById("notice").classList.contains("error"));
    assert(await page.locator("#export").isDisabled());
    await page.locator("#demo").click();
    await page.waitForFunction(() => document.getElementById("metric-rows").textContent === "3" && !document.getElementById("export").disabled);
    await page.locator("#data-only").click();
    await page.waitForFunction(() => !document.getElementById("export").disabled);
    // Unified options invalidate old results until the same input is reanalyzed.
    await page.locator("#preset-all").click();
    assert(await page.locator("#export").isDisabled());
    assert(await page.locator("#reanalyze").isEnabled());
    await page.locator("#reanalyze").click();
    await page.waitForFunction(() => !document.getElementById("export").disabled);
    await page.locator("#tab-mails").click();
    await page.waitForFunction(() => document.querySelectorAll("#details-table tbody tr").length === 3);
    await page.locator("#tab-attachments").click();
    await page.waitForFunction(() => document.querySelectorAll("#details-table tbody tr").length === 2);
    assert((await page.locator("#details-table").textContent()).includes("docx"));
    const allDownload = page.waitForEvent("download");
    await page.locator("#export").click();
    const zipDownload = await allDownload;
    assert.equal(zipDownload.suggestedFilename(), "EmailTools_Result.zip");
    const zipPath = path.join(artifacts, "all-results.zip");
    await zipDownload.saveAs(zipPath);
    async function zipEntries(filename) {
      const proc = spawn(path.join(root, "runtime/python/python.exe"), ["-c",
        "import sys,zipfile,json;z=zipfile.ZipFile(sys.argv[1]);print(json.dumps(z.namelist()));assert z.testzip() is None;z.close()", filename], { windowsHide: true });
      let value = "";
      proc.stdout.on("data", data => value += data.toString());
      await new Promise((resolve, reject) => { proc.on("exit", code => code === 0 ? resolve() : reject(new Error(`ZIP check exit ${code}`))); proc.on("error", reject); });
      return JSON.parse(value);
    }
    const entries = await zipEntries(zipPath);
    assert(entries.some(name => name.includes("/attachments/")));
    assert(entries.some(name => name.includes("/text/")));
    assert(entries.some(name => name.endsWith("/mail.txt")));
    assert(entries.includes("tables/EML_Table_Result.xlsx"));
    await page.locator("#opt-tables").uncheck();
    assert(await page.locator("#export").isDisabled());
    await page.locator("#reanalyze").click();
    await page.waitForFunction(() => !document.getElementById("export").disabled);
    assert(await page.locator("#tab-tables").isDisabled());
    assert(await page.locator("#table-workspace").isHidden());
    const noTableDownload = page.waitForEvent("download");
    await page.locator("#export").click();
    const noTableZip = await noTableDownload;
    const noTablePath = path.join(artifacts, "without-tables.zip");
    await noTableZip.saveAs(noTablePath);
    assert(!(await zipEntries(noTablePath)).some(name => name.startsWith("tables/")));
    // Restore the table preset before the narrow viewport check.
    await page.locator("#preset-tables").click();
    await page.locator("#reanalyze").click();
    await page.waitForFunction(() => !document.getElementById("export").disabled);
    await page.locator("#data-only").click();
    await page.waitForFunction(() => !document.getElementById("export").disabled);
    await page.setViewportSize({ width: 390, height: 844 });
    await screenshot("table-preview-mobile.png");
    await assertViewportFits("final mobile", true);
    assert.deepEqual(errors, []);
    await page.locator("#shutdown").click();
    await page.waitForFunction(() => document.getElementById("notice").textContent.includes("프로그램이 종료"));
    console.log(JSON.stringify({ result: "passed", checks: "column visibility, keyboard and pointer resizing, bounded workspace with internal column scrolling, responsive layouts from 320 to 1920px, reachable operation/save controls, column selection, add/edit validation, reorder, original comparison, workbook parity, empty selection, upload, inert markup, error recovery, shutdown", artifacts }));
  } finally {
    if (browser) await browser.close();
    if (child.exitCode === null && url) {
      try { await fetch(url + "api/shutdown", { method: "POST", headers: { "X-EmailTools-Token": new URL(url).pathname.split("/")[1] }, body: "{}" }); } catch {}
    }
    if (child.exitCode === null) {
      await new Promise(resolve => {
        const timer = setTimeout(() => { child.kill(); resolve(); }, 5000);
        child.once("exit", () => { clearTimeout(timer); resolve(); });
      });
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
