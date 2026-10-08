# Import P08 — rapport de divergences DEC (fichiers ↔ serveur)

Politique : DEC-0192. Le contenu de l'ADR fichier fait foi ; aucune divergence n'est fusionnée automatiquement.

Rejouer : `studio-admin vault import-decisions --decisions-dir docs/decisions --project <projet> [--server-snapshot docs/DEC_BASELINE_P00.json | --apply --author-email <admin>] [--report <fichier>]`.

- Notes planifiées : **217** (189 numérotées, 28 variantes serveur sans numéro)
- Numéro max connu : **DEC-0191**

## Collisions de numéro (décisions différentes) (28)

- `DEC-0086` : fichier « Roadmaps P2/P3 : domaine, persistance (migration 0013) et API HTTP canonique » ≠ serveur « Roadmaps P6 : section Roadmap de studio_prepare_context (roadmap active + overview, budget dédié 25 %, additif) » (ratio 0.30) ; variante serveur importée sans numéro, tag legacy-server-dec-0086
- `DEC-0087` : fichier « Roadmaps P4/P5 : surface MCP par intentions, initialisation de projet neutre à roadmap optionnelle » ≠ serveur « DEC-0088 Roadmaps P8 : propositions de revision, relecture humaine et file de review » (ratio 0.38) ; variante serveur importée sans numéro, tag legacy-server-dec-0087
- `DEC-0088` : fichier « Roadmaps P6 : section Roadmap de studio_prepare_context, budgetée, optionnelle et neutre » ≠ serveur « Roadmaps : DEC P8 renumérotée DEC-0089 ; IDs serveur non synchronisés avec les fiches ADR » (ratio 0.34) ; variante serveur importée sans numéro, tag legacy-server-dec-0088
- `DEC-0089` : fichier « Roadmaps P8 : propositions de revision, relecture humaine (approve/request-changes/reject) et file de review » ≠ serveur « Roadmaps P10 : validation finale, review par le rôle, correction ordre d'initialisation proposed (DEC-0090) » (ratio 0.27) ; variante serveur importée sans numéro, tag legacy-server-dec-0089
- `DEC-0090` : fichier « Roadmaps P10 : validation E2E finale, frontière de review par le rôle, provenance conservée et correction de l'ordre d'initialisation proposed » ≠ serveur « Desktop P0 : Tauri 2 comme shell natif mince autour du Dashboard autonome » (ratio 0.19) ; variante serveur importée sans numéro, tag legacy-server-dec-0090
- `DEC-0091` : fichier « Desktop P0 : Tauri 2 comme shell mince, frontières Desktop/bridge/daemon/serveur » ≠ serveur « Desktop P0 : abstraction CodeGraphProvider et Graphify installé séparément » (ratio 0.34) ; variante serveur importée sans numéro, tag legacy-server-dec-0091
- `DEC-0096` : fichier « Desktop P9 : adaptateurs de harnais au scope projet, jeton par référence, fail-closed » ≠ serveur « DEC-0099 Desktop P9 : fourniture du jeton machine aux harnais par credential helper, état token_missing » (ratio 0.42) ; variante serveur importée sans numéro, tag legacy-server-dec-0096
- `DEC-0097` : fichier « Desktop P11 : premier lancement guidé, workspace servi, deux commandes additives » ≠ serveur « Isolation projet minimale : membership User→Project (rôle = quoi, membership = où) » (ratio 0.26) ; variante serveur importée sans numéro, tag legacy-server-dec-0097
- `DEC-0098` : fichier « Decisions accept/supersede : transitions admin-only, et identite technique dashboard exclue des Machines » ≠ serveur « DU-0/A — Inscription publique fermée par défaut et activation vérifiée » (ratio 0.33) ; variante serveur importée sans numéro, tag legacy-server-dec-0098
- `DEC-0099` : fichier « Workflow W2 : le hook SessionStart assure lAgent du harnais (ensure, sans autorite) » ≠ serveur « DU-0/B — JWT court avec version de révocation, sans refresh token en V1 » (ratio 0.33) ; variante serveur importée sans numéro, tag legacy-server-dec-0099
- `DEC-0100` : fichier « Workflow W2b : setup-hooks distribue les hooks ensure sur fresh machine » ≠ serveur « DU-0/C — Chaîne proxy de confiance et anti-abus par étages » (ratio 0.13) ; variante serveur importée sans numéro, tag legacy-server-dec-0100
- `DEC-0101` : fichier « Enregistrement Agent expose via MCP » ≠ serveur « DU-0/D — Versions séparées et matrice de compatibilité N/N-1 fail-closed » (ratio 0.32) ; variante serveur importée sans numéro, tag legacy-server-dec-0101
- `DEC-0102` : fichier « Tasks : emission serveur des evenements task.* a chaque ecriture » ≠ serveur « DU-0/E — Artéfact Windows signé, updater minisign et promotion sans rebuild » (ratio 0.26) ; variante serveur importée sans numéro, tag legacy-server-dec-0102
- `DEC-0104` : fichier « Desktop P9 : un identifiant Studi'OS dédié par couple poste + outil d'IA, état token_missing » ≠ serveur « DU-0/A — Inscription publique fermée par défaut (rév. corrigée) » (ratio 0.26) ; variante serveur importée sans numéro, tag legacy-server-dec-0104
- `DEC-0144` : fichier « AIB-B : plan de bootstrap calcule cote serveur, en lecture seule » ≠ serveur « AIB-I — Agent : harness + clé stable locale, stable_key = résolution » (ratio 0.40) ; variante serveur importée sans numéro, tag legacy-server-dec-0144
- `DEC-0145` : fichier « AIB-C : ownership blocs delimites, anti-drift par adapters check » ≠ serveur « AIB-G — Aucune réclamation automatique sans task_id explicite » (ratio 0.30) ; variante serveur importée sans numéro, tag legacy-server-dec-0145
- `DEC-0146` : fichier « AIB-D : ressources communes servies a la demande, protocole seul materialise » ≠ serveur « AIB-J — Seul le propriétaire peut lancer sur sa machine » (ratio 0.21) ; variante serveur importée sans numéro, tag legacy-server-dec-0146
- `DEC-0147` : fichier « AIB-E : cablage MCP et harness machine-local, jamais dans le depot » ≠ serveur « AIB-B — Plan de bootstrap calculé côté serveur, en lecture seule » (ratio 0.27) ; variante serveur importée sans numéro, tag legacy-server-dec-0147
- `DEC-0148` : fichier « AIB-F : lancement distant en modele pull tire par le daemon » ≠ serveur « AIB-C — Blocs délimités + anti-drift par adapters check » (ratio 0.46) ; variante serveur importée sans numéro, tag legacy-server-dec-0148
- `DEC-0149` : fichier « AIB-G : aucune reclamation automatique sans task_id explicite » ≠ serveur « AIB-H — Session reprenable (même agent, même tâche) » (ratio 0.36) ; variante serveur importée sans numéro, tag legacy-server-dec-0149
- `DEC-0150` : fichier « AIB-H : session reprenable meme agent et meme tache » ≠ serveur « AIB-D — Ressources servies à la demande, protocole seul matérialisé » (ratio 0.35) ; variante serveur importée sans numéro, tag legacy-server-dec-0150
- `DEC-0151` : fichier « AIB-I : agent porte harness et cle stable locale, stable_key reste resolution » ≠ serveur « AIB-F — Lancement distant en modèle pull tiré par le daemon » (ratio 0.43) ; variante serveur importée sans numéro, tag legacy-server-dec-0151
- `DEC-0152` : fichier « AIB-J : seul le proprietaire de la machine peut y lancer une tache » ≠ serveur « AIB-E — Câblage MCP/harness machine-local, jamais dans le dépôt » (ratio 0.40) ; variante serveur importée sans numéro, tag legacy-server-dec-0152
- `DEC-0154` : fichier « P0 : reconciliation Desktop livree, ordre tranche, matrice validee » ≠ serveur « P0 — Vocabulaire harness canonique kebab-case » (ratio 0.30) ; variante serveur importée sans numéro, tag legacy-server-dec-0154
- `DEC-0155` : fichier « P0 : vocabulaire harness canonique kebab-case » ≠ serveur « P0 — Réconciliation Desktop, ordre tranché, matrice validée » (ratio 0.37) ; variante serveur importée sans numéro, tag legacy-server-dec-0155
- `DEC-0164` : fichier « AI Bootstrap P2 : expansion récursive de composed_agent dans le moteur P5, sans second moteur » ≠ serveur « AIB C5 — les trois extensions différées de la coordination restent reportées (no-go) » (ratio 0.31) ; variante serveur importée sans numéro, tag legacy-server-dec-0164
- `DEC-0180` : fichier « AIB L2 : identite agent par (harnais, provider, modele) sur tous les harnais » ≠ serveur « Compatibilité du manifest bootstrap : lecture v1 uniquement et refus explicite » (ratio 0.27) ; variante serveur importée sans numéro, tag legacy-server-dec-0180
- `DEC-0187` : fichier « Vault serveur à deux portées (studio / projet) et DEC unifiées » ≠ serveur « 0.3.0 : cadrage (nom Kartouche, périmètre, choix) » (ratio 0.22) ; variante serveur importée sans numéro, tag legacy-server-dec-0187

