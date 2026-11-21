# Annexe v1 — maquettes Atelier multi-studios et freemium (R0-maquettes)

Remplace, pour les écrans listés, les fiches de `docs/StudiOS_Refonte_Grand_Public_Atelier.pdf`. Les autres fiches du PDF restent valables ; leur reprise est prévue en R1+. Version v1, 2026-11-21, **en attente de validation du propriétaire** (gate avant R1-composants).

Ouvrir `index.html` (pages statiques, aucun réseau). Chaque fiche : états normal, vide, chargement, erreur, limite ; thème clair/sombre/système ; modes Simple/Expert. Valeurs de plans et seuils = illustrations (M-seuils, DEC-0387) ; prix « — € » (DEC-0383).

## Écrans révisés (existants.html)
| Fiche PDF | Fiche annexe | Changement |
|---|---|---|
| 13 Coque | E1 | sélecteur de studio avec rôle, entrée Abonnement du propriétaire, état studio unique |
| 11 Inscription | E2 | CGU et confidentialité à cocher, cas d'invitation |
| 12 Premiers pas | E3 | étape de création de studio |
| 53 Réglages · Comptes | E4 | membres et rôles de studio (Propriétaire, Administrateur, Membre, Lecture seule) |
| 54 Appareils | E5 | plafond du plan |
| 51 Fichiers | E6 | quota de stockage |
| Aide | E7 | lexique, limites sans objet |

## Écrans nouveaux (nouveaux.html)
N1 choix et création de studio · N2 invitations (envoi, acceptation valide/expirée/utilisée) · N3 Abonnement et Usage · N4 limite du plan atteinte · N5 studio suspendu · N6 journal d'accès et break-glass côté client · N7 export et suppression de studio.

## Console opérateur (console.html)
C0 connexion et MFA · C1 tableau de bord · C2 studios et suspension · C3 usage · C4 facturation · C5 demandes break-glass. Bandeau permanent « aucun contenu client » ; aucune vue de contenu.

## Contrastes
`contrastes.html` : 21 paires de tokens, clair et sombre, toutes conformes AA (texte ≥ 4,5 ; non-texte ≥ 3). Jeton `--bdf` ajouté pour les bordures de champ.

## États sans objet justifiés
E1/E2 : pas d'état vide (la coque et l'inscription existent toujours). N4/N7 : l'état « limite » ou « chargement » est porté par les variantes de la fiche.
