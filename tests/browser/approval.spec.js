const { test, expect } = require("@playwright/test");
const fs = require("fs");
const path = require("path");
let credentials;
test.beforeEach(async ({ context, page }) => {
  const fixturePath = path.join("/tmp", "tapgate-browser-fixture.json");
  credentials = JSON.parse(fs.readFileSync(fixturePath));
  credentials.consumer = credentials.consumers.shift();
  fs.writeFileSync(fixturePath, JSON.stringify(credentials));
  await context.addCookies([
    {
      name: "tapgate",
      value: credentials.consumer,
      domain: "127.0.0.1",
      path: "/",
      httpOnly: true,
      sameSite: "Strict",
    },
  ]);
  await page.goto("/");
  await expect(page.locator("#workspace")).toBeVisible();
});
async function add(page, changes = {}) {
  const task = "Browser " + Math.random().toString(36).slice(2, 8);
  const response = await page.request.post("/api/requests", {
    headers: {
      Authorization: "Bearer " + credentials.producer,
      "X-TapGate": "1",
    },
    data: {
      task,
      source: "codex",
      host: "TEST HOST · SSH",
      session: "synthetic",
      kind: "command",
      operation: "pwd",
      ...changes,
    },
  });
  expect(response.status()).toBe(201);
  const item = await response.json();
  await page.locator("#refresh").click();
  return {
    item,
    card: page
      .locator("article")
      .filter({ has: page.getByRole("heading", { name: task, exact: true }) }),
  };
}
test("white glass inbox renders with Watch preview and demo boundary", async ({
  page,
}) => {
  await expect(
    page.getByRole("heading", { name: "承認トレイ", exact: true }),
  ).toBeVisible();
  await expect(page.locator("#demo-banner")).toBeVisible();
  await expect(page.locator(".watch-case")).toBeVisible();
  await expect(page.locator("body")).toHaveCSS(
    "background-image",
    /linear-gradient/,
  );
  await page.screenshot({
    path: "artifacts/browser-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "artifacts/browser-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
});
test("one tap on Watch commits real server decision and pins result", async ({
  page,
}) => {
  const { item, card } = await add(page);
  await card.locator("h2").click();
  await page
    .locator("#watch-content")
    .getByRole("button", { name: "許可" })
    .click();
  await expect(page.locator("#watch-content")).toContainText("許可済み");
  await page.locator("#refresh").click();
  await expect(page.locator("#watch-content")).toContainText("許可済み");
  await expect(
    page.locator("#watch-content").getByRole("button", { name: "許可" }),
  ).toHaveCount(0);
  const result = await page.request.get("/api/requests/" + item.id, {
    headers: { Authorization: "Bearer " + credentials.producer },
  });
  expect((await result.json()).state).toBe("approved");
});
test("deny does not approve and appears in history", async ({ page }) => {
  const { item, card } = await add(page);
  await card.getByRole("button", { name: "拒否", exact: true }).click();
  await expect(card).toContainText("拒否済み");
  await page.locator("[data-tab=history]").click();
  await expect(
    page.locator('article[data-id="' + item.id + '"]').getByText("拒否済み"),
  ).toBeVisible();
});
test("publish operation requires full detail and has no Watch approve", async ({
  page,
}) => {
  const { card } = await add(page, { operation: "git push origin main" });
  await card.locator("h2").click();
  await expect(
    page.locator("#watch-content").getByRole("button", { name: "許可" }),
  ).toHaveCount(0);
  await page
    .locator("#watch-content")
    .getByRole("button", { name: "iPhoneで全文確認" })
    .click();
  await expect(page.locator("dialog")).toBeVisible();
  await expect(page.locator("dialog pre").first()).toHaveText(
    "git push origin main",
  );
  await page.locator("dialog").getByRole("button", { name: "許可" }).click();
  await expect(page.locator("dialog")).toContainText("許可済み");
});
test("long action shows full content in detail", async ({ page }) => {
  const operation = "python3 script.py " + "very-long-argument-".repeat(40);
  const { card } = await add(page, { operation });
  await card.getByRole("button", { name: /詳細/ }).click();
  await expect(page.locator("dialog pre").first()).toHaveText(operation);
  await page.getByRole("button", { name: "閉じる", exact: true }).click();
  await expect(page.locator("dialog")).not.toBeVisible();
});
test("source filters and tabs are functional", async ({ page }) => {
  await page.locator("[data-source=claude]").click();
  for (const name of await page
    .locator("article .source-name")
    .allTextContents())
    expect(name).toBe("Claude Code");
  await page.locator("[data-tab=settings]").click();
  await expect(page.locator("#settings-panel")).toBeVisible();
  await expect(page.locator("#requests")).not.toBeVisible();
  await page.locator("[data-tab=pending]").click();
  await expect(page.locator("#requests")).toBeVisible();
});
test("network failure never shows a successful decision", async ({ page }) => {
  const { card } = await add(page);
  await card.locator("h2").click();
  await page.route("**/api/requests/*/decision", (route) =>
    route.abort("failed"),
  );
  await page
    .locator("#watch-content")
    .getByRole("button", { name: "許可" })
    .click();
  await expect(page.locator("#status")).toContainText(/Failed|fetch|Load/);
  await expect(page.locator("#watch-content")).not.toContainText("許可済み");
});
test("double click emits only one decision POST", async ({ page }) => {
  const { card } = await add(page);
  await card.locator("h2").click();
  let requests = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/decision")) requests++;
  });
  await page
    .locator("#watch-content")
    .getByRole("button", { name: "許可" })
    .dblclick({ delay: 30 });
  await expect(page.locator("#watch-content")).toContainText("許可済み");
  expect(requests).toBe(1);
});
test("phone dismissal does not decide", async ({ page }) => {
  const { item, card } = await add(page, { operation: "rm ./temporary-file" });
  await card.getByRole("button", { name: "iPhoneで全文確認" }).click();
  await page.keyboard.press("Escape");
  const response = await page.request.get("/api/requests/" + item.id, {
    headers: { Authorization: "Bearer " + credentials.producer },
  });
  expect((await response.json()).state).toBe("pending");
});
test("informational prompts cannot be approved", async ({ page }) => {
  const { card } = await add(page, {
    informational: true,
    operation: "sandbox network permission",
    kind: "notification",
  });
  await card.locator("h2").click();
  await expect(page.locator("#watch-content")).toContainText(
    "元のターミナルで対応",
  );
  await expect(card.getByRole("button", { name: "許可" })).toHaveCount(0);
});
test("XSS task and command rendered as text", async ({ page }) => {
  const { card } = await add(page, {
    operation: '<img src=x onerror="window.pwned=true">',
  });
  await expect(card.locator(".operation")).toContainText("<img");
  await expect(card.locator("img")).toHaveCount(0);
  expect(await page.evaluate(() => window.pwned)).toBeUndefined();
});
test("mobile layout has no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".tabs")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
test("reduced motion removes spring animations", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const { card } = await add(page);
  expect(
    parseFloat(
      await card.evaluate((el) => getComputedStyle(el).animationDuration),
    ),
  ).toBeLessThan(0.01);
});
test("keyboard can open details and close with Escape", async ({ page }) => {
  const { card } = await add(page);
  await card.getByRole("button", { name: /詳細/ }).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("dialog")).not.toBeVisible();
});
test("logout revokes the session and returns to pairing", async ({ page }) => {
  await page.locator("[data-tab=settings]").click();
  await page.locator("#logout").click();
  await expect(page.locator("#pairing")).toBeVisible();
});

