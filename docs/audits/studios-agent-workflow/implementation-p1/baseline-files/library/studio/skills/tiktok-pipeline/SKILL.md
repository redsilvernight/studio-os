---
kind: skill
stable_key: tiktok-pipeline
scope: studio
description: "Rushes de gameplay ou produit → vidéo TikTok + Reel Instagram : plan de campagne, tendance, ingestion, sélection, storyboard, marque, couverture, musique, montage HyperFrames, rendu, publication validée par plateforme."
---

# Pipeline TikTok + Instagram

Prend un ou plusieurs dossiers de rushes, en tire une vidéo montée (découpe, sous-titres, habillage, musique), génère une couverture de marque unique et la publie — après validation explicite, plateforme par plateforme — sur TikTok et en Reel Instagram. Utilisable depuis n'importe quel projet.

## Prérequis

- ffmpeg et ffprobe.
- HyperFrames (CLI `npx hyperframes`, Node.js) et sa documentation (composition, keyframes, transitions).
- Fiches de référence du pipeline : kit de marque et gabarit de couverture, règles de montage, plan de contenu, fit-check de tendance, bibliothèque musicale, publication TikTok, publication Instagram, capture automatique (optionnelle).
- Publication : navigateur piloté dans la session de l'utilisateur, déjà connecté à ses comptes.
- Absent : le signaler, proposer l'installation, ne jamais improviser un substitut.

## Usage

```
<pipeline> <dossier(s) de rushes>          # pipeline complet
<pipeline> <dossier(s)> --duration 30       # durée cible
<pipeline> <dossier(s)> --music "<ambiance>"
<pipeline> --draft-only                     # reprend le dernier rendu et va à la publication
<pipeline> --plan                           # plan de campagne seul, aucun rush traité
```

Sans dossier : si le répertoire courant est un projet Godot (`project.godot`), déterminer l'intention :
- mise en avant d'une mise à jour récente (défaut, notamment après un push) → source = `<rushes>/<projet>/Current/` (dossier de rushes configuré pour le projet, alimenté par la capture automatique) ; passer par l'étape 1bis ;
- promotion générale → source = `<rushes>/<projet>/Old/` (archive), étape 1bis sautée.
Intention floue : demander. Hors projet Godot : utiliser `pipeline-out/rushes/` s'il existe, sinon demander où sont les rushes.

## Fait, et ne fait jamais

Fait : plan de campagne (optionnel), fit-check de tendance, ingestion, sélection, storyboard, kit de marque, couverture unique, musique libre de droits, montage, rendu, publication après validation.

Jamais sans confirmation explicite, à chaque fois et par plateforme : télécharger un fichier (musique, asset), publier sur TikTok ou Instagram, saisir des identifiants. L'accord pour TikTok ne vaut pas pour Instagram, et inversement.

## Étape 0 — État existant

- `pipeline-out/` existe : lire `brand-kit.json` (ne pas redemander), `draft-log.json` (historique des publications), `content-plan.json` s'il existe, et `rushes/`. Après le nettoyage (étape 11), seuls `brand-kit.json`, `draft-log.json` et `exports/` restent : c'est normal.
- Création dans un projet Godot : poser aussitôt un `pipeline-out/.gdignore` vide pour que l'éditeur n'importe pas ce contenu.
- `--draft-only` : aller à l'étape 7bis (couverture si absente) puis 9-10 avec le dernier rendu de `exports/`.

## Étape 0bis — Plan de campagne (optionnel)

Selon la fiche plan de contenu. `--plan` construit ou rafraîchit `content-plan.md` (+ `.json`) puis s'arrête. En passage normal, si le plan manque ou a plus de 2 semaines, le proposer sans l'imposer. Un plan couvrant le créneau du jour alimente l'étape 3 (pilier, angle, objectif).

## Étape 1 — Ingestion

