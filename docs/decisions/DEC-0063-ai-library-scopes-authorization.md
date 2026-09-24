---
id: DEC-0063
title: 'AI Library scopes & authorization : Studio/Project/User sans ACL parallele'
status: active
date: '2026-09-16'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0063 — AI Library scopes & authorization : Studio/Project/User sans ACL parallele

Tranche la semantique des scopes du gate P0 (roadmap AI Library V2.1).
Aucun RBAC ni aucune ACL projet parallele n'est cree : seules les primitives
existantes sont utilisees (`Principal`, `ensure_can_write`,
`ensure_can_provision`, `ensure_machine_owned`, filtre silencieux facon
`transfer_visibility_clause`, `TECH/04_AUTH_SYNC_CONTRACT.md`, DEC-0036).

## Lecture

- Studio et Project : toute machine authentifiee peut lire (comme les `GET`
  existants — il n'existe pas d'ACL projet, et P1 n'en invente pas ; c'est
  assume explicitement, coherent avec tasks/decisions).
- User : owner (`owner_user_id == principal.user.id`) ou `admin` uniquement.
  Toute autre lecture recoit `404`, jamais `403`, afin qu'aucune surface
  (get direct, liste, recherche, resolution, erreur, compteur, metadonnee)
  ne permette d'inferer l'existence d'une ressource User d'autrui
  (precision 1 du gate). Les collections filtrent avant exposition et ne
  comptent jamais les ressources invisibles.

## Ecriture

- `ensure_can_write` d'abord, partout (`readonly` jamais).
- Creation Studio : `ensure_can_provision` (`admin`/`developer`, comme
  `POST /projects`) ; creation Project/User : tout writer (le scope User
  fixe l'owner au `principal.user.id` appelant, jamais fourni par le client).
- Mutation d'une ressource (nouvelle version, activation, deprecation) :
  machine owner (`owner_user_id`, renseigne a la creation depuis le
  `principal` appelant) ou `admin`, sur le modele de `ensure_machine_owned`.
- Locks projet : tout writer pose un lock ; mainlevee par l'utilisateur
  createur ou `admin`.

## Precedence de resolution (pas d'autorisation)

Session transitoire > lock projet (une resolution contrevenant a un lock est
une erreur structuree, jamais un bypass silencieux) > binding User > defaut
Project > defaut Studio. La resolution elle-meme est P5 ; cette precedence
est figee ici pour que scopes, bindings et locks restent coherents.

## Amendement propose — DEC-0100 (2026-09-24, statut `proposed`)

Scope Project : lecture composee avec l'acces projet (membership ou `admin`).
Scope Studio : lecture reservee a `admin` ou a un User ayant au moins une
membership. Scope User, precedence de resolution et `404` non-oracle
inchanges (evalues apres le controle projet). « Sans ACL parallele » est
remplace pour le scope Project. Effectif a l'acceptation de DEC-0100.
