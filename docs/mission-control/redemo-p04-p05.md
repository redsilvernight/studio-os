# Redémonstration P04 / P05 après correctifs

Checklist des deux redémonstrations attendues par P06 (`p06-gate.md`). Cadre :
DEC-0212, pile locale jetable ; la production (VPS OVH, DEC-0205) n'est jamais
utilisée. Résultats à reporter dans `p04-gate.md` et `p05-gate.md`, preuves
sous `output/gate-demo-local/` (ignoré par Git). La revue humaine reste requise
après coup.

## Préparation commune

1. `dev` à jour sur `Flo` et `Flo-laptop` ; noter le SHA.
2. Pile `studio-gate-demo` sur `Flo` depuis `docker/docker-compose.yml`
   (`docker compose -p studio-gate-demo`), volumes nommés, sans `docker/.data` ;
   Caddy publié sur `127.0.0.1:8865` et, pour P05, sur l'IP Tailscale de `Flo`
   seulement. Migrations à head.
3. Projet jetable, dépôt pilote avec une branche `dev`, entrée MCP `studio-os`
   dans `opencode.json`, clé API du CLI opencode valide.
4. Un daemon isolé par machine : `APPDATA` et `XDG_CONFIG_HOME` dédiés, aucun
   `STUDIO_MCP_*` hérité ; machine enrôlée sur la pile démo.
5. Fin : `docker compose -p studio-gate-demo down -v`, suppression des
   dossiers `APPDATA` de démo.

## P04 — handoff dans un lancement profilé (`d943816c`)

| Étape | Attendu |
|---|---|
| Agent de Bibliothèque `p04-architect`, profil `architecture-read-only`, `claude-code` | Lancement `succeeded`, snapshot `capture ok`, `access_mode: read_only` |
| Session du lancement | `studio_start_work` **et** `studio_handoff` observés avec l'`agent_id` du serveur démo, pas celui du hook de production |
| Messagerie en `read_only` (PR #156, si fusionnée) | `SendMessage` et les outils hors `Read,Grep,Glob` indisponibles |
| Rejeu confirmé | Handoff observé aussi sur le rejeu ; plus de `handoff_not_observed` |

## P05 — deux machines (`aed07f4e`, `e3d162ee`, `349913e8`)

Roadmap jetable : S1 (A), S2 (B, `depends_on` S1), C indépendante ; un slot
par machine.

| Étape | Attendu |
|---|---|
| Deux batchs successifs rapides sur un slot | Jamais deux lancements admis sur la même machine ; pas de refus local `capacity_reached` nécessaire |
| Poste avec opencode non configuré | Machine non éligible pour opencode (`harness_incompatible`) ; opencode absent du sélecteur |
| Dry-run puis nouveau dry-run dans le dashboard | Le harness choisi reste sélectionné |
| Batch A + C, handoff A, B | Comme au 19 octobre : parallélisme, B admise une seule fois après S1 `done` |
| Coupure du daemon `Flo-laptop` | Poste hors ligne, aucun doublon ; réadmission après annulation ou orphelin |
| Session navigateur > 15 min | Expiration attendue (limite connue) ; à noter, pas un échec |
