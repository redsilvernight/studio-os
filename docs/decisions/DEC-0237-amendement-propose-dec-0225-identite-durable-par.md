---
id: DEC-0237
title: 'Amendement proposé DEC-0225 : identité durable par utilisateur, harnais logique
  et modèle effectif'
status: accepted
date: '2026-10-25'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0237 — Amendement proposé DEC-0225 : identité durable par utilisateur, harnais logique et modèle effectif

Nouvelle exigence explicite utilisateur du 25/10/2026 : même harnais/modèle doit retrouver son ID, entre conversations/tâches/rôles/redémarrages et postes autorisés du même utilisateur. DEC-0225 accepted est vérifiée : elle impose machine+provider+model et harness=null ; elle doit donc être amendée, pas interprétée comme satisfaisant cette demande.
Proposition : identité canonique unique serveur/utilisateur/harnais logique/provider/modèle effectif ; interfaces Desktop/CLI partagent le harnais logique lorsque le produit sait qu'elles sont équivalentes (codex, claude, opencode). Alias de sélection conservé en trace séparée, jamais présumé modèle effectif. Modèle/provider non observables => état explicite inconnu, aucune nouvelle fiche modèle inventée. Sessions et AIWork conservent machine exécutante et interface. Les identités historiques restent immuables ; rapprochement explicite réversible sans réattribution de provenance, et aucun effacement aveugle. Resolution/create sérialisée par contrainte unique et transaction. Ownership doit vérifier utilisateur courant + machine autorisée, pas exiger que la fiche soit créée par la machine courante.
À valider avant intégration : contrats API/Auth/Data, mapping interfaces exact, migration additive et tests concurrence, cross-user/cross-machine, changement modèle et historiques. Cette proposition ne donne aucun droit supplémentaire à un agent et n'est pas une acceptation de DEC.
