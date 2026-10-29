---
id: DEC-0221
title: P06 — lever le no-go sur l'historique des configurations (remplace DEC-0219)
status: accepted
date: '2026-10-19'
supersedes:
- DEC-0219
superseded_by: []
source: server-export
---

# DEC-0221 — P06 — lever le no-go sur l'historique des configurations (remplace DEC-0219)

Le 19 octobre 2026, l'utilisateur a choisi dans le chat Claude « Lever le no-go » face au report de DEC-0219.
Livrer P06-history-option comme une vue descriptive. La population est TaskLaunch sur la période. La configuration combine harness_id, profile_key, profile_contract_version et profile_digest du lancement, ainsi que harness_version, provider et model tirés du ledger lié par task_launch_id. Une valeur absente s'affiche « inconnu » ; plusieurs valeurs distinctes s'affichent « mixte ».
Chaque taux porte n, période, définition et couverture. Les groupes ne sont jamais classés : ordre de clé stable et marquage comparable=false.
Le rapprochement ledger/AIWork compte les entrées liées et non attribuées. La mention « tests réussis ≠ garantie qualité » est toujours affichée.
Aucun minimum d'effectif n'est fixé. Le critère d'échantillon réel ne sera coché que sur des données de production effectivement relevées.
