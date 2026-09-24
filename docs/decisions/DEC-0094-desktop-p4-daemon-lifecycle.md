---
id: DEC-0094
title: 'Desktop P4 : daemon unique supervisé, outbox liée à l’identité et health négocié'
status: active
date: '2026-09-21'
superseded_by: null
source: docs/decisions/DEC-0094-desktop-p4-daemon-lifecycle.md
---

# DEC-0094 — Desktop P4: daemon lifecycle

Status: **accepted** (human validation 2026-09-21)
Date: 2026-09-21
Task: `[Desktop P4] Daemon lifecycle & services locaux (lane B)`
Server decision UUID: `5019e74a-7770-49ca-90e9-0d40c2a7155c` (accepted server-side with the existing UUID, no renumbering)

## Context

P2 prouve seulement qu’un shell Tauri peut lancer un sidecar fixe et échanger
des messages `studio.local/v1`. P4 doit rendre le daemon existant exploitable
par Desktop sans dupliquer `HeartbeatDaemon`, `GitWatcher`, l’outbox ni le
protocole P1.

## Decision

- Le runtime Python commun possède heartbeat, watchers, rejeu, SQLite et
  credential machine. Tauri possède le processus, sa surveillance et la
  politique de reprise bornée.
- Le verrou P1 reste dérivé de `(server_origin, profile)` ; un second lancement
  s’attache ou retourne `already_running`. L’outbox est physiquement et
  logiquement liée à `(server_origin, profile, machine)` et tout mismatch est
  refusé avant réseau avec `IDENTITY_MISMATCH`.
- `daemon.health` est une commande additive de `studio.local/v1`, protégée par
  la capability `daemon.health`. Elle n’ajoute aucun champ aux réponses P1
  existantes et n’est émise qu’après négociation.
- Le transport local reste privé, borné et typé. Il n’expose ni shell, ni spawn,
  ni filesystem arbitraire, ni proxy HTTP.
- Le démarrage automatique passe par `STUDIO_DAEMON_AUTOSTART=1`. Desktop le
  pose au lancement du sidecar dès qu’une origine serveur est configurée (voir
  Amendement 2026-09-24) ; sans origine, le runtime reste arrêté.
  Par défaut, fermer Desktop demande l’arrêt gracieux ;
  `STUDIO_DESKTOP_KEEP_DAEMON=1` conserve le processus, qui reste joignable par
  l’endpoint privé lors de la réouverture de Desktop.
- Les logs et diagnostics sont bornés, rotatifs et redactés ; ils n’exportent ni
  secret, ni payload d’outbox, ni code/vault, ni URL signée.
- P4 ne définit aucune UX P3, configuration workspace P5, signature, updater ou
  installer final P10.

## Consequences

Les anciens pairs continuent d’utiliser `daemon.status`; seuls les pairs qui
négocient `daemon.health` voient heartbeat, Git watchers, replay et providers.
La CLI et Desktop doivent passer par le même assemblage runtime afin qu’aucun
second heartbeat ou replayer ne contourne le verrou.

## Amendement 2026-09-24 — démarrage automatique par Desktop

Validé par l’humain le 2026-09-24. Avec l’autostart en opt-in, rien dans Desktop
ne démarrait le runtime : le sidecar répondait au bridge mais heartbeat, rejeu
de l’outbox et watchers ne tournaient jamais (`daemon.status` = `stopped`).
Desktop (`desktop/src-tauri/src/sidecar.rs`) pose donc `STUDIO_DAEMON_AUTOSTART=1`
dès qu’une origine serveur est configurée. Le daemon ne démarre le runtime que
s’il possède le verrou ; un daemon déjà présent reste attaché, et
`daemon.start` répond alors `already_running`.

## Validation attendue

Démarrage, attach, stop, restart, double lancement, mismatch d’identité,
credential révoqué, offline, crash/recovery bornée, logs redactés/rotatifs,
orphan process et shutdown propre.
