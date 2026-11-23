# Conditions générales d'utilisation — Studi'OS

> **BROUILLON — relecture juridique humaine requise.**
> Document préparé à titre indicatif (étape S5-exploitation). Il ne constitue pas un avis juridique et ne doit pas être publié sans validation par un professionnel du droit. Les clauses portant sur des faits non encore décidés sont marquées « À CONFIRMER » avec la question posée ; aucune valeur chiffrée non décidée n'est présentée comme définitive.

## 1. Objet et acceptation

Les présentes conditions générales d'utilisation (CGU) encadrent l'accès et l'utilisation du service Studi'OS : une plateforme de gestion de projets assistée par intelligence artificielle, organisée en « studios » (espaces de travail isolés les uns des autres), accessible par application de bureau et interface web.

L'utilisation du service implique l'acceptation des présentes CGU et de la [politique de confidentialité](politique-confidentialite.md). **À CONFIRMER** — le mode d'acceptation (case à cocher explicite lors de l'inscription ? acceptation tacite à la mise à jour ?) et la procédure de notification des modifications.

## 2. Compte et inscription

- L'inscription se fait par adresse e-mail : l'adresse est enregistrée d'abord, puis le mot de passe et le nom affiché sont définis lors de la vérification de l'adresse, par le détenteur de la boîte (décisions DEC-0109 et DEC-0128).
- Une même personne peut appartenir à plusieurs studios et basculer entre eux ; elle agit toujours dans le studio actif qu'elle a choisi (décision DEC-0382).
- Les rôles dans un studio (propriétaire, admin, membre…) déterminent les droits ; seules les personnes autorisées accèdent à un studio donné (décisions DEC-0382 et DEC-0386).
- La création de comptes par des mineurs : **À CONFIRMER** — une limite d'âge minimum est-elle fixée ?

## 3. Studios et contenus des clients

- Chaque studio isole ses projets, notes, fichiers, journaux et connaissances : une ressource d'un autre studio n'est ni visible ni accessible (isolation par studio, décision DEC-0382).
- **Le client (propriétaire du studio) possède ses données** : projets, notes, fichiers et historique. Studi'OS n'acquiert aucun droit de propriété sur ces contenus et n'y accède pas par défaut (voir politique de confidentialité).
- Le client est responsable des contenus qu'il dépose et de la légitimité de leur traitement (y compris vis-à-vis des personnes qu'il invite dans son studio).

## 4. Abonnement, prix et paiement

- Le service repose sur une offre freemium : plan Gratuit et plan payant (Pro), avec des limites annoncées dans l'interface (« limite du plan atteinte » avec action de mise à niveau).
- **À CONFIRMER** — les tarifs et les valeurs des plans ne sont pas fixés à ce jour (décision DEC-0383 : prix « — € »). Toute clause tarifaire (montant, périodicité, prorata, révision des prix) restera lettre morte tant que la décision tarifaire ne sera pas prise.
- Le paiement est délégué à un prestataire de paiement externe (voir `sous-traitants.md`). **À CONFIRMER** — Stripe est le prestataire envisagé : intégration, entité contractuelle, moyens de paiement acceptés et gestion des échecs de prélèvement restent à arrêter.
- **À CONFIRMER** — période d'essai, droits de rétractation, et traitement de la TVA selon le pays du client.

## 5. Suspension d'un studio

Un studio peut passer en **lecture seule** dans deux cas : impayé prolongé, ou décision de l'administration du service (maquette d'écran « Studio suspendu »). Dans cet état :

- la consultation des contenus reste possible pour les membres ;
- les actions d'écriture sont masquées ou bloquées ;
- l'interface explique la raison, ce qui reste permis et comment rétablir le studio.

**À CONFIRMER** — durée de l'impayé déclenchant la suspension, préavis envoyé au propriétaire, et sort des données d'un studio suspendu durablement (voir aussi procédure d'export et de suppression).

## 6. Accès d'exception (break-glass) et confidentialité

Par défaut, **personne chez Studi'OS ne lit le contenu d'un studio**. Un accès d'exception n'existe que si toutes les conditions suivantes sont réunies :

1. une demande motivée par un opérateur (la console opérateur, protégée par authentification multifacteur, ne montre jamais le contenu des studios) ;
2. **l'accord explicite du propriétaire du studio**, dans l'interface, pour cette demande précise ;
3. une durée et une portée limitées — seuls les journaux techniques et les métadonnées sont demandables, la portée « contenu » n'existe pas ;
4. une journalisation visible par le client (journal en append-only avec chaînage par hachage), avec révocation possible à tout moment.

Les plafonds de durée et de portée sont illustratifs dans les maquettes (4 heures par demande) : **À CONFIRMER** — seuils définitifs issus des M-seuils (décision DEC-0387).

## 7. Export et suppression

Le client dispose, à tout moment et sans frais, d'un export complet de son studio (projets, notes, fichiers, journal) puis, s'il le souhaite, d'une suppression confirmée avec un délai de grâce annulable (maquette d'écran « Export et suppression »). Les modalités opérationnelles sont détaillées dans [la procédure dédiée](procedures-export-suppression.md).

## 8. Disponibilité et évolution du service

- Le service est fourni avec des sauvegardes régulières et des mécanismes de restauration documentés ; aucune garantie de disponibilité chiffrée n'est fixée à ce stade. **À CONFIRMER** — un engagement de niveau de service (SLA) est-il promis, et lequel ?
- L'éditeur peut faire évoluer le service ; les évolutions supprimant des fonctionnalités déjà payées : **À CONFIRMER** — préavis et modalités.

## 9. Responsabilité

- L'éditeur est tenu d'une obligation de moyens pour la fourniture du service.
- L'éditeur ne contrôle pas les contenus des clients et n'assume pas leur exactitude ou licéité.
- **À CONFIRMER** — rédaction par le juriste des limitations de responsabilité applicables (faute lourde/dolosive, dommages indirects, montant de plafonnement le cas échéant), en cohérence avec le droit français.

## 10. Durée, résiliation et sort des données

- Les CGU s'appliquent tant que le client utilise le service.
- Le propriétaire d'un studio peut exporter puis supprimer son studio à tout moment (section 7) ; la suppression passe par un délai de grâce annulable.
- **À CONFIRMER** — résiliation d'un simple compte utilisateur (sans studio) : procédure et sort des données à définir.

## 11. Litiges et droit applicable

- Les présentes CGU sont soumises au droit français.
- Réclamation préalable auprès du contact de l'éditeur (voir mentions légales).
- Consommateurs : recours possible à un médiateur de la consommation. **À CONFIRMER** — adhésion à un dispositif de médiation et références à indiquer.
- Attribution de juridiction : **À CONFIRMER** — clause à rédiger par le juriste.

---

*Historique du document :*

| Date | Modification |
| --- | --- |
| 2026-11-23 | Première version (brouillon, S5-exploitation). |
