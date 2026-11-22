import { expect, type Page } from "@playwright/test";

/** Répond au dialogue confirmDs ouvert ; renvoie son message. */
export async function answerConfirm(page: Page, ok: boolean): Promise<string> {
  const dialog = page.getByRole("dialog").filter({ has: page.locator("[data-ds-confirm]") });
  await expect(dialog).toBeVisible();
  const message = (await dialog.locator("[data-ds-confirm-message]").textContent()) ?? "";
  await dialog.locator(`[data-ds-confirm="${ok ? "ok" : "cancel"}"]`).click();
  await expect(dialog).toHaveCount(0);
  return message;
}
