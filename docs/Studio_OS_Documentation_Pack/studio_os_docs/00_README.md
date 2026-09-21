# Studio OS - Documentation Pack

Version de reference pour la construction de Studio OS.

## Objectif
Studio OS est la couche de coordination commune d'un studio de jeu video de deux developpeurs travaillant a distance. Il relie humains, agents IA (quel que soit leur harness, provider ou modele), Git/GitHub, Godot, graphe de connaissance, notes, enregistrements de sessions, builds, marketing et transferts de fichiers.

## Architecture generale
- Deux postes autonomes, chacun sur son propre reseau.
- Aucun acces direct obligatoire entre les deux PC.
- Un serveur central sur VPS OVH, expose uniquement en HTTPS.
- Les traitements lourds restent en local; le VPS coordonne, stocke l'etat commun et heberge Studio Storage.
- Les donnees privees restent locales par defaut.

## Ordre de lecture recommande
### Pour un humain
1. HUMAN/01_VISION_PRODUIT.md
2. HUMAN/02_FONCTIONNALITES_FINALES.md
3. HUMAN/03_WORKFLOWS_QUOTIDIENS.md
4. HUMAN/04_DEPLOIEMENT_OVH.md
5. HUMAN/05_SECURITE_EXPLOITATION.md

### Pour une IA
1. AI/01_AI_OPERATING_REFERENCE.md
2. AI/02_AGENT_RULES.md
3. AI/03_CONTEXT_BOOTSTRAP.md
4. TECH/01_ARCHITECTURE.md
5. TECH/02_API_CONTRACT.md
6. TECH/03_EVENT_CONTRACT.md
7. TECH/04_AUTH_SYNC_CONTRACT.md
8. TECH/05_DATA_MODEL.md
9. TECH/06_STORAGE_TRANSFER_SPEC.md
10. TECH/07_MCP_CONTRACT.md
11. TECH/08_OFFLINE_SYNC.md
12. TECH/09_OBSIDIAN_GRAPHIFY.md
13. TECH/10_TEST_ACCEPTANCE.md

### Pour construire le produit
- IMPLEMENTATION/01_ROADMAP.md
- IMPLEMENTATION/02_BLOCK_A_PROMPT.md
- IMPLEMENTATION/03_BLOCK_B_PROMPT.md
- IMPLEMENTATION/04_INTEGRATION_CHECKLIST.md
- Chantier Project AI Bootstrap : [../../AI_BOOTSTRAP_ROADMAP.md](../../AI_BOOTSTRAP_ROADMAP.md)
  (audit : [../../AI_BOOTSTRAP_P0_AUDIT.md](../../AI_BOOTSTRAP_P0_AUDIT.md))

### Pour un consommateur externe (developpeur tiers)
1. INTEGRATION/00_EXTERNAL_CONSUMER_GUIDE.md — parcours complet, de zero au
   premier transfert, sans connaissance interne du studio.
2. TECH/02_API_CONTRACT.md
3. TECH/04_AUTH_SYNC_CONTRACT.md
4. TECH/07_MCP_CONTRACT.md

## Principes non negociables
- Le serveur central est la source d'etat partagee, pas une machine de developpeur.
- Pas de dependance LAN, SMB ou IP directe entre les domiciles.
- Les gros fichiers transitent par un stockage objet S3/MinIO, pas par FastAPI.
- Les Resource Claims sont des soft locks, jamais des verrous bloquants.
- La memoire partagee est en lecture seule par defaut pour les agents.
- Toute action IA significative doit etre tracable.
- Les contrats API, evenements, auth et sync sont versionnes.
- Les clients doivent tolerer une coupure Internet temporaire.
