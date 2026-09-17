import { expect, test } from "@playwright/test";
test("sign in, create, continue, and reopen durable history", async ({ page }) => {
  const message = `Synthetic browser turn ${Date.now()}`;
  const answer = `Synthetic response to: ${message}`;
  const firstDelta = answer.slice(0, Math.max(1, Math.floor(answer.length / 2)));
  await page.goto("/");
  await page.getByLabel("Username").fill(process.env.CORTEX_WEB_TEST_USER ?? "cortex-user");
  await page.getByLabel("Password").fill(process.env.CORTEX_WEB_TEST_PASSWORD ?? "cortex-local-dev");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("button", { name: "New conversation" }).click();
  await page.getByLabel("Message Cortex").fill(message);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(firstDelta, { exact: true })).toBeVisible();
  await expect(page.getByText("Response saved.", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Messages").getByText(message, { exact: true })).toBeVisible();
  await expect(page.getByText(answer, { exact: true })).toBeVisible();
  const conversationUrl = page.url();
  await page.goto("/conversations");
  await page.getByRole("link", { name: /^Conversation / }).first().click();
  await expect(page).toHaveURL(conversationUrl);
  await expect(page.getByText(message, { exact: true })).toBeVisible();
});

test("stopping after a received delta publishes no partial turn", async ({ page }) => {
  const message = `Cancelled browser turn ${Date.now()}`;
  const answer = `Synthetic response to: ${message}`;
  const firstDelta = answer.slice(0, Math.max(1, Math.floor(answer.length / 2)));
  await page.goto("/");
  await page.getByLabel("Username").fill(process.env.CORTEX_WEB_TEST_USER ?? "cortex-user");
  await page.getByLabel("Password").fill(process.env.CORTEX_WEB_TEST_PASSWORD ?? "cortex-local-dev");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("button", { name: "New conversation" }).click();
  await expect(page).toHaveURL(/\/conversations\/[0-9a-f-]+$/);
  const conversationUrl = page.url();

  await page.getByLabel("Message Cortex").fill(message);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(firstDelta, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByText("Stopped. Nothing was saved.", { exact: true })).toBeVisible();

  await page.goto(conversationUrl);
  await expect(page.getByText("What are you working on?", { exact: true })).toBeVisible();
  await expect(page.getByText(message, { exact: true })).not.toBeVisible();
  await expect(page.getByText(answer, { exact: true })).not.toBeVisible();
});

test("Northstar lookup shows read-only evidence outside conversation history", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Username").fill(process.env.CORTEX_WEB_TEST_USER ?? "cortex-user");
  await page.getByLabel("Password").fill(process.env.CORTEX_WEB_TEST_PASSWORD ?? "cortex-local-dev");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("link", { name: "Knowledge lookup" }).click();
  await page.getByLabel("Search knowledge").fill("Revenue is £45m");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const evidence = page.getByRole("article", { name: "Knowledge evidence" });
  await expect(evidence.getByRole("heading", { name: "Project Orion" })).toBeVisible();
  await expect(evidence.getByText("Project Orion operating update")).toBeVisible();
  await expect(evidence).toContainText("£45m");
  await page.getByLabel("Ask Cortex").fill("Operating Partner");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const answer = page.getByRole("article", { name: "Knowledge answer" });
  await expect(answer).toContainText("Synthetic local model answer");
  await expect(answer).toContainText("Project Orion operating update");
  await expect(answer).toContainText("PageVersion:");
  await expect(answer.getByRole("listitem").filter({ hasText: "PageVersion:" })).toHaveCount(3);
  await expect(page.getByLabel("Messages")).toHaveCount(0);
  const cookies = await page.context().cookies();
  expect(cookies.find((cookie) => cookie.name === "cortex-session")).toMatchObject({ httpOnly: true, sameSite: "Lax" });
  expect(cookies.some((cookie) => cookie.value.includes("cortex-local-dev") || cookie.value.includes("brain-local-dev"))).toBe(false);
  expect(await page.content()).not.toContain("cortex-local-dev");
  expect(await page.content()).not.toContain("brain-local-dev");
  await page.reload();
  await expect(page.getByRole("article", { name: "Knowledge evidence" })).toHaveCount(0);
  await expect(page.getByRole("article", { name: "Knowledge answer" })).toHaveCount(0);
});
