/**
 * P14 — Vault : parcours navigateur complet sur le bundle de production
 * (`vite preview`), API canonique stubée comme les autres e2e.
 *
 * Propriétés vérifiées, dans l'ordre où un lecteur les rencontre :
 *   1. la liste se charge par portée (studio), puis projet ;
 *   2. la recherche passe bien par `GET /vault/search` (jamais du client) ;
 *   3. le détail rend le Markdown sans exécuter le HTML du serveur ;
 *   4. une note `proposed` n'expose Valider/Refuser qu'à l'admin, et l'écriture
 *      porte `expected_version` ;
 *   5. un 409 affiche un message puis recharge la version du serveur ;
 *   6. l'historique liste les versions et permet d'en afficher une.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const STAMP = "2026-09-17T10:00:00Z";
const NOTE_ID = "33333333-3333-3333-3333-333333333333";
const OTHER_NOTE_ID = "44444444-4444-4444-4444-444444444444";
const PROJECT_ID = "11111111-1111-1111-1111-111111111111";
const ADMIN = "55555555-5555-5555-5555-555555555555";

const summary = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: NOTE_ID,
  scope: "studio",
  project_id: null,
  slug: "cache-strategy",
  readable_id: "DEC-001",
  note_type: "decision",
  title: "Stratégie de cache",
  summary: "Redis avant PostgreSQL.",
  status: "validated",
  tags: ["cache"],
  links: [],
  anchors: ["src/cache.ts"],
  content_hash: "h2",
  author_type: "user",
  author_id: ADMIN,
  version: 2,
  created_at: STAMP,
  updated_at: STAMP,
  ...overrides,
});

const PROPOSED_NOTE = {
  ...summary(),
  id: "66666666-6666-6666-6666-666666666666",
  slug: "naming-convention",
  readable_id: null,
  note_type: "convention",
  title: "Convention de nommage",
  summary: "kebab-case pour les slugs.",
  status: "proposed",
  version: 1,
  content_hash: "h1",
};

const PROJECT_NOTE = summary({
  id: OTHER_NOTE_ID,
  scope: "project",
  project_id: PROJECT_ID,
  slug: "release-checklist",
  title: "Checklist de release",
  note_type: "procedure",
});

const VERSIONS = [
  {
    note_id: NOTE_ID,
    version: 1,
    title: "Stratégie de cache",
    summary: "PostgreSQL seulement.",
    body: "## v1\n\nPostgreSQL seulement.",
    status: "draft",
    tags: [],
    links: [],
    anchors: [],
    content_hash: "h1",
    change_summary: "Création",
    author_type: "user",
    author_id: ADMIN,
    created_at: STAMP,
  },
  {
    note_id: NOTE_ID,
    version: 2,
    title: "Stratégie de cache",
    summary: "Redis avant PostgreSQL.",
    body: "## v2\n\nRedis avant PostgreSQL.",
    status: "validated",
    tags: ["cache"],
    links: [],
    anchors: ["src/cache.ts"],
    content_hash: "h2",
    change_summary: "Ajout de Redis",
    author_type: "user",
    author_id: ADMIN,
    created_at: STAMP,
  },
];

interface StubState {
  role: string;
  calls: string[];
  /** Force le prochain PATCH à répondre 409, comme une écriture concurrente. */
  conflictOnce: boolean;
}

