# Studio OS v0.13.0 — 18/11/2026

## Nouveautés

- Résolution du workspace par le MCP via les roots MCP ou le cwd (P2-mcp-local).
- Dépôts détectés non suivis listés dans Workspaces (P3-detected).
- Assistant de configuration du dashboard réduit au poste (P3-onboarding).
- Suivi par dépôt : membre, non-membre et fork (P4-e2e) ; le client envoie des URL à `resolve-repository`.

## Corrections

- Liste des dépôts détectés dégradée mais fonctionnelle avec un ancien démon ; contrat MCP précisant le registre local.
- CI : course au rattachement MCP, typage `last_seen_at`, export mort, compteur de commandes pont.

## Notes de mise à jour (contrats, migrations, config)

- Aucune migration. Le client envoie des URL à `resolve-repository` : mettre à jour studio-client avec le serveur.
