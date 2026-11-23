# Sous-traitants et prestataires — Studi'OS

> **BROUILLON — relecture juridique humaine requise.**
> Document préparé à titre indicatif (étape S5-exploitation). Il recense les prestataires qui traitent des données pour le compte de l'éditeur, au sens de l'article 28 du RGPD. Les éléments non décidés sont marqués « À CONFIRMER » avec la question posée.

## Règles applicables à tous

- Tout prestataire n'intervient que sur instruction de l'éditeur, avec des garanties contractuelles écrites (article 28 RGPD).
- **À CONFIRMER** — pour chaque prestataire : existence et version du contrat de sous-traitance / DPA signé, et registre des traitements associé.

## 1. OVH SAS — hébergement

| Élément | Détail |
| --- | --- |
| Rôle | Hébergement du service en production : serveur privé virtuel (VPS), bases PostgreSQL, stockage objet MinIO, sauvegardes |
| Fait établi | Production migrée sur VPS OVH (décision DEC-0205, 2026-10-11) ; sauvegardes `pg_dump` + miroir MinIO sur le même hébergement |
| Coordonnées | OVH SAS, 2 rue Kellermann, 59100 Roubaix, France |
| Localisation des données | **À CONFIRMER** — site exact retenu (France/UE attendu) |
| Contrat | **À CONFIRMER** — DPA OVH et références à joindre |

## 2. Stripe — paiements (en préparation)

| Élément | Détail |
| --- | --- |
| Rôle envisagé | Traitement des paiements des abonnements payants (plans Pro) ; l'éditeur ne stocke pas de carte bancaire |
| Fait établi | Le code identifie déjà les clés Stripe comme secrets sensibles à ne jamais journaliser ; la facturation est une brique prévue de l'offre freemium (plans Gratuit/Pro) |
| Statut | **À CONFIRMER** — l'intégration Stripe n'est pas encore en production : entité contractuelle (Stripe Payments Europe Ltd ?), périmètre exact, moyens de paiement |
| Localisation des données | **À CONFIRMER** — traitement possiblement hors UE, garanties (clauses contractuelles types) à documenter |
| Contrat | **À CONFIRMER** — DPA / conditions Stripe applicables |

## 3. Relais SMTP — e-mails transactionnels

| Élément | Détail |
| --- | --- |
| Rôle | Envoi des e-mails essentiels du compte : vérification d'adresse à l'inscription, réinitialisation de mot de passe (décisions DEC-0109 et DEC-0128) |
| Fait établi | Le produit supporte un backend e-mail configurable : `disabled`, `file` (développement) ou `smtp` (relais générique, configuration et secrets côté serveur uniquement) |
| Fournisseur retenu | **À CONFIRMER** — aucun fournisseur SMTP de production n'est arrêté à ce jour (OVH mail relay, fournisseurs tiers ?). À choisir avant la mise en exploitation |
| Contenu transmis | Adresse e-mail du destinataire et contenu minimal de l'e-mail transactionnel ; aucune donnée de studio |
| Contrat | **À CONFIRMER** — selon fournisseur retenu |

## 4. À ajouter le cas échéant

**À CONFIRMER** — compléter cette liste si d'autres prestations manipulent des données : service d'assistance, supervision, envoi d'erreurs (crash reports, opt-in), modèles d'IA hébergés. Chaque ajout passera par la même grille (rôle, localisation, garanties, contrat).

## Changelog de la liste

| Date | Modification |
| --- | --- |
| 2026-11-23 | Première version (brouillon, S5-exploitation) : OVH, Stripe (en préparation), SMTP. |
