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
