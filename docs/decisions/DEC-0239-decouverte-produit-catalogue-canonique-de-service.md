---
id: DEC-0239
title: 'Découverte produit : catalogue canonique de service, progressif et adapté
  aux droits'
status: accepted
date: '2026-10-25'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0239 — Découverte produit : catalogue canonique de service, progressif et adapté aux droits

Proposition : une source de capacités produit dans le service A, consommée via GET /capabilities par CLI/Desktop et directement par le handler MCP fin studio_discover_capabilities. Distincte des définitions de bibliothèque : aucun texte de définition chargé, aucune publication. Catalogue limité aux fonctions réellement exposées (test de correspondance aux endpoints). Résumé6capacités, limite24, détail par clé avec exemple/prérequis/restrictions ; intents overview/start_project/configuration. Disponibilité = droits, projets/CI accessibles et dernier rapport machine, jamais une promesse de connectivité testée ; données locales Git renvoyées au diagnostic du setup, rapport absent/périmé explicite. Quatre états available/needs_configuration/not_authorized/unsupported. Les autorisations effectives restent dans les services ; lecture seule ne gagne aucun droit. Le profil MCP session expose un seul outil de découverte, pas tout le catalogue d'outils. Accueil charge uniquement au clic ; CLI capabilities et détail via --key.
