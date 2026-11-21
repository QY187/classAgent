import assert from "node:assert/strict";
import { test } from "node:test";

const base = process.env.PDF_PREVIEW_TEST_URL;
test("PDF阅读器在普通滚动条下保持稳定，缩放和窗口变化不清空画布", { skip: !base, timeout: 90000 }, async () => {
  const { chromium } = await import("playwright-core");
  const browser = await chromium.launch({
    channel: process.env.PDF_PREVIEW_BROWSER_CHANNEL || (process.platform === "win32" ? "msedge" : "chrome"),
    headless: true, ignoreDefaultArgs: ["--hide-scrollbars"], args: ["--disable-features=OverlayScrollbar"],
  });
  try {
    for (const width of [390, 1440]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      await context.addInitScript(({ token, username }) => {
        localStorage.setItem("classagent_token", token);
        localStorage.setItem("classagent_user", JSON.stringify({ username, role: "user" }));
      }, { token: process.env.PDF_PREVIEW_TEST_TOKEN || "isolated", username: process.env.PDF_PREVIEW_TEST_USER || "export-preview" });
      const page = await context.newPage(), errors = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.goto(`${base}/courses/${process.env.PDF_PREVIEW_TEST_COURSE || "c"}/export`, { waitUntil: "networkidle" });
      // 强制保留15px普通滚动条，防止无头浏览器默认隐藏滚动条而漏掉原回归。
      await page.addStyleTag({ content: ".pdf-reader-viewport::-webkit-scrollbar { width: 15px; height: 15px; }" });
      await page.getByRole("button", { name: "查看实际 PDF", exact: true }).click();
      const canvas = page.locator("canvas[data-rendered=true]"), viewport = page.locator(".pdf-reader-viewport");
      await canvas.waitFor();
      await page.waitForFunction(() => document.querySelector(".pdf-reader-viewport")?.getAttribute("aria-busy") === "false");
      await page.waitForTimeout(350);
      assert(await viewport.evaluate(element => element.offsetWidth - element.clientWidth >= 12), "必须实际保留普通滚动条");
      await page.evaluate(() => {
        const viewport = document.querySelector(".pdf-reader-viewport"), host = viewport.querySelector(".pdf-reader-page-host");
        window.__pdfStability = { initial: host.firstChild, replacements: 0, empty: 0, busy: 0 };
        window.__pdfObserver = new MutationObserver(records => {
          for (const record of records) {
            if (record.type === "childList" && record.target === host) {
              window.__pdfStability.replacements++;
              if (!host.querySelector("canvas")) window.__pdfStability.empty++;
            }
            if (record.type === "attributes") window.__pdfStability.busy++;
          }
        });
        window.__pdfObserver.observe(viewport, { childList: true, subtree: true, attributes: true, attributeFilter: ["aria-busy"] });
      });
      await viewport.evaluate(element => { element.scrollTop = 100; });
      await page.waitForTimeout(6000);
      const idle = await page.evaluate(() => ({ replacements: window.__pdfStability.replacements, busy: window.__pdfStability.busy,
        same: window.__pdfStability.initial === document.querySelector(".pdf-reader-page-host").firstChild }));
      assert.deepEqual(idle, { replacements: 0, busy: 0, same: true }, `静置/滚动时不应触发重绘：${width}`);
      await page.getByLabel("PDF预览缩放").selectOption("2");
      await page.waitForFunction(() => document.querySelector("canvas[data-rendered=true]")?.dataset.zoom === "2"
        && document.querySelector(".pdf-reader-viewport").getAttribute("aria-busy") === "false");
      assert.equal(await page.evaluate(() => window.__pdfStability.empty), 0, "新页绘制完成前应保留旧Canvas");
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.getByLabel("PDF预览缩放").selectOption("1");
      await page.waitForFunction(() => document.querySelector("canvas[data-rendered=true]")?.dataset.zoom === "1"
        && document.querySelector(".pdf-reader-viewport").getAttribute("aria-busy") === "false");
      const previousWidth = await canvas.evaluate(element => element.width);
      await page.setViewportSize({ width: width === 1440 ? 1100 : 450, height: 900 });
      await page.waitForFunction(previous => {
        const canvas = document.querySelector("canvas[data-rendered=true]");
        return canvas && canvas.width !== previous && document.querySelector(".pdf-reader-viewport").getAttribute("aria-busy") === "false";
      }, previousWidth);
      await page.waitForTimeout(300);
      const replacements = await page.evaluate(() => window.__pdfStability.replacements);
      await page.waitForTimeout(1200);
      assert.equal(await page.evaluate(() => window.__pdfStability.replacements), replacements, "窗口变化完成后须稳定");
      assert.equal(await page.evaluate(() => window.__pdfStability.empty), 0);
      await page.getByRole("button", { name: "收起预览", exact: true }).click();
      assert.equal(await page.locator(".pdf-document-reader canvas").count(), 0);
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally { await browser.close(); }
});
