// Capture every user-facing screen at desktop and mobile. Usage: node dev/screenshots.mjs <outdir>
// Env: BASE_URL (default http://localhost:3000). Requires the mock API and `next dev` to be running.
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import path from "node:path";
const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require("playwright")); } catch { ({ chromium } = await import("playwright")); }

const outDir = process.argv[2];
if (!outDir) { console.error("usage: node dev/screenshots.mjs <outdir>"); process.exit(1); }
mkdirSync(outDir, { recursive: true });
const BASE = process.env.BASE_URL || "http://localhost:3000";
// Fixture ids from dev/mock-api.mjs
const RESUME_ID = "00000000-0000-4000-8000-000000000010";
const DONE_WF = "00000000-0000-4000-8000-000000000100";
const RUNNING_WF = "00000000-0000-4000-8000-000000000101";

const VIEWPORTS = {
  desktop: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 },
  mobile: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
};

async function settle(page) {
  await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
  await page.waitForFunction(() => !document.querySelector('.animate-pulse, [role="status"][aria-label="Loading"]'), null, { timeout: 15000 }).catch(() => console.warn("  ! skeleton still visible on", page.url()));
  await page.evaluate(() => document.fonts?.ready).catch(() => {});
  await page.waitForTimeout(400);
}

const browser = await chromium.launch();
const produced = [];
let problems = 0;

