---
id: DEC-0181
title: 'Compatibilité du manifest bootstrap : lecture v1 uniquement et refus explicite'
status: accepted
date: '2026-10-03'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0181 — Compatibilité du manifest bootstrap : lecture v1 uniquement et refus explicite

## Décision proposée

Le lecteur accepte `studio.bootstrap/v1`. Pour préserver le contrat v1 existant,
l'absence du champ `format` reste acceptée et équivaut à v1 : le modèle public lui
attribue déjà cette valeur par défaut. Aucune version v0 n'a été publiée : il
n'existe donc ni format N-1 à maintenir, ni migration à exécuter.

Quand il est présent, le champ `format` est contrôlé avant la validation Pydantic.
Un document dont la racine n'est pas un objet, un format non textuel, une version
ancienne, inconnue ou future produit le code stable
`unsupported_bootstrap_manifest_version`. Le diagnostic indique la version
attendue et propose de régénérer le manifest avec
`studio-client bootstrap init --overwrite` après revue des changements locaux.

La gate ne transforme pas le document. Le modèle `BootstrapManifest` conserve
`extra="forbid"` : les champs inconnus restent refusés, sans troncature ni perte de
données. `bootstrap check`, `diff` et `sync` utilisent tous le même chargeur et
échouent avant toute écriture.

## Ownership

Le contrat et la gate vivent dans `studio_contracts.bootstrap`. Le client local
possède la lecture du fichier `.agents/bootstrap.json` et la traduction du
diagnostic pour la CLI. Une future version du format devra définir explicitement
sa matrice de lecture et sa migration dans une nouvelle Decision avant de modifier
`BOOTSTRAP_FORMAT`.
