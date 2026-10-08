---
id: DEC-0142
title: Refresh token rotatif et session desktop persistante (complète DEC-0110)
status: accepted
date: '2026-09-27'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0142 — Refresh token rotatif et session desktop persistante (complète DEC-0110)

Serveur : `2f654121-eb10-40c5-b834-cefa8ec1b5c2` (accepted).
Tâche : `76ba7e87-b807-46d7-9cb1-b11c19564541`.
Complète [DU0-B](DU0-B-session-revocation.md) (DEC-0110), sans la remplacer.

## Contexte

DEC-0110 impose un JWT d'accès de 15 minutes maximum, gardé en mémoire et sans
refresh token (l'option 2, « refresh rotatif », avait été différée). Résultat
pour l'application desktop : l'utilisateur est déconnecté au bout de
15 minutes et à chaque redémarrage.

## Décision

Le report de l'option 2 de DEC-0110 est levé. Tout le reste de DEC-0110 reste
en vigueur : JWT d'accès ≤ 15 min, en mémoire, claims minimaux, `auth_version`,
revalidation SSE, fail-closed.

- **Refresh token** : secret opaque aléatoire, stocké uniquement sous forme
  de hash côté serveur, rattaché à `user`, `machine`, `session_id` et à une
  `family_id`.
- **Rotation** : chaque `POST /auth/refresh` consomme le jeton et renvoie un
  nouveau couple (JWT d'accès et refresh token). Un jeton déjà consommé qui
  revient révoque toute la famille, car c'est un signe de vol.
- **Durée** : 30 jours d'expiration glissante et 90 jours d'expiration
  absolue ; au-delà, le mot de passe est redemandé.
- **Révocation** : logout, « révoquer toutes les sessions », disable, reset
  et changement de rôle (toute incrémentation d'`auth_version`) révoquent les
  refresh tokens concernés. Un refresh vérifie `auth_version` et l'état du
  compte comme un accès normal.
- **Desktop (Bloc B)** : le refresh token est stocké dans le coffre de l'OS
  (Windows Credential Manager/DPAPI) via le shell Tauri, jamais dans
  `localStorage` ni en clair. Renouvellement silencieux avant `exp` ou après
  un 401 (un seul retry, refresh concurrents mutualisés). Restauration de la
  session au démarrage. En cas d'échec, retour à l'écran de login actuel.
- **Navigateur hors desktop** : pas de persistance, comportement de DEC-0110
  inchangé.
- **Contrat** : changement du contrat Auth/Sync et de l'OpenAPI, via le skill
  `contract-change`, avec régénération des clients.

## Conséquences

- Nouvelle famille de secrets persistés : une table, une migration et le
  nettoyage des jetons expirés.
- Une personne qui accède à la session Windows de l'utilisateur accède aussi
  à Studio OS pendant 90 jours au plus. C'est un risque accepté, comparable
  aux autres clients desktop.
- Tests requis : rotation, réutilisation, expirations glissante et absolue,
  révocation par `auth_version`, refresh concurrents, e2e du redémarrage
  desktop.