for (const [vpName, vpOpts] of Object.entries(VIEWPORTS)) {
  const shot = async (page, name, opts = {}) => {
    const file = path.join(outDir, `${vpName}-${name}.png`);
    await page.screenshot({ path: file, fullPage: !opts.viewportOnly });
    produced.push(file);
    console.log("  saved", path.basename(file));
  };
  const attach = (page) => {
    page.on("console", (m) => { if (m.type() === "error") { problems++; console.log(`  [console.error] ${page.url()} :: ${m.text().slice(0, 300)}`); } });
    page.on("pageerror", (e) => { problems++; console.log(`  [pageerror] ${page.url()} :: ${e.message.slice(0, 300)}`); });
    page.on("response", (r) => { if (r.status() >= 400 && r.url().includes("/api/")) console.log(`  [http ${r.status()}] ${r.url()}`); });
  };
  const go = async (page, url) => {
    const res = await page.goto(BASE + url, { waitUntil: "domcontentloaded" });
    if (res && res.status() >= 400) { problems++; console.log(`  [http ${res.status()}] ${url}`); }
    await settle(page);
    await page.addStyleTag({ content: "nextjs-portal, #__next-build-watcher { display: none !important; }" }).catch(() => {});
  };

  console.log(`== ${vpName} ==`);
  // Logged-out pages
  let ctx = await browser.newContext(vpOpts);
  let page = await ctx.newPage();
  attach(page);
  await go(page, "/login");
  await shot(page, "01-login");
  await go(page, "/register");
  await shot(page, "02-register");

  // Log in through the real UI (new context so register page state doesn't matter)
  await go(page, "/login");
  await page.fill('input[name="email"]', "jordan.lee@example.com");
  await page.fill('input[name="password"]', "demo-password-123");
  await Promise.all([page.waitForURL("**/dashboard", { timeout: 20000 }), page.click('button[type="submit"]')]);
  await settle(page);

  await go(page, "/onboarding");
  await shot(page, "03-onboarding");
  await go(page, `/onboarding?step=job&version=00000000-0000-4000-8000-000000000012`);
  await shot(page, "03b-onboarding-job");

  await go(page, "/dashboard");
  await shot(page, "04-dashboard");
  // Expand the completed row
  const toggle = vpName === "desktop"
    ? page.getByRole("button", { name: /details for Staff Data Engineer/i })
    : page.locator("ul li", { hasText: "Staff Data Engineer" }).locator("button[aria-expanded]").first();
  if (await toggle.count()) { await toggle.click(); await settle(page); await shot(page, "04a-dashboard-row-expanded"); }

  await go(page, "/resumes");
  await shot(page, "05-resumes");
  const versionsBtn = page.getByRole("button", { name: /version/i }).first();
  if (await versionsBtn.count()) { await versionsBtn.click().catch(() => {}); await settle(page); await shot(page, "05a-resumes-versions-open"); }
  await go(page, "/resumes");
  const upload = page.getByRole("button", { name: /^\s*upload/i }).first();
  if (await upload.count()) { await upload.click(); await page.waitForTimeout(400); await shot(page, "05b-resumes-upload-dialog", { viewportOnly: true }); }

  // Scanned PDFs are read in the background. The mock simulates it: "scan-fail" ends failed after ~6 s.
  await go(page, "/resumes");
  const scanUpload = page.getByRole("button", { name: /^\s*upload/i }).first();
  if (await scanUpload.count()) {
    await scanUpload.click();
    await page.setInputFiles('input[type="file"]', { name: "scan-fail.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.1\n%%EOF\n") });
    await page.getByRole("button", { name: "Upload resume" }).click();
    if (await page.getByRole("heading", { name: /reading your scan/i }).waitFor({ timeout: 8000 }).then(() => true, () => false)) {
      await shot(page, "05c-scan-reading", { viewportOnly: true });
      await page.keyboard.press("Escape");
      await page.getByText("Reading scan…").first().waitFor({ timeout: 8000 }).catch(() => {});
      await shot(page, "05d-list-row-reading");
      await page.getByText("Could not read").first().waitFor({ timeout: 20000 }).catch(() => {});
      await shot(page, "05e-list-row-failed");
      // Failed state inside the upload dialog (a second scan that is allowed to fail while the dialog stays open)
      await page.getByRole("button", { name: /^\s*upload/i }).first().click();
      await page.setInputFiles('input[type="file"]', { name: "scan-fail.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.1\n%%EOF\n") });
      await page.getByRole("button", { name: "Upload resume" }).click();
      await page.getByText("We couldn't read your scan").waitFor({ timeout: 20000 }).catch(() => {});
      await shot(page, "05f-scan-failed", { viewportOnly: true });
      await page.keyboard.press("Escape");
    }
  }

  await go(page, `/resumes/${RESUME_ID}`);
  await shot(page, "06-resume-detail");
  await go(page, "/resumes/new");
  await shot(page, "07-resume-new");
  await go(page, "/tailor/new");
  await shot(page, "08-tailor-new");

  await go(page, `/tailor/${RUNNING_WF}`);
  await shot(page, "09-tailor-progress");

  await go(page, `/tailor/${DONE_WF}`);
  await shot(page, "10-tailor-review");
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, "10a-review-top-export-bar", { viewportOnly: true });
  for (const [tabName, file] of [["Missing keywords", "10e-review-keywords"], ["Hiring-manager view", "10f-review-hiring-manager"]]) {
    const tab = page.getByRole("tab", { name: new RegExp(tabName, "i") });
    if (await tab.count()) { await tab.click(); await settle(page); await shot(page, file); }
  }
  const changesTab = page.getByRole("tab", { name: /^changes/i });
  if (await changesTab.count()) { await changesTab.click(); await settle(page); }
  const changes = page.getByRole("heading", { name: /review changes/i }).first();
  if (await changes.count()) { await changes.scrollIntoViewIfNeeded(); await page.evaluate(() => window.scrollBy(0, -16)); await page.waitForTimeout(300); await shot(page, "10b-review-changes", { viewportOnly: true }); }
  const iterate = page.locator("#iterate");
  if (await iterate.count()) { await iterate.scrollIntoViewIfNeeded(); await page.waitForTimeout(300); await shot(page, "10c-review-regenerate", { viewportOnly: true }); }
  await page.evaluate(() => window.scrollTo(0, 0));
  const share = page.getByRole("button", { name: /share link/i });
  if (await share.count()) { await share.click(); await page.waitForTimeout(800); await shot(page, "10d-review-share-dialog", { viewportOnly: true }); }

  await go(page, "/applications");
  await shot(page, "11-applications");
  const add = page.getByRole("button", { name: /add application|add your first/i }).first();
  if (await add.count()) { await add.click(); await page.waitForTimeout(400); await shot(page, "11a-applications-add-dialog", { viewportOnly: true }); }

  await go(page, "/settings");
  await shot(page, "12-settings");
  await ctx.close();
}
await browser.close();
console.log(`\n${produced.length} screenshots written to ${outDir}; ${problems} console/page problems`);