Scanner `*.mp4`, `*.mov`, `*.mkv`, `*.avi`.
- Source `<rushes>/<projet>/Current|Old/` : **ne pas copier**, référencer sur place (ce sont les masters ; les copier double l'espace disque).
- Autre source : copier dans `pipeline-out/rushes/` si absent ; ce dossier devient alors la seule copie, à conserver.

Inventaire par fichier :
```
ffprobe -v error -show_entries format=duration:stream=width,height,r_frame_rate -of json <fichier>
```
Résumer nombre, durée totale, résolutions — agrégation déterministe par script, sans modèle.

## Étape 1bis — Rushes ↔ commits (source `Current/`)

`Current/` cumule les rushes de plusieurs sessions, parfois plusieurs fonctionnalités.
1. Les fichiers sont nommés `<tag>-<yyyyMMdd-HHmmss>.<ext>` : en tirer l'horodatage.
2. Dans le dépôt du projet : `git log --since="<plus ancien rush, élargi>" --pretty=format:"%H %ad %s" --date=iso-strict` (élargir la borne basse : le test précède parfois le commit).
3. Associer chaque rush aux commits voisins, lire message et `git show --stat` pour comprendre la fonctionnalité.
4. Plusieurs fonctionnalités et aucune précision : lister les groupes (fonctionnalité, rushes, commits) et demander. Un seul groupe cohérent : l'utiliser.
5. Ce contexte nourrit le storyboard et la légende.

Plus de ~200 lignes de commits et diffs : extraction mécanique via un sous-agent `reader` si le harnais en dispose, sinon lecture ciblée (skill `delegate`). Le choix du groupe reste éditorial, jamais délégué.

## Étape 2 — Sélection

1. Coupures naturelles : `ffmpeg -i <f> -vf "select='gt(scene,0.35)',showinfo" -f null -` ; pics de volume en heuristique secondaire.
2. Vignettes de revue : `ffmpeg -i <f> -vf fps=1/2 thumb-%03d.jpg`.
3. Choisir 3 à 8 segments à moment clair (réussite, nouveauté visuelle, effet « wow ») ; éviter temps morts et échecs non voulus, sauf ton comique.
4. Découper vers `pipeline-out/selects/` avec `-ss <début> -to <fin>`.

**Toujours forcer un frame rate constant** : `-r 30 -fps_mode cfr -c:v libx264 -pix_fmt yuv420p`, même si une copie sans réencodage semblait possible. Les captures de gameplay sont presque toujours en VFR, ce qui peut bloquer l'aperçu HyperFrames sur ce fichier. ffmpeg récent : `-fps_mode cfr`, pas `-vsync`.

**Vérifier le cadrage réel** : un `object-fit: cover` 16:9 → 9:16 ne garde qu'une tranche étroite (~32 % de la largeur) centrée sur `object-position` ; un panneau d'UI large ou un sujet décentré peut sortir du cadre. Extraire une frame de contrôle plein cadre (`ffmpeg -vf "select=eq(n\,N)" -frames:v 1 out.jpg`) et vérifier. UI large : pré-recadrer la source en 9:16 (pas de `contain`, bandes noires rejetées) ; sujet décentré : calculer `object-position` depuis les coordonnées pixel de la frame.

Log `showinfo` ou transcription au-delà de ~200 lignes : extraction des timestamps candidats via `reader` ou recherche ciblée. Le choix du hook n'est jamais délégué.

## Étape 3 — Storyboard

Pilier « Trend » ou tendance citée : fit-check d'abord (niche, phase du cycle, structure native, twist) et verdict reprendre/adapter/passer ; en cas d'échec, proposer un autre pilier plutôt que forcer.

Selon les règles de montage :
- Hook (0-3 s) : le moment le plus fort, sans intro.
- Corps : segments ordonnés en progression, pas en ordre de capture.
- Relance si la vidéo dépasse ~20 s.
- CTA de fin : par défaut l'invitation communautaire du kit de marque, plus tout CTA pertinent (nom du jeu, wishlist…) ; demander la première fois, réutiliser ensuite. Toujours présent sauf demande contraire pour cette vidéo.

Présenter le storyboard (segments, durée visée) **avant tout montage**.

## Étape 4 — Kit de marque

Selon sa fiche : construit une fois par projet, réutilisé ensuite.

## Étape 5 — Musique

Selon la fiche bibliothèque musicale : OST du projet d'abord, puis bibliothèque partagée du studio (manifeste), sinon proposer 2 à 4 pistes (source, licence, taille) et attendre l'accord avant tout téléchargement. Beaucoup de résultats bruts : filtrage mécanique par critère explicite (ambiance, durée, licence) via `reader` ou soi-même.

## Étape 6 — Montage (HyperFrames)

Lire la documentation HyperFrames (CLI, composition, keyframes, transitions) avant de monter. Étape non déléguée : elle repose sur l'exécution directe de la CLI.

1. `npx hyperframes init` dans `pipeline-out/hf-project/` s'il n'existe pas, sinon réutiliser.
2. Segments sur la timeline, dans l'ordre du storyboard.
3. Cartons de marque (ouverture, CTA de fin).
4. Sous-titres karaoké mot à mot (transcription si voix), placés selon les règles de montage.
5. Transitions (zoom punch, jump cut), cadrage, zones de sécurité ; vérifier la collision HUD du jeu / UI TikTok.
6. Piste musicale, coupes calées sur le beat si pertinent.
7. `npx hyperframes lint` puis `npx hyperframes check`.
8. `npx hyperframes preview --background`, présenter le lien à l'utilisateur, **attendre son accord avant le rendu**.

Aperçu bloqué (canvas noir, processus qui meurt, boucle d'erreurs) après une tentative honnête, alors que `check` passe : repli légitime vers le rendu, puis validation du fichier réel par frames de contrôle à chaque plan (`ffmpeg -ss <t> -frames:v 1 out.jpg`) avant de le montrer. Rendu figé sans log : chercher des processus navigateur headless ou `node` orphelins d'une tentative précédente et les arrêter.

## Étape 7 — Rendu

`npx hyperframes render --quality high --output pipeline-out/exports/<nom>.mp4` ; vérifier existence, taille non nulle, durée plausible (`ffprobe`).

## Étape 7bis — Couverture

**Un seul fichier `pipeline-out/exports/<nom>-cover.png`** selon le gabarit du kit de marque (frame choisie, vignette de marque, titre, accroche propre à la vidéo, filigrane du compte), uploadé tel quel sur TikTok et Instagram. Jamais une couverture différente par plateforme.

## Étape 8 — Validation utilisateur

Présenter la vidéo et la couverture à l'utilisateur ; ne pas continuer sans retour positif explicite sur les deux.

## Étape 8bis — Archivage (source `Current/`)

Seulement si la source était `Current/`. Vidéo validée : déplacer le contenu de `Current/` vers `Old/` (le créer si besoin). En cas de collision de nom, garder les deux fichiers. Rangement interne non destructif, sans confirmation supplémentaire.

## Étape 9 — Publication TikTok

Selon la fiche publication TikTok. Jamais sans confirmation explicite à chaque fois, quel que soit le niveau d'automatisation en amont.

## Étape 10 — Publication croisée Instagram

Selon la fiche publication Instagram. Par défaut même vidéo, même couverture, même légende, sauf adaptation demandée. Confirmation propre à Instagram, indépendante de TikTok. Demander publication immédiate ou programmée (programmation native d'Instagram) sans présumer.

## Étape 11 — Nettoyage

Une fois le sort des deux publications réglé (publiée ou refusée), ne garder que l'indispensable :
- **Garder** : `brand-kit.json`, `draft-log.json`, `content-plan.*` ; `exports/<nom>.mp4` et `<nom>-cover.png` de chaque entrée de `draft-log.json` ; `rushes/` s'il est la seule copie des rushes d'entrée.
- **Supprimer** : `hf-project/`, `selects/`, les dossiers de logs et frames de contrôle, `rushes/` seulement si la source était `<rushes>/<projet>/`, les résidus de transaction HyperFrames et tout fichier de `exports/` non référencé par `draft-log.json`.

Rangement du cache local de travail, fait par défaut, mais **toujours en comparant à `draft-log.json`** avant de supprimer dans `exports/`, jamais à l'aveugle.

## Capture automatique (optionnelle)

Le pipeline ne déclenche jamais de capture ni de montage de lui-même. À activer volontairement selon la fiche capture : addon d'éditeur Godot qui enregistre chaque Play dans `<rushes>/<projet>/Current/`, ou consigne de projet déclenchant la capture lors des tests.

## Honnêteté

- Ne jamais prétendre avoir regardé une vidéo non regardée.
- Ne jamais publier sans confirmation propre à chaque plateforme.
- Ne jamais télécharger sans lister source, licence, taille et obtenir l'accord.
- Ne jamais improviser une couverture autre que `<nom>-cover.png` à l'upload ; si elle manque, la régénérer (7bis).
- Étape en échec (rendu, ffprobe) : le dire clairement plutôt que livrer un résultat dégradé en silence.
