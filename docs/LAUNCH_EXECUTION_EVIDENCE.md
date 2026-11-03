# Précontrôle et preuves d'exécution

`pwsh scripts/test-env.ps1` vérifie les services existants et la révision Alembic
sans lancer Docker et sans migrer. Il respecte `STUDIO_TEST_DATABASE_URL` et
`STUDIO_S3_ENDPOINT_URL`, y compris pour PostgreSQL/MinIO natifs. Un contrôle
réussi retourne 0 ; une infrastructure absente ou un schéma non à jour retourne
2 avec `environment_unavailable`. Aucun `ready` n'est imprimé après un échec.
Le code Alembic réel figure dans le diagnostic d'échec ; son processus possède
une limite de temps et s'exécute depuis `services/api`.

Le démarrage des conteneurs de test nécessite `-StartServices`. Une migration
nécessite séparément `-Migrate`. Ces mutations exigent une base locale nommée
`test_*` ou `*_test`. Les endpoints personnalisés restent vérifiables sans
Docker. Le démarrage de Docker Desktop exige au moins 16 Gio de marge de mémoire
engageable et 4 Gio de RAM disponible ; aucun autre processus n'est arrêté pour
libérer cette mémoire. Le script ne crée aucun conteneur.

Le daemon conserve le code de sortie réel du harnais dans l'extrait de résultat.
Il lit aussi les événements structurés Codex (`--json`) et Claude
(`--output-format stream-json --verbose`). Une commande Codex qui annonce
`completed` avec `exit_code=1` est un échec. Les erreurs structurées de tour,
de résultat Claude et d'outil ne sont pas effacées par un processus qui sort
avec 0 : le lancement est signalé `failed`. Le code de raison existant
`harness_exited` reste accompagné d'un diagnostic plus précis dans l'extrait.

La dernière observation d'une commande Codex exactement identique remplace sa
précédente observation ; réussir une autre commande ne masque pas son échec.
L'absence de pytest et certaines erreurs explicites de connexion PostgreSQL
ou Docker sont classées `environment_unavailable`. Les autres échecs observés
portent `validation=failed`. La lecture est bornée à 64 K caractères et 512
documents ; seuls 20 codes de commandes figurent dans l'en-tête.

`validation=unverified` signifie qu'aucune preuve de validation du livrable
n'est disponible, même si le processus s'est terminé correctement. Une phrase
comme « tous les tests passent » ne constitue aucune preuve. Une sortie
inconnue, corrompue ou tronquée ne prouve pas une validation réussie. Le champ
`evidence_truncated` expose cette limite ; les anciens événements sortis du
tampon ne sont pas reconstruits. Les résultats Claude sans code de commande
restent sans code inventé. Les formats OpenCode non reconnus restent non
vérifiés. Ce diagnostic ne remplace pas la revue ni les critères de la tâche.

Formats de référence : [Codex non interactif](https://learn.chatgpt.com/docs/non-interactive-mode)
et [Claude Code programmatique](https://code.claude.com/docs/en/headless).

Tests : `tests/harness/test_test_env_preflight.py`,
`tests/client/test_execution_evidence.py`, `tests/client/test_launch_executor.py`.
Ils utilisent des processus factices et des services de test locaux ; ils ne
lancent aucun modèle.
