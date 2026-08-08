#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

// Options that may be repeated; they are ALWAYS collected as arrays so a
// single occurrence does not become a string (string.every is undefined).
const MULTI_OPTIONS = new Set(["expect-options-text"]);

function parseArgs(values) {
  const result = {};
  for (let index = 0; index < values.length; index += 2) {
    const key = values[index];
    const value = values[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`invalid argument list near ${key ?? "<end>"}`);
    }
    const name = key.slice(2);
    if (name in result || MULTI_OPTIONS.has(name)) {
      result[name] = [].concat(result[name] ?? [], value);
    } else {
      result[name] = value;
    }
  }
  for (const required of ["playwright-dir", "html", "output"]) {
    if (!result[required]) throw new Error(`missing --${required}`);
  }
  return result;
}

const args = parseArgs(process.argv.slice(2));
const require = createRequire(import.meta.url);
const { chromium } = require(path.resolve(args["playwright-dir"]));
const html = path.resolve(args.html);
const output = path.resolve(args.output);
fs.mkdirSync(output, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
});
const page = await context.newPage();
const pageErrors = [];
const consoleErrors = [];
page.on("pageerror", (error) => pageErrors.push(String(error)));
page.on("console", (message) => {
  if (
    message.type() === "error" &&
    !message.text().includes("Failed to load resource")
  ) {
    consoleErrors.push(message.text());
  }
});

