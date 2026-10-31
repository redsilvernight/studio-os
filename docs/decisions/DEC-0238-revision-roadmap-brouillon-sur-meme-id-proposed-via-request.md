---
id: DEC-0238
title: 'Révision roadmap : brouillon sur même ID, proposed via request_changes'
status: accepted
date: '2026-10-25'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0238 — Révision roadmap : brouillon sur même ID, proposed via request_changes

Proposition : étendre POST /roadmaps/{id}/proposals et studio_propose_roadmap aux brouillons, via moteur reconcile_document existant (conserve IDs et liens des étapes retenues, refuse suppression étape liée). base_revision_no contrôlé sous verrou ; nouvelle révision monotone snapshot si submit=false, proposal si submit=true. Commentaires des révisions antérieures inchangés. Sur proposed, aucun auteur ne peut modifier le contenu gelé directement : message invalid_state indique request_changes par rôle habilité puis révision draft. Active conserve pending proposal sans application jusqu'à revue humaine. Champ optionnel submit dans ProposalCreate, défaut true ; aucun agent ne gagne pouvoir d'approbation.
