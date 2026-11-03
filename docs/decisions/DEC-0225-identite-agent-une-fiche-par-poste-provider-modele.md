---
id: DEC-0225
title: 'Identité agent : une fiche par (poste, provider, modèle), indépendante du
  harnais (remplace DEC-0180)'
status: accepted
date: '2026-10-20'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0225 — Identité agent : une fiche par (poste, provider, modèle), indépendante du harnais (remplace DEC-0180)

Contexte : Retours 13. Choix utilisateur : une fiche par modèle et par PC, réutilisée entre projets et outils. DEC-0180 incluait le harnais dans la clé (`agents-ensure-<harnais>:<provider>/<modele>`), d'où une fiche par outil pour un même modèle ; le lanceur daemon utilise une troisième clé (`launch-agent-<sha>`).

Décide :
- Clé unique, construite par un seul helper client : `agent-model:<provider|unknown>/<modele normalisé>`, scopée par la machine authentifiée (contrainte existante `(machine_id, stable_key)`). Hooks (tous harnais) et lanceur daemon l'utilisent.
- Métadonnées de la fiche identiques pour tous les appelants : `display_name` = modèle normalisé, `harness` = null, `provider`, `model`. Le harnais/outil reste attribué à l'exécution (`ai_work.harness`, déjà au contrat), jamais à la fiche.
- Normalisation minimale et explicite : trim, minuscules, séparation `provider/modele` ; aucune fusion de variantes (dates, tailles) : des modèles différents gardent des fiches différentes. Modèle inconnu : pas de fiche modèle, repli explicite sur l'agent du harnais (DEC-0099), libellé « modèle inconnu ».
- Concurrence : l'identité est la fiche, l'exécution est la session ; deux sessions simultanées du même modèle restent deux sessions distinctes.
- Doublons existants (clés DEC-0180 et `launch-agent-*`) : conservés intacts (historique, autorisations, provenance) ; le dashboard les regroupe par (poste, modèle) et les marque « ancienne identité ». Aucune suppression ni réécriture de provenance.
- Aucun changement de contrat versionné : `stable_key` et `POST /agents/ensure` sont déjà additifs.

Conséquences : une seule fiche par modèle et par PC pour les nouvelles sessions ; l'autre PC a sa propre fiche (scope machine). Écarté : migration de données fusionnant les fiches (perte de provenance).