const checks = {};
let runtime = {};
let optionsCheckSkipped = true;
try {
  await page.goto(pathToFileURL(html).href, {
    waitUntil: "load",
    timeout: 120000,
  });
  await page.waitForFunction(
    () =>
      document.readyState === "complete" && typeof window.State === "object",
    null,
    { timeout: 120000 },
  );
  await page.waitForTimeout(1000);
  runtime = await page.evaluate(() => ({
    title: document.title,
    passage: window.State?.passage ?? null,
    sugarCubeVersion: window.SugarCube?.version?.toString?.() ?? null,
    storyApiType: typeof window.SugarCube?.Story,
    engineApiType: typeof window.SugarCube?.Engine,
    bodyCharacters: document.body?.innerText?.length ?? 0,
  }));
  checks.storyLoaded =
    runtime.title.includes("Degrees of Lewdity") &&
    runtime.bodyCharacters > 100;
  checks.startPassage = runtime.passage === "Start";
  await page.screenshot({ path: path.join(output, "01-age-gate.png") });

  const ageDialog = page.locator("#ui-dialog-body");
  if (await ageDialog.isVisible()) {
    const checkbox = ageDialog.locator('input[type="checkbox"]');
    await checkbox.check();
    // English builds label the gate button "Enter", Korean builds "입장".
    const enterButton = ageDialog
      .getByRole("button", { name: /^(Enter|입장)$/ })
      .first();
    await enterButton.click();
    await ageDialog.waitFor({ state: "hidden", timeout: 30000 });
  }
  checks.ageGateAccepted = await page.evaluate(
    () => localStorage.getItem("verifiedAge") === "true",
  );
  await page.screenshot({ path: path.join(output, "02-start.png") });

  const startCaption = page.locator("#startCaption");
  const optionsButton = startCaption
    .getByRole("button", { name: /^(OPTIONS|옵션)$/ })
    .first();
  await optionsButton.click();
  const overlay = page.locator("#customOverlay");
  await page.waitForFunction(
    () =>
      document.querySelector("#customOverlay")?.getAttribute("data-overlay") ===
      "options",
    null,
    { timeout: 30000 },
  );
  const optionsText = await page.locator("#customOverlayContent").innerText();
  checks.optionsOverlay =
    (await overlay.getAttribute("data-overlay")) === "options";
  // Korean strings to require in the options overlay; empty means the check
  // is skipped — recorded as a warning so a silent pass is visible.
  const expectedOptionsTexts = args["expect-options-text"] ?? [];
  checks.koreanOptionsApplied =
    expectedOptionsTexts.length === 0 ||
    expectedOptionsTexts.every((text) => optionsText.includes(text));
  optionsCheckSkipped = expectedOptionsTexts.length === 0;
  await page.screenshot({ path: path.join(output, "03-options.png") });

  await page.locator(".customOverlayClose").click();
  await overlay.waitFor({ state: "hidden", timeout: 30000 });
  const savesButton = startCaption
    .getByRole("button", { name: /^(SAVES|세이브)$/ })
    .first();
  await savesButton.click();
  await page.waitForFunction(
    () =>
      document.querySelector("#customOverlay")?.getAttribute("data-overlay") ===
      "saves",
    null,
    { timeout: 30000 },
  );
  await page.waitForFunction(
    () =>
      document
        .querySelector("#customOverlayContent")
        ?.innerText?.includes("save on this passage"),
    null,
    { timeout: 30000 },
  );
  const savesText = await page.locator("#customOverlayContent").innerText();
  checks.savesOverlay =
    (await overlay.getAttribute("data-overlay")) === "saves";
  checks.startSaveRestriction =
    /can't save (?:on this passage|here)|저장할 수 없습니다|세이브할 수 없습니다/i.test(
      savesText,
    );
  await page.screenshot({ path: path.join(output, "04-saves.png") });

  // Korean passage ratio over the compiled story (all <tw-passagedata>
  // elements, widget/script passages included).  Guard against a silent
  // regression to English; --min-korean-ratio makes it a hard check.
  const koreanRatio = await page.evaluate(() => {
    try {
      const passages = [...document.querySelectorAll("tw-passagedata")];
      if (passages.length === 0) return null;
      const korean = passages.filter((p) =>
        /[가-힣]/.test(p.textContent ?? ""),
      ).length;
      return { korean, total: passages.length, ratio: korean / passages.length };
    } catch {
      return null;
    }
  });
  runtime.koreanPassageRatio = koreanRatio;
  if (koreanRatio && args["min-korean-ratio"]) {
    checks.koreanPassageRatio =
      koreanRatio.ratio >= Number(args["min-korean-ratio"]);
  }

  if (args.passage) {
    const passageProbe = await page.evaluate((passage) => {
      try {
        const story = window.SugarCube?.Story ?? window.Story;
        const exists =
          typeof story?.has === "function" ? story.has(passage) : false;
        const item = exists ? story.get(passage) : null;
        return {
          exists,
          text: item?.text ?? "",
          preview: (item?.text ?? "").slice(0, 500),
        };
      } catch {
        return { exists: false, text: "", preview: "" };
      }
    }, args.passage);
    checks.requestedPassageCompiled = passageProbe.exists;
    if (passageProbe.exists) {
      if (args["expect-text"]) {
        checks.expectedPassageSourceText = passageProbe.text.includes(
          args["expect-text"],
        );
      }
      runtime.requestedPassage = args.passage;
      runtime.requestedPassageCharacters = passageProbe.text.length;
      runtime.requestedPassagePreview = passageProbe.preview;
    }
  }
  if (args.wikify) {
    const wikifyProbe = await page.evaluate((source) => {
      try {
        const host = document.createElement("div");
        host.id = "browser-smoke-wikify-probe";
        document.body.append(host);
        const WikifierApi = window.Wikifier;
        if (typeof WikifierApi !== "function") {
          return { rendered: false, error: "Wikifier unavailable" };
        }
        new WikifierApi(host, source);
        const tooltip = host.querySelector("mouse.tooltip-centertop");
        const triggerText = tooltip
          ? [...tooltip.childNodes]
              .filter((node) => node.nodeType === Node.TEXT_NODE)
              .map((node) => node.textContent ?? "")
              .join("")
              .trim()
          : "";
        const tooltipText =
          tooltip?.querySelector("span:last-of-type")?.textContent?.trim() ??
          "";
        const renderedErrors = [...host.querySelectorAll(".error-view, .red")]
          .map((node) => node.textContent?.trim() ?? "")
          .filter(
            (text) => text.startsWith("[ERROR:") || /\berror\b/i.test(text),
          );
        return {
          rendered: true,
          text: host.textContent ?? "",
          html: host.innerHTML,
          triggerText,
          tooltipText,
          renderedErrors,
        };
      } catch (error) {
        return { rendered: false, error: String(error) };
      }
    }, args.wikify);
    checks.requestedWikifyRendered = wikifyProbe.rendered;
    checks.requestedWikifyNoErrors =
      wikifyProbe.rendered && (wikifyProbe.renderedErrors?.length ?? 0) === 0;
    if (args["expect-wikify-text"]) {
      checks.expectedWikifyText = wikifyProbe.text.includes(
        args["expect-wikify-text"],
      );
    }
    if (args["expect-trigger-text"]) {
      checks.expectedWikifyTriggerText =
        wikifyProbe.triggerText === args["expect-trigger-text"];
    }
    if (args["expect-tooltip-text"]) {
      checks.expectedWikifyTooltipText = wikifyProbe.tooltipText.includes(
        args["expect-tooltip-text"],
      );
    }
    runtime.wikifyProbe = wikifyProbe;
  }
  if (args["passage-list"]) {
    const entries = fs
      .readFileSync(args["passage-list"], "utf-8")
      .split("\n")
      .map((line) => line.replace(/\r$/, "").trim())
      .filter(Boolean)
      .map((line) => {
        const [passage, ...rest] = line.split("\t");
        return { passage, expect: rest.join("\t") || "" };
      });
    const results = await page.evaluate((passages) => {
      const story = window.SugarCube?.Story ?? window.Story;
      return passages.map(({ passage, expect }) => {
        try {
          const exists =
            typeof story?.has === "function" ? story.has(passage) : false;
          const item = exists ? story.get(passage) : null;
          const text = item?.text ?? "";
          return {
            passage,
            exists,
            textMatch: !expect || text.includes(expect),
            preview: text.slice(0, 120),
          };
        } catch (error) {
          return {
            passage,
            exists: false,
            textMatch: false,
            error: String(error),
          };
        }
      });
    }, entries);
    checks.passageListOk =
      results.length > 0 &&
      results.every((item) => !item.exists || item.textMatch);
    runtime.passageList = results;
  }
} finally {
  await browser.close();
}

