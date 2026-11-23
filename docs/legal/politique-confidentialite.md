# Politique de confidentialité — Studi'OS

> **BROUILLON — relecture juridique humaine requise.**
> Document préparé à titre indicatif (étape S5-exploitation), conforme dans l'esprit au RGPD. Il ne constitue pas un avis juridique et ne doit pas être publié sans validation par un professionnel du droit. Les éléments non décidés sont marqués « À CONFIRMER » avec la question posée.

## 1. Responsable du traitement

**À CONFIRMER** — la personne morale éditrice de Studi'OS (voir [mentions légales](mentions-legales.md)), ses coordonnées complètes et son contact dédié à la protection des données.

- Délégué à la protection des données (DPO) : **À CONFIRMER** — un DPO est-il désigné (obligatoire ou non selon les traitements) ? Sinon, quel contact « protection des données » publier ?

## 2. Quelles données sont traitées

Selon votre usage du service :

- **Compte** : adresse e-mail, mot de passe (stocké sous forme hachée, jamais en clair), nom affiché ; statut de vérification de l'adresse.
- **Studios et contenus** : projets, notes, fichiers, connaissances, historiques — ce sont vos données, isolées par studio (décision DEC-0382).
- **Données techniques et de mesure** : journaux techniques, mesures d'usage des ressources (consommation des lancements et des agents, décision DEC-0251), mesures d'infrastructure agrégées (décision DEC-0384).
- **Instantanés d'exécution** : lorsque les agents travaillent, un instantané lié à chaque lancement capture des références et empreintes (versions, digests, état Git) — **ni prompts ni secrets par défaut**, avec anonymisation obligatoire (décision DEC-0199).
- **Journal des accès d'exception** : demande, accord ou refus du propriétaire, durée, portée, consultations — en append-only avec chaînage par hachage.
- **Facturation** (si abonnement payant) : données traitées par le prestataire de paiement. **À CONFIRMER** — quelles données de facturation l'éditeur conserve-t-il lui-même (adresses, invoices) ?

Les chemins locaux, notes privées et captures brutes de vos machines ne sont pas publiés par défaut ; seules les données explicitement classées projet/studio sont partagées.

## 3. Finalités et bases légales

| Finalité | Exemples | Base légale (proposition) |
| --- | --- | --- |
| Fournir le service | comptes, studios, projets, transferts, agents | Exécution du contrat |
| Sécurité et prévention des abus | journaux d'audit, jetons par machine révocables, MFA des opérateurs | Intérêt légitime |
| Communication essentielle | vérification d'adresse, réinitialisation de mot de passe | Exécution du contrat |
| Facturation des plans payants | abonnements, paiement | Exécution du contrat |
| Obligations légales | conservation comptable le cas échéant | Obligation légale |
| Amélioration mesurée du service | métriques agrégées, sans contenu client | Intérêt légitime |

**À CONFIRMER** — tableau à faire valider qualification par qualification par le juriste (notamment l'intérêt légitime pour les métriques).

## 4. Qui accède à vos données

- **Par défaut, personne chez Studi'OS ne lit le contenu de votre studio.**
- Les opérateurs travaillent depuis une console distincte qui **ne montre jamais le contenu des studios** : seulement des mesures, des statuts et des journaux sans contenu. Leur connexion exige une authentification multifacteur et leur liste est fixée en configuration serveur.
- Un accès d'exception à des journaux techniques ou des métadonnées n'est possible qu'après une demande motivée **et votre accord explicite** si vous êtes propriétaire du studio, avec durée et portée limitées, journalisation visible et révocation à tout moment (voir CGU, section 6).
- Les sous-traitants techniques (hébergement, paiement, e-mail) sont listés dans [la page sous-traitants](sous-traitants.md).

## 5. Durées de conservation

Valeurs en vigueur dans le produit (défauts documentés) :

| Donnée | Durée |
| --- | --- |
| Transferts temporaires | 7 jours |
| Fichiers de build | 30 jours |
| Instantanés d'exécution | 90 jours (purge automatique des expirés) |
| Sauvegardes serveur | 14 jeux de sauvegarde conservés (rotation) |
| Compte et studios | tant que le compte existe |

**À CONFIRMER** — les valeurs suivantes ne sont pas encore arrêtées : durée de rétention des sauvegardes après la suppression définitive d'un studio (30 jours annoncés dans la maquette, valeur d'illustration) ; durée de conservation d'un compte inactif ; durée de conservation des journaux techniques et du journal des accès d'exception ; durées comptables légales applicables.

## 6. Sécurité

Mesures en place dans le produit : HTTPS obligatoire hors développement local ; un jeton par machine, révocable indépendamment ; buckets de stockage privés et URL pré-signées courtes ; PostgreSQL et MinIO non exposés publiquement ; validation stricte des chemins et des noms de fichiers ; journaux d'audit pour les actions sensibles ; secrets hors dépôt Git, en variables d'environnement.

## 7. Vos droits

Vous disposez des droits d'accès, de rectification, d'effacement, de portabilité, d'opposition et de limitation, que vous exercez via le contact indiqué en section 1. **À CONFIRMER** — l'adresse d'exercice des droits et le délai de réponse internalisé (le RGPD impose un délai maximal d'un mois).

- **Portabilité et export** : l'export complet d'un studio (projets, notes, fichiers, journal) est disponible en libre-service pour le propriétaire — voir [la procédure d'export et de suppression](procedures-export-suppression.md).
- **Effacement** : la suppression d'un studio est en libre-service avec délai de grâce annulable ; la suppression d'un compte individuel : **À CONFIRMER** — procédure à définir.
- Vous pouvez saisir la CNIL (www.cnil.fr) de toute réclamation.

## 8. Transferts hors Union européenne

Les données sont hébergées chez OVH (France). **À CONFIRMER** — vérifier, sous-traitant par sous-traitant (paiement, e-mail), si un transfert hors UE peut intervenir et les garanties associées (clauses contractuelles types, TIA) ; documenter le résultat ici.

## 9. Cookies et traceurs

**À CONFIRMER** — inventaire exact à réaliser : quels cookies/stockages locaux le client web et l'application de bureau utilisent-ils réellement (session, préférences de thème), et un bandeau de consentement est-il nécessaire (a priori non pour le strict fonctionnel) ?

---

*Historique du document :*

| Date | Modification |
| --- | --- |
| 2026-11-23 | Première version (brouillon, S5-exploitation). |