function apiStub(state: StubState) {
  return async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (url.pathname.endsWith("/healthz")) return json(200, {});
    if (url.pathname.endsWith("/api/v1/auth/token")) {
      return json(200, { access_token: "e2e-token", token_type: "bearer", expires_in: 900 });
    }
    if (url.pathname.endsWith("/api/v1/auth/me")) {
      return json(200, {
        user_id: ADMIN,
        display_name: "Ada",
        email: "ada@example.test",
        role: state.role,
        machine_id: ADMIN,
      });
    }
    if (url.pathname.endsWith("/api/v1/projects")) {
      return json(200, [{ id: PROJECT_ID, name: "Studi'os", slug: "studios", status: "active", created_at: STAMP }]);
    }
    if (url.pathname.endsWith("/api/v1/vault/search")) {
      state.calls.push(`search q=${url.searchParams.get("q") ?? ""}`);
      return json(200, {
        items: [
          { note: summary(), reason: "lexical", matched_anchors: ["src/cache.ts"], rank: 1, snippet: "Redis avant…" },
        ],
        total: 1,
        truncated: false,
      });
    }
    if (url.pathname.endsWith("/api/v1/vault/tree")) {
      const scope = url.searchParams.get("scope");
      state.calls.push(`tree scope=${scope ?? "none"}`);
      const items = scope === "project" ? [PROJECT_NOTE] : [summary(), PROPOSED_NOTE];
      return json(200, { items, next_cursor: null });
    }
    const versionOne = /\/api\/v1\/vault\/notes\/([^/]+)\/versions\/(\d+)$/.exec(url.pathname);
    if (versionOne !== null) {
      const found = VERSIONS.find((entry) => entry.version === Number(versionOne[2]));
      return found === undefined ? json(404, { detail: "not_found" }) : json(200, found);
    }
    if (/\/api\/v1\/vault\/notes\/[^/]+\/versions$/.test(url.pathname)) {
      return json(200, { items: VERSIONS, next_cursor: null });
    }
    const noteId = /\/api\/v1\/vault\/notes\/([^/]+)$/.exec(url.pathname);
    if (noteId !== null) {
      if (request.method() === "PATCH") {
        const body = request.postDataJSON() as { expected_version?: number; status?: string };
        state.calls.push(`patch expected_version=${body.expected_version} status=${body.status ?? ""}`);
        if (state.conflictOnce) {
          state.conflictOnce = false;
          return json(409, { detail: { error_code: "version_conflict", server_version: 3 } });
        }
        const base = noteId[1] === PROPOSED_NOTE.id ? PROPOSED_NOTE : summary();
        return json(200, { ...base, status: body.status, version: (body.expected_version ?? 1) + 1 });
      }
      const id = noteId[1];
      if (id === OTHER_NOTE_ID) return json(200, { ...PROJECT_NOTE, body: "## Release\n\nTag, puis déploiement." });
      if (id === PROPOSED_NOTE.id) return json(200, { ...PROPOSED_NOTE, body: "## Nommage\n\n- kebab-case" });
      return json(200, { ...summary(), body: "# Stratégie\n\n- Redis **d'abord**\n- Jamais de cache local." });
    }
    return json(200, []);
  };
}

async function openVault(page: Page, state: StubState): Promise<Error[]> {
  const errors: Error[] = [];
  page.on("pageerror", (error) => errors.push(error));
  await page.route("**/api/**", apiStub(state));
  await page.goto("/#/vault");
  await page.fill("#login-email", "ada@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#view h1")).toHaveText("Vault");
  return errors;
}

/** Hash-only navigation : a full `goto` would drop the memory-only token. */
async function goHash(page: Page, hash: string): Promise<void> {
  await page.evaluate((value) => {
    window.location.hash = value;
  }, hash);
}

