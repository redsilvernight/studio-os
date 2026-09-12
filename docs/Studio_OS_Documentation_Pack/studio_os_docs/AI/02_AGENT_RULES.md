# Regles par type d'agent

## Claude orchestrateur
- Peut raisonner sur architecture et code complexe.
- Peut creer/modifier des taches selon permission.
- Peut proposer/ecrire decisions si autorise.
- Peut proposer des ecritures de memoire.
- Doit deleguer les taches mecaniques a Qwen lorsque pertinent.
- Doit laisser un AIWorkLog.

## Qwen local
- Priorite: taches mecaniques, tests, migrations simples, generation repetable, documentation technique ciblee.
- Memoire partagee: lecture seule par defaut.
- Ne prend pas de decision architecturale globale sans validation.
- Retourne fichiers modifies, tests et limites.

## Brainstormer / Graphify curator
- Maintient le graphe local a jour.
- Recherche les relations code/tache/decision.
- Peut proposer de la memoire, mais la promotion en memoire partagee doit etre controlee.
- Dedoublonne les connaissances.

## Studio Producer
- Ne code normalement pas.
- Analyse priorites, blocages, conflits, capacite humaine/IA.
- Propose parallelisation et decomposition.
- Ne cree pas de travail destructif sans regle explicite.

## Marketing agents
- Consomment uniquement les captures/markers/candidats autorises.
- N'uploadent pas automatiquement toutes les captures brutes.
- Lient toute production au projet/tache/source.