test("expired request loses its approval buttons in the browser", async ({
  page,
}) => {
  const { item, card } = await add(page);
  await card.locator("h2").click();
  require("child_process").execFileSync("python3", [
    "-c",
    "import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute('UPDATE requests SET expires=0 WHERE id=?',(sys.argv[2],)); db.commit()",
    credentials.db,
    item.id,
  ]);
  await page.locator("#refresh").click();
  await expect(page.locator("#watch-content")).toContainText("期限切れ");
  await expect(
    page.locator("#watch-content").getByRole("button", { name: "許可" }),
  ).toHaveCount(0);
});
test("reconnection restores actionable controls", async ({ page, context }) => {
  const { card } = await add(page);
  await card.locator("h2").click();
  await context.setOffline(true);
  await page.locator("#refresh").click();
  await expect(page.locator("#connection")).toContainText("オフライン");
  await expect(
    page.locator("#watch-content").getByRole("button", { name: "許可" }),
  ).toBeDisabled();
  await context.setOffline(false);
  await page.locator("#refresh").click();
  await expect(
    page.locator("#watch-content").getByRole("button", { name: "許可" }),
  ).toBeEnabled();
});
test("invalid pairing code keeps user on pairing screen", async ({
  page,
  context,
}) => {
  await context.clearCookies();
  await page.reload();
  await expect(page.locator("#pairing")).toBeVisible();
  await page.getByLabel("ペアリングコード").fill("99999999");
  await page.getByRole("button", { name: "接続", exact: true }).click();
  await expect(page.locator("#pair-error")).not.toBeEmpty();
  await expect(page.locator("#workspace")).not.toBeVisible();
});
