# Revue Agents — P02-wf-agents (wireframes/agents.html)

Source fidèle : `dashboard/src/views/agents.ts` (+ `agents.css`) — identités, signaux d'activité dérivée, résumé « Travaille sur › dernier travail › tâche prise », machine d'exécution, renvois Bibliothèque / Machines / Paramètres. Langage : `wireframes/index.html` (tokens, rail/sidebar, `Ctrl K`, point de couleur, `Détails techniques` replié, un seul `connection-status`, ≤ 68 ch).

## Écran actuel : reste / disparaît / se déplace

| Élément actuel (`agents.ts`) | Verdict | Maquette |
|---|---|---|
| Titre « Agents IA » + phrase calme, recherche locale + compteur « affichés / chargés » | Reste | En-tête Liste + champ « nom ou rôle » + compteur |
| Nom humain + lien fiche, nature déclarée (`agent_kind`) | Reste | Nom + « Rôle » (rôle, dispo et projet visibles par ligne) |
| 5 signaux honnêtes (session ouverte, récent, passé, inconnu, aucun) + « pas preuve de connexion » | Reste | Libellés intacts, point de couleur à la place des badges |
| Résumé honnête (travaille sur › dernier travail › tâche prise › rien affirmé) | Reste | Héros « Travaille sur… » (Liste : aperçu ; Fiche : héros) |
| Machine d'exécution (nom humain), états vides, notice « Activité inconnue » | Reste | Props « Machine », `empty`, notice conservée en intention |
| Sections fiche : Activité, Travail actuel, Résumé, Travail produit, Sessions, Environnement | Reste | Héros + Activité + Travail produit + Sessions + Environnement condensé |
| Fournisseur / modèle / harnais affichés dans la carte | Disparaît (du défaut) | Repliés dans « Détails techniques » |
| IDs agent/machine, version, dates visibles ou en clair | Disparaît (du défaut) | Repliés, copie sur clic, aucun UUID en `innerText` |
| Badges / statuts redondants par ligne | Disparaît | Un point de couleur porte le statut |
| Propriétés (rôle, dispo, projet, machine, màj) en flux | Se déplace | Ligne métal sous 1400 px, colonne latérale dès 1600 px |
| Travail produit, sessions | Se déplace | Volet contexte à 2560 px (Liste) ; sections Fiche avec renvoi « À valider » |
| « Informations techniques » (`<details>`) | Se déplace | « Détails techniques » unique : modèle, permissions, IDs |

## Écarts assumés

- Actions « Administration » (Renommer, Voir la machine, Paramètres runtime, Révoquer) : intention neuve, aucun contrat ni UI actuels ; regroupées en carte pointillée hors flux quotidien.
- « Permissions » : `Agent` n'expose pas de permissions ; libellé illustratif renvoyant aux Paramètres runtime, sans inventer de mapping runtime/modèle.
- 3 groupes Liste (En activité / Actifs récemment / Inactifs) : projection lisible des 5 signaux, signaux exacts gardés en fiche.
- « Agent sans nom » / « Rôle non renseigné » : applique C2 là où le code a un kind vide ou un fallback générique.
- Valeurs modèle illustratives, sans UUID ni mapping inventé (respecte l'en-tête d'`agents.ts`).

## Mapping par largeur

| Écran | 1280 (rail 72) | 1600 (sidebar 236) | 2560 (sidebar 236) |
|---|---|---|---|
| Liste | Maître-détail : liste 360 + aperçu, props en ligne métal | Liste 400 + aperçu (contenu + props 260) | + volet 380 : travail produit, sessions, projet suivi |
| Fiche | Principal + contexte 300 (propriétés) | 760 + 340 (+ travail récent) | + colonne 420 : projets suivis, décisions liées |

Aucune carte ne s'élargit ; texte courant ≤ 68 ch ; ligne de flottaison pointillée par largeur.

## C1–C4 (4 lignes)

C1 — Liste : l'aperçu porte l'unique primaire « Ouvrir le travail… » ; Fiche : le héros porte la même action, ≤ 1 clic vers la tâche.
C2 — 0 UUID par défaut (noms humains, « Agent sans nom ») ; modèle, permissions et IDs seulement dans « Détails techniques » déplié.
C3 — ≤ 4 éléments majeurs par écran (Liste : liste + aperçu + contexte ; Fiche : héros, activité, travail, sessions + admin séparée).
C4 — Exactement 1 `connection-status` visible (sous l'avatar, même bascule rail/sidebar que `index.html`), aucun doublon.