## Titres divergents (même décision) (67)

- `DEC-0001` : fichier « Layout du depot : monorepo uv (`packages/` + `services/`) » / serveur « Layout du dépôt : monorepo uv, packages/ et services/ »
- `DEC-0003` : fichier « Credential machine : token opaque, hash stocke serveur » / serveur « Credential machine : token opaque, hash stocké côté serveur »
- `DEC-0005` : fichier « MCP importe la couche `services/` directement (pas de HTTP interne) » / serveur « Le MCP importe la couche services/ directement (pas de HTTP interne) »
- `DEC-0011` : fichier « Provisioning initial hors-bande via CLI serveur `studio-admin` » / serveur « Provisioning initial hors-bande via la CLI serveur studio-admin »
- `DEC-0014` : fichier « Docker Desktop installe ; deux bugs reels corriges dans `docker/` » / serveur « Docker Desktop installé : deux bugs réels corrigés dans la stack docker compose »
- `DEC-0018` : fichier « Realtime (roadmap etape 4.1) : SSE + curseur `seq`, pas de WebSocket » / serveur « Realtime (étape 4.1) : SSE + curseur seq, pas de WebSocket »
- `DEC-0019` : fichier « Quotas transferts (roadmap etape 4.2) : quota par projet, sans fenetre temporelle » / serveur « Quotas transferts (étape 4.2) : quota par projet, sans fenêtre temporelle »
- `DEC-0020` : fichier « Worker d'expiration des transferts (roadmap etape 4.3) : job CLI explicite, suppression directe » / serveur « Worker d'expiration des transferts (étape 4.3) : job CLI explicite, suppression directe »
- `DEC-0021` : fichier « Sauvegarde Postgres/MinIO et restauration (roadmap etape 4.4) : scripts shell + pg_dump/pg_restore + mc mirror » / serveur « Sauvegarde Postgres/MinIO et restauration (étape 4.4) : scripts shell, pg_dump/pg_restore, mc mirror »
- `DEC-0022` : fichier « Etape 4.5 (validation docker-compose sur base vierge) fermee : chaine complete demontree » / serveur « Étape 4.5 : validation docker-compose sur base vierge fermée »
- `DEC-0023` : fichier « Etape 5 (roadmap) : auth MCP par requete + extension a 25 outils reels » / serveur « Étape 5 : auth MCP par requête et extension à 25 outils réels »
- `DEC-0024` : fichier « Etape 6.1 (roadmap) : socle du Bloc B, `StudioApiClient` » / serveur « Étape 6.1 : socle du Bloc B, StudioApiClient »
- `DEC-0025` : fichier « Integrite reelle d'upload via Content-MD5 natif S3 (correction d'un defaut confirme, pas le SHA256 declaratif) » / serveur « Intégrité réelle d'upload via Content-MD5 natif S3 »
- `DEC-0026` : fichier « Appels boto3 async via `asyncio.to_thread`, factory `StorageProvider` mise en cache » / serveur « Appels boto3 async via asyncio.to_thread, factory StorageProvider en cache »
- `DEC-0030` : fichier « Sous-etape 6.4 (replay ordonne) : fusion chronologique events+mutations, arret sur transitoire, markers hors perimetre » / serveur « Sous-étape 6.4 (replay ordonné) : fusion chronologique events+mutations, arrêt sur transitoire »
- `DEC-0033` : fichier « Sous-etape 6.7 (TransferClient) : multipart local avec URLs mises en cache, reprise download par taille de fichier, etape 6 entierement close » / serveur « Sous-étape 6.7 (TransferClient) : multipart local avec URLs en cache, reprise download par taille de fichier, étape 6 close »
- `DEC-0037` : fichier « Reprise multipart apres expiration des URLs par-part : endpoint additif refresh-parts, ListParts comme verite serveur, nettoyage des uploads orphelins » / serveur « Reprise multipart après expiration des URLs par-part : endpoint additif refresh-parts »
- `DEC-0038` : fichier « Etape 7 (roadmap) : scenario "fichier multipart de 1 Go reel" ferme, test streame sans mock » / serveur « Étape 7 : scénario « fichier multipart de 1 Go réel » fermé, test streamé sans mock »
- `DEC-0039` : fichier « Etape 7 (roadmap) : scenario "replay offline complet" ferme, outbox generique sans ajout client » / serveur « Étape 7 : scénario « replay offline complet » fermé, outbox générique sans ajout client »
- `DEC-0040` : fichier « Etape 7 (roadmap) fermee : scenario "deux machines simulees sur reseaux distincts" ferme » / serveur « Étape 7 fermée : scénario « deux machines simulées sur réseaux distincts » »
- `DEC-0041` : fichier « Etape 8 (roadmap), sous-etape 8.1 : tracabilite AIWorkLog -> Event, revue admin-only » / serveur « Étape 8.1 : traçabilité AIWorkLog → Event, revue admin-only »
- `DEC-0042` : fichier « Etape 8 (roadmap), sous-etape 8.2 : adaptateurs locaux Obsidian/Graphify en lecture seule, portee fermee par defaut » / serveur « Étape 8.2 : adaptateurs locaux Obsidian/Graphify en lecture seule, portée fermée par défaut »
- `DEC-0043` : fichier « Model-Agnostic Agent Identity : separation auth_role / harness / provider / model, agent_profile optionnel » / serveur « Identité d'agent model-agnostic : auth_role / harness / provider / model séparés, agent_profile optionnel »
- `DEC-0044` : fichier « Specialized Agent Profiles : studio-architect, studio-tester, contract-guardian, sync-debugger comme agent_profiles harness-agnostic » / serveur « Profils d'agents spécialisés (SUPERSEDED par DEC-0043) »
- `DEC-0045` : fichier « CC-1 : enregistrement public dAgent (POST /agents) comme identite de provenance, sans autorite » / serveur « CC-1 : enregistrement public d'Agent (POST /agents) comme identité de provenance, sans autorité »
- `DEC-0046` : fichier « HTTP canonical complet, MCP subset additif : surface parity non requise, enforcement parity requise » / serveur « HTTP canonique complet, MCP sous-ensemble additif : parité de surface non requise, parité d'enforcement requise »
- `DEC-0049` : fichier « Sous-etape 8.4 (roadmap) : Review Queue agregee, aucune nouvelle table, revue limitee au travail IA » / serveur « Étape 8.4 : Review Queue agrégée, aucune nouvelle table, revue limitée au travail IA »
- `DEC-0050` : fichier « Question ouverte n°3 (etape 8) : auth dashboard V0 ratifiee, token machine reutilise, aucune nouvelle mecanique » / serveur « Question ouverte n°3 (étape 8) : auth dashboard V0 ratifiée (SUPERSEDED par DEC-0056) »
- `DEC-0054` : fichier « UC-6 : guide dintegration dun consommateur externe, sans connaissance interne » / serveur « UC-6 : guide d'intégration d'un consommateur externe, sans connaissance interne »
- `DEC-0055` : fichier « UC-7 : tests de conformance dun client inconnu (unknown-harness/provider/model, sans profil) » / serveur « UC-7 : tests de conformance d'un client inconnu (unknown-harness/provider/model, sans profil) »
- `DEC-0056` : fichier « Dashboard human authentication with JWT (DASH-4) » / serveur « Authentification humaine du dashboard par JWT (DASH-4) »
- `DEC-0057` : fichier « Etape 8 (roadmap), sous-etape 8.3b : Context Package compose localement par le Bloc B, part partagee lue par HTTP canonique, manifeste versionne ephemere » / serveur « Étape 8.3b : Context Package composé localement par le Bloc B, part partagée lue par HTTP canonique »
- `DEC-0060` : fichier « Etape 9.3 : revue de securite, durcissement headers au edge » / serveur « Étape 9.3 : revue de sécurité, durcissement des headers au edge »
- `DEC-0061` : fichier « Dashboard CSP progressive : tests statiques, e2e Playwright, Report-Only » / serveur « CSP progressive du dashboard : tests statiques, e2e Playwright, Report-Only »
- `DEC-0063` : fichier « AI Library scopes & authorization : Studio/Project/User sans ACL parallele » / serveur « AI Library : scopes et autorisation Studio/Project/User sans ACL parallèle »
- `DEC-0064` : fichier « AI Library versioning : pointeur actif, versions immuables, locks projet » / serveur « AI Library : versioning par pointeur actif, versions immuables, locks projet »
- `DEC-0065` : fichier « AI Library scope resolution : shadowing, version effective, erreurs unifiees » / serveur « AI Library : résolution de scope, shadowing, version effective, erreurs unifiées »
- `DEC-0066` : fichier « AI Library semantic content P3 : schemas par kind, ModelProfile exigences pures, matcher fige » / serveur « AI Library P3 : contenu sémantique par kind, ModelProfile en exigences pures, matcher figé »
- `DEC-0067` : fichier « AI Library bindings P5 : relations typees, matrice kind, fail-closed » / serveur « AI Library P5 : Library Bindings, relations typées, matrice de kinds, fail-closed »
- `DEC-0068` : fichier « AI Library User/Runtime Bindings P4 : choix runtime par utilisateur, precedences » / serveur « AI Library P4 : User/Runtime Bindings, choix runtime par utilisateur, précédences »
- `DEC-0069` : fichier « AI Library Resolution Engine P5 : coeur pur, provenance, erreur stricte » / serveur « AI Library P5 : Resolution Engine, cœur pur, provenance, erreur stricte »
- `DEC-0070` : fichier « AI Library Runtime Registry P6 : runtimes declares, identite stable, neutre provider/harness » / serveur « AI Library P6 : Runtime Registry, runtimes déclarés, identité stable, neutre provider/harness »
- `DEC-0071` : fichier « AI Library HTTP canonique P7 : surface de reference Library/P4/P5/P6 via services communs » / serveur « AI Library P7 : HTTP canonique, surface de référence Library/P4/P5/P6 via services communs »
- `DEC-0072` : fichier « AI Library MCP minimal P8 : 5 outils use-cases sur services communs, output schemas explicites » / serveur « AI Library P8 : MCP minimal, 5 outils use-cases sur services communs, output schemas explicites »
- `DEC-0073` : fichier « P9 Integration Context Package locale : AI Library comme source du composeur DEC-0057 via StudioApiClient » / serveur « P9 : Context Package local, AI Library comme source du composeur DEC-0057 via StudioApiClient »
- `DEC-0076` : fichier « P12 dashboard UI & Resolution Inspector : interface humaine au-dessus du HTTP canonique, aucune resolution frontend » / serveur « P12 : dashboard UI et Resolution Inspector, interface humaine au-dessus du HTTP canonique, aucune résolution frontend »
- `DEC-0077` : fichier « P13 validation E2E finale : sous-système Library/Runtime/Resolution accepté de bout en bout, un défaut P12 corrigé » / serveur « P13 : validation E2E finale, sous-système Library/Runtime/Resolution accepté, un défaut P12 corrigé »
- `DEC-0095` : fichier « Desktop P10 : installateur NSIS par utilisateur, sidecar onedir, Graphify détecté et non redistribué » / serveur « P10 : packaging Windows NSIS per-user ; Graphify non redistribué »
- `DEC-0106` : fichier « DU-0/C — Proxy de confiance et anti-abus par étages » / serveur « DU-0/C — Proxy de confiance et anti-abus par étages (rév. corrigée) »
- `DEC-0107` : fichier « DU-0/D — Versions séparées et compatibilité N/N-1 » / serveur « DU-0/D — Versions séparées et compatibilité N/N-1 (rév. corrigée) »
- `DEC-0108` : fichier « DU-0/E — Distribution Windows à double signature » / serveur « DU-0/E — Distribution Windows à double signature (rév. corrigée) »
- `DEC-0109` : fichier « DU-0/A — Inscription publique fermée par défaut » / serveur « DU-0/A — Inscription publique fermée par défaut (rév. alignée ADR) »
- `DEC-0110` : fichier « DU-0/B — JWT court et version de révocation » / serveur « DU-0/B — JWT court et version de révocation (rév. alignée ADR) »
- `DEC-0123` : fichier « Isolation projet minimale : membership User→Project, rôle = quoi, membership = où » / serveur « DU-0/Isolation — membership User→Project : rôle = quoi, membership = où (fichier renuméroté DEC-0103) »
- `DEC-0124` : fichier « Oracle slug projet accepté : slugs non secrets, 409 conflict structuré » / serveur « Oracle slug projet accepté (slugs non secrets, 409 conflict) »
- `DEC-0126` : fichier « Licence du dépôt : Apache-2.0 et inventaire tiers embarqué » / serveur « Licence du dépôt : Apache-2.0 + inventaire tiers embarqué »
- `DEC-0129` : fichier « Distribution Windows non signée : pas de certificat Authenticode » / serveur « Distribution Windows non signee : pas de certificat Authenticode (cout) »
- `DEC-0130` : fichier « Enrôlement du poste Desktop : une seule entrée secrète sur le pont local » / serveur « Enrôlement du poste Desktop : une seule entrée secrète sur le pont local (amende DEC-0093) »
- `DEC-0134` : fichier « B6 — Auto-update réel sur les canaux : version de build, feed par canal, preuve après publication » / serveur « B6 — Auto-update réel sur les canaux : version de build, feed par canal, preuve après publication (proposed) »
- `DEC-0137` : fichier « C3 — Canaux beta/stable : promotion du même artefact par manifeste, sans rebuild » / serveur « C3 — Promotion beta→stable par manifeste, sans rebuild (canaux + inscriptions) »
- `DEC-0143` : fichier « AIB-A : bootstrap = composition + manifest minimal studio.bootstrap/v1 » / serveur « AIB-A — Bootstrap = composition + manifest studio.bootstrap/v1 »
- `DEC-0162` : fichier « Desktop : deux builds Prod/Dev distincts et serveur local Dev » / serveur « Desktop Prod et Dev deviennent deux builds distincts, sans promotion croisée d’artefact »
- `DEC-0163` : fichier « L3 : handoff composite en un appel + repli end_session (claims, ai_work, session) » / serveur « L3 handoff composite + repli end_session »
- `DEC-0167` : fichier « AIB P3 : générateur local du bundle, offline d'abord » / serveur « AIB P3 : générateur local du bundle, offline d'abord (DEC-0165) »
- `DEC-0179` : fichier « AIB R3 : reglages de lancement locaux persistes dans launch_settings.json » / serveur « AIB R3 : réglages de lancement locaux persistés dans launch_settings.json (précédence sur config.toml, échec fermé) »
- `DEC-0182` : fichier « AIB P9 — Credential éphémère de lancement » / serveur « AIB P9 — Credential éphémère de lancement (projet+tâche+session) à la place du token machine durable »
- `DEC-0186` : fichier « MCP : déprécier les outils redondants de session et de claim, retrait après la fenêtre de transition » / serveur « MCP : déprécier les outils redondants de session et de claim (DEC-0186) »

