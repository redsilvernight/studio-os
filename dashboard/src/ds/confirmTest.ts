/** Aide de test : répond au dialogue confirmDs ouvert (true = Confirmer, false = Annuler). */
export async function answerConfirm(ok: boolean): Promise<string> {
  const sel = `[data-ds-confirm="${ok ? "ok" : "cancel"}"]`;
  let button: HTMLElement | null = null;
  for (let i = 0; i < 50 && button === null; i += 1) {
    button = document.querySelector<HTMLElement>(sel);
    if (button === null) await new Promise((resolve) => setTimeout(resolve, 0));
  }
  if (button === null) throw new Error("aucun dialogue de confirmation ouvert");
  const message = document.querySelector("[data-ds-confirm-message]")?.textContent ?? "";
  button.click();
  await Promise.resolve();
  return message;
}