const rendererWarnings = consoleErrors.filter(
  (message) =>
    message.startsWith("Error during effect '") ||
    message.startsWith("Failed to load mask "),
);
const unexpectedConsoleErrors = consoleErrors.filter(
  (message) => !rendererWarnings.includes(message),
);
const assetEventWarnings = pageErrors.filter((message) => message === "Event");
const unexpectedPageErrors = pageErrors.filter(
  (message) => message !== "Event",
);
checks.noUnexpectedPageErrors = unexpectedPageErrors.length === 0;
checks.noUnexpectedConsoleErrors = unexpectedConsoleErrors.length === 0;
const report = {
  schemaVersion: 1,
  html,
  runtime,
  checks,
  warnings: {
    missingImageAssetEvents: assetEventWarnings.length,
    rendererWarnings: rendererWarnings.length,
    optionsCheckSkipped,
    note: "The local source tree has no external img pack; renderer warnings are non-blocking for this UI smoke test. optionsCheckSkipped=true means no --expect-options-text was given, so the options overlay Korean check was skipped.",
  },
  unexpectedPageErrors,
  unexpectedConsoleErrors,
  ok: Object.values(checks).every(Boolean),
};
fs.writeFileSync(
  path.join(output, "report.json"),
  `${JSON.stringify(report, null, 2)}\n`,
);
console.log(JSON.stringify(report, null, 2));
if (!report.ok) process.exitCode = 1;
