---
id: DEC-0194
title: 'AI Library : kind « hook » (studio.library.hook/v1), relation uses_hook, consentement
  par machine'
status: accepted
date: '2026-10-08'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0194 — AI Library : kind « hook » (studio.library.hook/v1), relation uses_hook, consentement par machine

Changement additif : LibraryKind.HOOK, BindingRelation.USES_HOOK (agent_definition→hook, workflow→hook ; hook ne source aucun binding). Contenu `studio.library.hook/v1` : event abstrait fermé (session_start, session_end, user_prompt, pre_tool, post_tool, stop, subagent_stop, notification, pre_compact), matcher (seulement pre_tool/post_tool), mode blocking|advisory (blocking seulement pre_tool/user_prompt/stop), timeout 1–600 s, 1–8 scripts inline {os, shell, body} uniques par (os, shell), aucun secret (422 invalid_hook). Pas de migration (kind/relation en chaînes). Côté client : projection par harnais (Claude settings.json, plugin OpenCode ; événement non exprimable → ignoré et signalé, jamais approximé), fusion sans toucher aux hooks non gérés, manifeste, dry-run/diff, et exécution soumise à un consentement explicite par machine sur l'empreinte sha256 du contenu (nouvelle version = nouveau consentement) ; désactivation locale possible ; version dépréciée/inactive retirée à la synchro.
