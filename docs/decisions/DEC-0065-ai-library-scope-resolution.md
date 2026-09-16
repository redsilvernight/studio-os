---
id: DEC-0065
title: 'AI Library scope resolution : shadowing, version effective, erreurs unifiees'
status: active
date: '2026-09-16'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0065 — AI Library scope resolution : shadowing, version effective, erreurs unifiees

Fige la couche scopes/heritage P2 au-dessus du domaine P1 (gate P2).
Service pur et deterministe, sans endpoint/MCP/UI/registry en P2.
Ne prejuge ni des workflows ni des runtime bindings futurs.

## 1. Resolution logique

Entree : `(principal, kind, stable_key, project_id?)`, apres application
prealable des regles de visibilite DEC-0063. Ordre total de shadowing :

`User > Project(project_id) > Studio`

Le premier candidat visible est la definition effective. Sans `project_id`,
la couche Project est absente (candidats User + Studio uniquement) : la
couche Project est parametree par le projet demande, jamais globale.
Le rang de scope est explicite (constante applicative) : le resultat ne
depend ni de l'ordre SQL, ni de l'ordre d'insertion, ni d'un dictionnaire,
ni d'un comportement implicite du moteur. Une ligne hors nomenclature
(scope inconnu, atteignable uniquement hors API) est exclue des candidats :
fail-closed, indistinguable d'une absente.

## 2. Filter-first et contrat d'erreur unifie

Securite : `filter visible candidates -> resolve`, jamais l'inverse.
Contrat externe unique `definition_not_found` (meme statut, meme code, meme
message public) pour : absente, invisible, sans version utilisable,
dependance absente, dependance invisible. Des raisons diagnostiques internes
(`missing_definition`, `invisible_definition`, `no_active_version`,
`missing_dependency`, `invisible_dependency`) peuvent exister cote serveur
mais ne sont jamais exposees a un principal qui pourrait en deduire
l'existence d'une ressource inaccessible.

## 3. Resolution logique vs reference structurelle

Deux mecanismes distincts : la demande `kind + stable_key` utilise le
shadowing (§1) et produit une definition effective (heritage) ; une
dependance enregistree par UUID est une identite structurelle exacte qui ne
relance aucun shadowing, ne cherche aucun equivalent dans un autre scope,
ne flotte jamais, mais dont la visibilite est verifiee — cible exacte
inutilisable = non resoluble (contrat §2).

## 4. Version effective

Apres selection : lock applicable `(project, resource UUID)` = `locked_version`
(origine `lock`), sinon `active_version` (origine `active`), sinon echec
public §2 (jamais de devinette silencieuse, jamais de substitution vers une
autre version). Une version `deprecated` se resout avec `deprecated = true`,
sans devenir une incompatibilite.

## 5. Pins

Semantique P1 conservee : pin = UUID exact, aucun re-shadowing, aucune
resolution flottante cachee.

## 6. Locks

Advisory, ni autorisation ni claim. `User shadows Project locked` est autorise
si la visibilite le permet : le lock concerne son UUID canonique et ne capture
aucune autre definition partageant le `stable_key`. Teste explicitement.

## 7. Provenance minimale

`LibraryResolution` : scope effectif, UUID effectif, version effective,
origine (`lock`/`active`), flag deprecated. Aucune mention des candidats
ecartes invisibles, aucune trace multi-candidats en P2.

## 8. Compatibilite separee

La resolution repond "quelle definition/version effective", `check_compatibility`
repond "compatible avec quelles contraintes" — separement. `unknown !=
compatible` est preserve : une resolution reussie n'implique jamais la
compatibilite.