## Statuts divergents (11)

- `DEC-0095` : fichier proposed / serveur validated
- `DEC-0127` : fichier proposed / serveur validated
- `DEC-0137` : fichier validated / serveur superseded
- `DEC-0159` : fichier proposed / serveur validated
- `DEC-0160` : fichier proposed / serveur validated
- `DEC-0161` : fichier proposed / serveur validated
- `DEC-0172` : fichier proposed / serveur validated
- `DEC-0181` : fichier proposed / serveur validated
- `DEC-0182` : fichier proposed / serveur validated
- `DEC-0185` : fichier proposed / serveur validated
- `DEC-0186` : fichier proposed / serveur validated

## Statuts fichier absents ou inconnus (2)

- `DEC-0014` : statut fichier « None » → validated (serveur)
- `DEC-0015` : statut fichier « None » → validated (serveur)

## Contenu masqué à l'import (1)

- `DEC-0010` : mot de passe d'URL retiré (user@host)

## Notes non importées (0)

Aucune.

## Présentes en fichier seulement (1)

- `DEC-0092` : Desktop P0 : CodeGraphProvider neutre, Graphify optionnel installé séparément

## Présentes au serveur seulement (34)

- `DEC-0083` : Priorité : roadmap Roadmaps & Project Initialization avant la roadmap Desktop
- `DEC-0103` : DU-0/Isolation — membership User→Project : rôle = quoi, membership = où (rév. corrigée)
- `DEC-0105` : DU-0/B — JWT court et version de révocation (rév. corrigée)
- `DEC-0111` : Workflow W2 : le hook SessionStart assure l'Agent du harnais (ensure, sans autorité)
- `DEC-0112` : Workflow W2b : setup-hooks distribue les hooks ensure sur fresh machine
- `DEC-0113` : enregistrement Agent exposé via MCP
- `DEC-0114` : Tasks : emission serveur des evenements task.* a chaque ecriture
- `DEC-0115` : Git partagé : stable → dev → task, roadmaps et phases hors de Git
- `DEC-0116` : DEC-0104 Desktop P9 : fourniture du jeton machine aux harnais par credential helper, état token_missing
- `DEC-0117` : Desktop P9 : un identifiant Studi'OS dédié par couple poste + outil d'IA (DEC-0104 §2, remplace DEC-0116)
- `DEC-0118` : Oracle slug projet accepté (slugs non secrets, 409 conflict)
- `DEC-0119` : [proposed] Roadmaps : état « approved » distinct de « active » ?
- `DEC-0120` : Roadmaps : pas d'état « approved », approve reste proposed → active
- `DEC-0121` : Amendement A2 de DEC-0110 : GET /auth/me, expires_in, états de compte dès A2
- `DEC-0122` : Amendement A3 de DU0-A : administration HTTP des comptes, anti-auto-modification, e-mails normalisés
- `DEC-0125` : Promotion dev → master uniquement à la fin d'une roadmap terminée et fonctionnelle
- `DEC-0128` : A4 — Amendement DEC-0109 : mot de passe choisi à la vérification, récupération indépendante du flag
- `DEC-0131` : B4 clôturée sans Authenticode ni test Smart App Control
- `DEC-0136` : Git watching actif par défaut pour les espaces locaux (proposed)
- `DEC-0138` : P04 : bge-m3 (fenêtre 2048) + hybride α 0,1 sur requête nettoyée, repli search_text
- `DEC-0139` : P05 : bge-m3 limité à 256 tokens (variante bge-m3-256) et recette agents top 4
- `DEC-0140` : P07 : curateur unique Brainstormer, exception CURRENT.md bornée, journal dans le vault
- `DEC-0153` : AIB-C — Blocs délimités + anti-drift par adapters check
- `DEC-0158` : AIB-I : ensure agent serveur par stable_key, distinct d'AgentDefinition
- `DEC-0165` : AIB C5 — remèdes préalables : budget sync de start_work et bruit ai_work
- `DEC-0169` : v0.2.0 livrée en HTTP direct seul ; magnet/torrent différé
- `DEC-0170` : Convention « jamais de téléchargement de ROMs » remplacée par « RomVault n'agrège/ne scrape aucune source »
- `DEC-0178` : v0.2.0 publiée — roadmap « Sources de téléchargement » terminée
- `DEC-0183` : Profils d'outils MCP : session par defaut, admin par connexion
- `DEC-0184` : Correctif DEC-0183 : les profils MCP scopent la decouverte (tools/list), pas les appels
- `DEC-0188` : Surcouche utilisateur : title = identité, shownTitle = affichage
- `DEC-0189` : Entrées non-ROM : console « pc », kind, fichiers jamais supprimés
- `DEC-0190` : Reprise d'une machine existante à l'enrôlement (adopt) par rotation de credential
- `DEC-0191` : Vault serveur à deux portées (studio / projet) et DEC unifiées — source canonique côté serveur
