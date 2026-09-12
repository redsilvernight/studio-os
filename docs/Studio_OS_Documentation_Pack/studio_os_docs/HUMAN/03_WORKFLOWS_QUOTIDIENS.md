# Workflows quotidiens

## Demarrer une tache
1. L'utilisateur execute `studio work APO-142` ou choisit la tache dans le dashboard.
2. Le daemon detecte projet, branche Git et etat Godot.
3. Une WorkSession est creee.
4. Le heartbeat publie l'activite.
5. Le systeme peut proposer les fichiers a claim via Graphify.
6. L'enregistrement de session peut demarrer automatiquement.
7. Claude charge le contexte via MCP.

## Deleguer a Qwen
1. Claude ou le Producer identifie une sous-tache mecanique.
2. Une sous-tache est creee et attribuee a Qwen.
3. Qwen lit le contexte autorise.
4. Il travaille localement et journalise ses actions.
5. Le resultat passe en `needs_review`.
6. Un humain ou Claude valide avant fusion.

## Prendre une decision d'architecture
1. Un humain/Claude cree une proposition.
2. La proposition indique contexte, choix, raisons et consequences.
3. Apres validation, Studio OS genere DEC-XXXX.
4. La decision devient recherchable par les futurs agents.

## Eviter un conflit
1. Une tache claim `scripts/player/player.gd`.
2. L'autre developpeur ouvre une tache touchant le meme fichier.
3. Studio OS avertit du chevauchement.
4. Le developpeur peut continuer, changer de tache ou coordonner.

## Envoyer un gros fichier
1. `studio transfer send build.zip --to dev-b --project apotheosis`.
2. L'API cree un Transfer et une URL d'upload pre-signee.
3. Le client envoie directement le fichier a MinIO en multipart.
4. A la fin, le hash est verifie et le transfert passe a `ready`.
5. Le destinataire recoit une notification.
6. Le download utilise une URL pre-signee et peut reprendre apres coupure.

## Marquer un moment marketing
1. Pendant une capture: `studio mark "first successful gameplay"`.
2. Le marqueur est lie a la session/tache/recording.
3. Le worker MarketingCandidate cree une proposition de clip.
4. Le pipeline marketing peut ensuite traiter uniquement cette plage temporelle.

## Fin de journee
Studio OS genere un resume: taches, commits, travaux IA, decisions, builds, conflits, clips et transferts importants.
