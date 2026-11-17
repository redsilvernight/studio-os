# Enregistrement du depot d'un projet

Un projet Studio OS peut posseder un ou plusieurs **depots** (remotes Git
normalises `hote/organisation/depot`). Cet enregistrement est ce qui permet a
un depot local de retrouver son projet : `POST /projects/resolve-repository`
compare les remotes d'un depot de travail aux depots enregistres.

## 1. A la creation du projet (recommande)

`POST /projects` accepte un champ **optionnel** `repository` (toute forme
d'URL : `https`, `ssh`, `git@hote:chemin`). Le serveur le normalise et
l'enregistre avec le projet dans le meme appel ; la reponse (`201`) est un
`Project` dont `repositories` contient deja la cle normalisee.

- URL invalide : `422 invalid_repository_url`, aucun projet cree.
- Depot deja lie a **un autre** projet : `409 repository_already_linked`,
  aucun projet cree (le slug reste libre).
- Champ absent : le projet est cree sans depot (etat valide).

Le dashboard expose ce champ dans la modale « Nouveau projet » (« Adresse du
depot (facultative) »). Un plan d'initialisation (`studio.initialization/v1`)
ne porte pas ce champ (contrat fige) : un projet cree par `apply` est lie
juste apres par la route du §2, avec les memes codes d'erreur.

## 2. Apres coup : ajouter un depot a un projet existant

Obligatoire quand le projet a ete cree sans depot, et pour un second remote
(`origin` + `upstream` par exemple). Roles `admin` ou `developer` avec acces
au projet.

```bash
# 1. Verifier ce que le depot local resout deja (aucune ecriture)
curl -sS -X POST "$STUDIO_API/api/v1/projects/resolve-repository" \
  -H "Authorization: Bearer $STUDIO_MACHINE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"remotes": ["'"$(git remote get-url origin)"'"]}'

# 2. Lier le depot au projet (201, ou 200 si deja lie a ce projet)
curl -sS -X POST "$STUDIO_API/api/v1/projects/<project_id>/repositories" \
  -H "Authorization: Bearer $STUDIO_MACHINE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "'"$(git remote get-url origin)"'"}'

# 3. Relire (attendu : la cle normalisee dans "repositories")
curl -sS "$STUDIO_API/api/v1/projects/<project_id>" \
  -H "Authorization: Bearer $STUDIO_MACHINE_TOKEN"
```

`$STUDIO_API` inclut `/api/v1` (ex. `https://<hote-studio>/api/v1`). Le jeton
est le credential machine deja utilise par le client ; aucune nouvelle
autorisation n'est introduite.

## 3. Conflit : depot deja lie a un autre projet

L'unicite est globale : un remote appartient a **au plus un** projet.
`409 repository_already_linked` renvoie la cle normalisee dans `url` ; la
correction est explicite — retirer le lien du mauvais projet
(`DELETE /projects/{id}/repositories/{normalized_url}`) puis le lier au bon.
Le serveur ne deplace jamais un depot silencieusement.

## 4. Operation non executee ici : ratacher le depot Studi'OS a son projet

Ce changement ne modifie **aucune donnee** du Studio en service. Pour
rattacher le depot de code Studi'OS a son projet existant, executer les
trois commandes du §2 depuis la racine du depot, avec le `project_id` du
projet Studio OS correspondant (la commande 1 indique s'il est deja
resolu : `status: resolved` = rien a faire). Le resultat attendu est une cle
`hote/organisation/depot` (sans `.git`, sans port ni utilisateur) dans
`repositories`.
