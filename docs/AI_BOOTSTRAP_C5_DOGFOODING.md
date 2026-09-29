# AI Bootstrap C5 — Dogfooding de la coordination et décisions go/no-go

Tâche Studio OS : `0fab1892` — [AIB C5] Rapport de dogfooding de la coordination et
décisions go/no-go. Phase `coordination`, roadmap Project AI Bootstrap rév. 4.
Références : DEC-0156 (fan-out NOTIFY), DEC-0157 (coordination en pull).

## 1. Objet

DEC-0157 §Hors périmètre diffère explicitement trois extensions au dogfooding C5, à
trancher par décision :

1. GitWatcher enrichi ;
2. impact Graphify ;
3. relais temps réel du daemon.

La tâche demande de mesurer trois choses — bruit, coût en contexte, collisions
manquées — puis de conclure par des décisions go/no-go. Ce rapport mesure ce qui est
réellement observable dans Studio OS et énonce les décisions, y compris quand la
mesure est insuffisante.

## 2. Méthode et fenêtre

- Lecture `studio_get_recent_changes` (projet Studio OS), 500 événements les plus
  récents, du **2026-09-27T09:14:09Z** au **2026-09-29T17:47:36Z** (~2,5 jours).
- `studio_get_resource_claims` (claims, tous statuts), `studio_get_ai_work`,
  `studio_get_teammate_activity`.
- Contrats de référence : TECH/02 §C2–C4, TECH/03 §coordination.*.
- Aucune donnée n'est inventée : chaque chiffre est compté dans les sorties ci-dessus.

## 3. Résultats mesurés

| Mesure | Valeur | Commentaire |
|---|---|---|
| Événements sur la fenêtre | 500 (plafond de lecture) | ~200/jour |
| Événements `coordination.*` émis | **0** | le canal C3 n'a jamais servi en conditions réelles |
| `ai_work.started` + `ai_work.completed` | 117 événements pour **59** `ai_work_id` uniques | ≈ **2 événements par entrée de journal** (paire de doublons) |
| Événements système Git | 85 (`git.commit` 47 + `git.branch.changed` 38) | 17 % du flux |
| Sessions | 30 (`session.started` 30 / `session.ended` 28) | 30 sessions distinctes |
| `resource.conflict` | 6 sur 2 tâches (`6f401f29`, `846eca51`) | tous avertissements, aucun blocage Git |
| Postes actifs sur la fenêtre | 1 (`Flo-desktop`) | aucun dogfooding deux machines |

Bornes de contexte **documentées** (TECH/02 §C2–C4), non mesurées en conditions
réelles :

- `GET /sync` / `studio_sync` : `limit` défaut 50 / max 200 ; `max_chars` défaut
  12 000 / max 50 000 ; « rien de nouveau » tient en < 300 caractères ; débordement =
  compteurs + renvoi vers `prepare_context`, jamais d'historique brut.
- `POST /coordination` / `studio_coordinate` : `text` 1..280, `refs` ≤ 5 par
  catégorie, **20 signaux par session** (puis `429`).
- Budget du protocole (`tests/protocol/test_agent_protocol.py`) : règle ~150–250
  tokens, 4 skills.

## 4. Constats

1. **Le canal de coordination n'a aucun signal réel.** Sur 2,5 jours de travail
   effectif, 0 `coordination.*` n'a été émis. Les 8 occurrences du mot dans les
   sorties sont des résumés `ai_work` (livraisons C3/C4), pas des événements. Cible
   d'usage (plusieurs sessions/machines) non atteinte : un seul poste actif.
2. **Le bruit dominant n'est pas la coordination.** Il vient de la paire
   `ai_work.started`/`ai_work.completed` (≈ 2× chaque entrée) et du flux système Git
   (85 événements). Toute extension qui ajoute des événements accroît un bruit déjà
   mesurable.
3. **Collisions : 6 avertissements, 0 collision manquée constatée.** Les claims ont
   produit 6 `resource.conflict` sur 2 tâches ; aucun n'a bloqué Git ni entraîné de
   perte. Le mécanisme de recoupement (claims + `studio_sync`) suffit sur la fenêtre.
4. **Deux blocages opérationnels empêchent un vrai dogfooding.** (a) `studio_handoff`
   est absent du serveur MCP connecté (relevé C4) — la clôture en un appel, qui porte
   `coordination.handoff` et le curseur, n'est pas exerçable telle quelle. (b) Le
   budget en caractères du bloc `sync` de `start_work` n'est pas mesuré (relevé C4).

## 5. Limites de la mesure

- **Aucun signal `coordination.*`** : impossible de conclure sur le bruit ou le coût
  du canal lui-même ; seule l'infrastructure préexistante (events Git, claims,
  ai_work) est mesurable.
- **Mono-poste** : la coordination inter-machines, cœur de DEC-0157, n'a pas été
  exercée.
- **Coût en contexte non chiffré** : les bornes documentées existent, mais aucune
  mesure en caractères/tokens d'une réponse réelle n'a été produite.
- Fenêtre plafonnée à 500 événements ; les totaux sont des majorants par le bas.

## 6. Décisions go/no-go proposées

D1–D3 sont enregistrées en `proposed` sous **DEC-0164** ; D4–D5 sous **DEC-0165**.

**D1 — GitWatcher enrichi : NO-GO (report).** Le flux Git est déjà riche (85
événements système sur la fenêtre, émis par l'ingress serveur, TECH/03 §Émission).
Enrichir le watcher ajouterait du bruit avant que le canal de coordination n'ait le
moindre usage. Réexamen quand `coordination.*` > 0 et quand une collision réelle aura
été manquée faute d'information Git.

**D2 — Impact Graphify : NO-GO (report).** Aucune collision mesurée n'est imputable
à l'absence d'impact Graphify ; Graphify est par ailleurs hors du périmètre sémantique
de ce dépôt (politique de skip). Pas de besoin démontré.

**D3 — Relais temps réel du daemon : NO-GO (report).** Le pull via `studio_sync`
n'est pas sous tension : 0 signal de coordination, « rien de nouveau » < 300
caractères. DEC-0156 (NOTIFY) couvre déjà le fan-out SSE des humains/daemon ; ajouter
un relais poussé vers le daemon avant tout usage réel serait de l'infrastructure sans
charge.

**D4 — Remède préalable : mesurer le budget du bloc `sync` de `start_work`** (chars
et tokens réels, tâche avec claims et coordination) et débloquer `studio_handoff`
côté serveur MCP connecté. Sans ces deux points, D1–D3 ne peuvent pas être tranchés
sur des données réelles.

**D5 — Remède de bruit : dédupliquer la paire `ai_work.started`/`ai_work.completed`.**
117 événements pour 59 entrées = ≈ 2× le volume utile ; c'est le premier poste de
bruit à corriger, indépendamment de la coordination.

## 7. Critères de réexamen

Rouvrir D1–D3 lorsqu'au moins deux conditions sont réunies :

- au moins deux postes actifs sur une même fenêtre ;
- `coordination.*` réellement émis (> 0), avec au moins un `handoff` inter-session ;
- budget `sync`/`start_work` mesuré en caractères.

## 8. Preuves

- `studio_get_recent_changes(project_id, since=2026-09-27, limit=500)` → 500
  événements, fenêtre ci-dessus ; distribution par type ; 0 `coordination.*`.
- `studio_get_resource_claims(project_id)` → 6 `resource.conflict`, 2 tâches.
- `studio_get_ai_work(project_id)` → 117 événements `ai_work.*`, 59 ids uniques.
- `studio_get_teammate_activity(project_id)` → 1 poste (`Flo-desktop`).
