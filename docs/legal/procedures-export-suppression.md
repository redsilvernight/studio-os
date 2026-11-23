# Procédure d'export et de suppression des données d'un studio

> **BROUILLON — relecture juridique humaine requise.**
> Document préparé à titre indicatif (étape S5-exploitation). Il décrit le libre-service prévu par le produit (maquette « Export et suppression d'un studio », écran N7) et l'engagement qui l'entoure. Les valeurs marquées sont des valeurs d'illustration tant que les seuils définitifs (M-seuils, décision DEC-0387) ne sont pas arrêtés. Pas de code : description des mécanismes et des délais uniquement.

## 1. Principe

Le client possède ses données : un export complet, puis, s'il le veut, une suppression confirmée avec délai de grâce. L'export et la suppression se font depuis **Réglages › Confidentialité** et sont réservés au **propriétaire du studio**. Toute la procédure est traçable dans le journal du studio.

## 2. Export du studio

**Contenu de l'export.** Une archive datée de tout le studio : projets, notes, fichiers et journal. Un export ne vide rien : il ajoute une copie.

**Déroulement.**

1. Le propriétaire lance « Préparer l'export » ; la préparation est asynchrone : il peut quitter la page et est prévenu quand c'est prêt.
2. Une fois prêt, l'archive est proposée au téléchargement via un **lien pré-signé de courte durée (15 minutes, une seule utilisation — valeur d'illustration, À CONFIRMER avec les M-seuils DEC-0387)**.
3. Après expiration du lien, « Préparer un nouvel export » relance la préparation.

**Règles.**

- **Un seul export à la fois**, réservé au propriétaire.
- **À CONFIRMER** — l'archive peut-elle être conservée côté service quelques jours (au-delà du lien de 15 minutes) et avec quelle durée ? Sinon, téléchargement immédiat obligatoire.
- **À CONFIRMER** — la partie du journal personnel visible dans l'export (le journal étant append-only et chaîné, préciser ce qui est exporté et comment l'intégrité est vérifiable).

## 3. Suppression du studio

**Dialogue de conséquences.** La suppression commence toujours par un résumé explicite de ce qui sera effacé (par exemple : nombre de projets, notes, volume de fichiers, historique), et rappelle que les sauvegardes disparaissent à la fin de la rétention annoncée (30 jours — valeur d'illustration, À CONFIRMER).

**Confirmation.** Le propriétaire confirme en **saisissant le nom du studio** ; aucun autre chemin de suppression n'existe.

**Délai de grâce.**

- La suppression est **programmée 14 jours plus tard** (valeur d'illustration, À CONFIRMER — seuil définitif M-seuils DEC-0387).
- Pendant ce délai, le studio passe en **lecture seule** : les membres consultent, personne n'écrit.
- Le propriétaire peut **annuler** la suppression jusqu'à l'échéance ; à l'annulation, le studio redevient normal.

**Exécution.** À l'échéance non annulée :

- les contenus du studio (projets, notes, fichiers, historique, connaissances) sont effacés ;
- les copies présentes dans les **sauvegardes serveur** disparaissent à la fin de la rétention des sauvegardes (voir politique de confidentialité, section 5 ; durée post-suppression : **À CONFIRMER**) ;
- **À CONFIRMER** — sort des identifiants résiduels non personnels (compteurs, empreintes) nécessaires à l'intégrité du journal global.

## 4. Cas non couverts (À CONFIRMER)

- **Suppression d'un compte utilisateur** (indépendamment d'un studio) : procédure à définir — que devient l'appartenance aux studios, les instantanés d'exécution liés à ses machines, ses jetons ?
- **Studio inactif / compte inactif** : existence ou non d'une purge automatique.
- **Studio de l'utilisateur supprimé par l'administration** (illicibilité, réclamations) : articulation avec la section suspension des CGU.

## 5. Engagement récapitulatif

1. L'export complet est disponible en libre-service, sans frais, pour le propriétaire.
2. Aucune suppression définitive n'a lieu sans confirmation explicite et sans délai de grâce annulable.
3. Chaque étape (export préparé, demande de suppression, annulation, exécution) est journalisée de façon visible.
4. Les durées définitives seront fixées par les M-seuils (décision DEC-0387) avant publication : toutes les valeurs ci-dessus sont à revalider.

---

*Historique du document :*

| Date | Modification |
| --- | --- |
| 2026-11-23 | Première version (brouillon, S5-exploitation), à partir de la maquette N7. |