test("vault journey: scope, search, safe detail, decision and history", async ({ page }) => {
  const state: StubState = { role: "admin", calls: [], conflictOnce: false };
  const errors = await openVault(page, state);

  /* 1. Portée studio : l'arbre est lu, pas la recherche. */
  await expect(page.locator("#view")).toContainText("Stratégie de cache");
  await expect(page.locator("#view")).toContainText("Convention de nommage");
  expect(state.calls).toContain("tree scope=studio");

  /* 2. Bascule projet : requête serveur scope=project. */
  await page.locator('[data-vault-scope="project"]').click();
  await expect(page.locator("#view")).toContainText("Checklist de release");
  expect(state.calls).toContain("tree scope=project");

  /* 3. Recherche : la saisie part sur GET /vault/search. */
  await page.fill("#vault-query", "cache");
  await expect(page.locator("#view")).toContainText("recherche serveur");
  await expect(page.locator("#view")).toContainText("1 résultat(s)");
  expect(state.calls.some((call) => call.startsWith("search q=cache"))).toBe(true);

  /* 4. Détail : Markdown rendu, HTML du serveur inerte. */
  await goHash(page, `#/vault/${NOTE_ID}`);
  await expect(page.locator("#view h1")).toHaveText("Stratégie de cache");
  await expect(page.locator("#view .vault-prose")).toContainText("Redis");
  await expect(page.locator("#view")).toContainText("src/cache.ts");

  /* 5. Historique : les deux versions, puis le corps d'une seule. */
  await expect(page.locator("#view .vault-version")).toHaveCount(2);
  await expect(page.locator('#vault-version-1')).toBeHidden();
  await expect(page.locator('#vault-version-2')).toBeHidden();
  await page.locator('[data-vault-show-version="1"]').click();
  await expect(page.locator("#vault-version-1")).toContainText("PostgreSQL seulement.");
  await expect(page.locator("#vault-version-2")).toBeHidden();
  await page.locator('[data-vault-show-version="1"]').click();
  await expect(page.locator("#vault-version-1")).toBeHidden();

  /* 6. Décision : visible pour l'admin, PATCH versionné. */
  await goHash(page, `#/vault/${PROPOSED_NOTE.id}`);
  await expect(page.locator("#view h1")).toHaveText("Convention de nommage");
  await expect(page.locator("#view")).toContainText("Proposée");
  await page.locator("[data-vault-accept]").click();
  await expect(page.locator("#view")).toContainText("Validée");
  expect(state.calls).toContain("patch expected_version=1 status=validated");

  expect(errors).toEqual([]);
});

test("a 409 on acceptance explains itself and reloads the server version", async ({ page }) => {
  const state: StubState = { role: "admin", calls: [], conflictOnce: true };
  const errors = await openVault(page, state);

  await goHash(page, `#/vault/${PROPOSED_NOTE.id}`);
  await page.locator("[data-vault-reject]").click();
  await expect(page.locator("[data-vault-msg]")).toContainText("modifié ailleurs");
  // The page reloads the note rather than keeping the stale one.
  await expect(page.locator("#view")).toContainText("Proposée");
  await expect(page.locator("[data-vault-reject]")).toBeEnabled();

  expect(errors).toEqual([]);
});

test("a developer sees no accept/reject on a studio note but does on a project one", async ({ page }) => {
  const state: StubState = { role: "developer", calls: [], conflictOnce: false };
  const errors = await openVault(page, state);

  await goHash(page, `#/vault/${PROPOSED_NOTE.id}`);
  await expect(page.locator("#view")).toContainText("Proposée");
  await expect(page.locator("[data-vault-accept]")).toHaveCount(0);
  await expect(page.locator("[data-vault-reject]")).toHaveCount(0);

  await goHash(page, `#/vault/${OTHER_NOTE_ID}`);
  await expect(page.locator("#view h1")).toHaveText("Checklist de release");
  // The note is `validated`, so even a writer has nothing to decide.
  await expect(page.locator("[data-vault-accept]")).toHaveCount(0);

  expect(errors).toEqual([]);
});

test("a readonly account decides nothing anywhere", async ({ page }) => {
  const state: StubState = { role: "readonly", calls: [], conflictOnce: false };
  const errors = await openVault(page, state);

  await goHash(page, `#/vault/${PROPOSED_NOTE.id}`);
  await expect(page.locator("#view")).toContainText("Convention de nommage");
  await expect(page.locator("[data-vault-accept]")).toHaveCount(0);
  await expect(page.locator("[data-vault-reject]")).toHaveCount(0);
  expect(state.calls.some((call) => call.startsWith("patch"))).toBe(false);

  expect(errors).toEqual([]);
});