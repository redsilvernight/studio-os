---
id: DEC-0179
title: 'AIB R3 : reglages de lancement locaux persistes dans launch_settings.json'
status: accepted
date: '2026-10-01'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0179 — AIB R3 : reglages de lancement locaux persistes dans launch_settings.json

Tâches `d4c076ab` (commandes bridge), `fdd305e5` (application au runtime) et
`60fc6c30` (cette décision). Statut `accepted` (accord humain du 2026-10-01 ; fichier et
serveur alignés.

## Décide

- Les réglages édités par `launch.get_settings` / `launch.save_settings`
  (opt-in, concurrence 1-8, harnesses autorisés) sont persistés dans
  `launch_settings.json` sous le `data_root` du daemon, par écriture atomique.
  `config.toml` n'est jamais réécrit : il reste le fichier de l'utilisateur.
- Précédence : un `launch_settings.json` valide l'emporte sur les défauts de
  `config.toml` (`launch_opt_in`, `max_concurrent_launches`,
  `launch_allowed_harnesses`). Sans fichier, ces défauts s'appliquent.
- Échec fermé : fichier illisible ou invalide = opt-in faux et aucun harness.
  Le défaut `config.toml` n'est alors **pas** repris, pour qu'un fichier
  corrompu ne rouvre jamais les lancements.
- Un enregistrement exige `confirmed: true` et refuse tout harness absent du
  registre local ; la validation précède l'écriture.
- Le runtime évalue la config effective à chaque heartbeat et tirage : un
  enregistrement s'applique sans redémarrage (politique et capacités
  `accepts_launches`, `max_launches`).

## Conséquences

- Un opt-in posé dans `config.toml` est révocable par l'UI : dès qu'un fichier
  existe, il prime. Supprimer le fichier restaure les défauts `config.toml`.
- Seul le propriétaire de la machine peut autoriser les lancements (AIB-J) ; les
  droits par projet restent portés par le serveur (DEC-0175), pas par ce fichier.
- Écarte : réécrire `config.toml` (perte de commentaires, conflits d'édition) ;
  reprendre le défaut `config.toml` si le fichier est illisible (rouvre les
  lancements sur corruption).
