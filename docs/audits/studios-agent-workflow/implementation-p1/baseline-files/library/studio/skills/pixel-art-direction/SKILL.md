---
kind: skill
stable_key: pixel-art-direction
scope: studio
description: "Discipline et workflow PixelLab pour du pixel art de jeu cohérent : personnages, objets, tilesets, UI, polices, cartes, animations. À charger avant toute génération ou revue d'asset pixel art d'un projet."
---

# Direction pixel art (PixelLab)

Transforme les outils PixelLab, d'un assortiment d'appels de génération, en un style cohérent par projet. Lire avant le premier asset d'un nouveau projet ou thème, et revoir la section verrouillage de style à chaque nouvelle famille d'assets (personnages → tilesets → UI).

## Prérequis

- PixelLab accessible depuis l'agent (serveur d'outils PixelLab connecté au harnais) avec un compte actif.
- Absent : le signaler, proposer la connexion, ne jamais improviser un substitut.

## 1. Choix de l'outil

| Besoin | Outil |
|---|---|
| Personnage complet, 4/8 directions | `create_character` |
| Portrait | `create_portrait_character` |
| Nouvelle pose, tenue ou émotion d'un personnage existant | `create_character_state` |
| Animation de marche, course, attente, attaque | `animate_character` |
| Synchronisation labiale, réaction vocale | `create_vocal_animation`, `create_talking_gif` |
| Objet à une orientation | `create_1_direction_object` |
| Objet multi-orientations (coffre, ennemi, véhicule) | `create_8_direction_object` |
| Nouvel état d'un objet (ouvert, endommagé) | `create_object_state` |
| Animer un objet ou une image | `animate_object`, `animate_image` |
| Tile isométrique | `create_isometric_tile` |
| Tileset top-down | `create_topdown_tileset` |
| Tileset sidescroller / plateforme | `create_sidescroller_tileset` |
| Tiles de liaison (route, rivière, mur) | `create_path_tiles` |
| Kit modulaire de bâtiments | `create_building_kit` |
| Assemblage de carte et placement d'objets | `create_map`, `edit_map`, `place_map_object`, `move_map_object` |
| Décor ponctuel lié à une carte | `create_map_object` |
| Élément d'UI (bouton, panneau, icône, HUD) | `create_ui_asset` |
| Police bitmap | `create_font` |
| Convertir une image en pixel art | `image_to_pixelart` |
| Image pixel brute hors asset de jeu | `create_image_pixflux` / `create_image_pixen` / `create_image_pro` |
| Retoucher un asset | `edit_image`, `edit_image_pixen`, `inpaint_image`, `correct_pixelart` |
| Forcer une palette commune | `reduce_colors` |
| Recadrer ou nettoyer une frame de planche | `select_object_frames`, `unzoom_image` |

Doute sur un paramètre : interroger l'aide officielle PixelLab (`agent_help`) plutôt que deviner ; elle connaît l'API en vigueur.

## 2. Verrouillage de style — avant l'asset n° 2

Chaque type d'asset a son mécanisme de cohérence. Chaîner depuis le **premier asset accepté** du projet, jamais depuis un prompt neuf :

- **Personnages** : passer `reference_image_base64` (sprite du premier personnage accepté) à chaque `create_character` suivant — une seule source d'identité pour tout le casting.
- **Objets** : passer `style_object_id` (objet déjà terminé) comme ancrage.
- **Tilesets** : chaîner les transitions avec `lower_base_tile_id` / `base_tile_id` dans `create_topdown_tileset` ; ne jamais générer indépendamment les tilesets d'une même carte.
- **UI** : passer `style_image_base64` (capture du personnage principal ou d'un tileset) à `create_ui_asset` pour que l'UI corresponde au jeu, pas à un kit générique.
- **Appels du modèle pro** (`create_image_pro`, `edit_image`) : `style_copy=["color_palette","outline","detail","shading"]` pour verrouiller tous les axes en itérant.
- **Palette** : passer les assets finis dans `reduce_colors(palette_image_base64=...)` contre une image de palette canonique du projet.
- Garder `shading` et `detail` identiques pour tout un projet (par exemple toujours `"basic shading"` + `"medium detail"`) : un shading incohérent fait paraître le casting issu de jeux différents.

## 3. Barre de qualité (non négociable)

- **Canevas** : une taille par classe d'assets — 16×16 ou 32×32 pour personnages et objets, multiples plus grands (48×48, 64×64) seulement pour boss ou héros si l'échelle l'exige. Jamais de tailles mélangées dans un tileset ou un casting.
- **Silhouette d'abord** : un sprite doit se lire en silhouette noire pure. Deux personnages confondables en silhouette : rejet, pas retouche de détail.
- **Rampes à décalage de teinte** : ombres vers des teintes plus froides et sombres, lumières vers plus chaud et clair ; une rampe de seule luminosité paraît bon marché.
- **Animation à volume constant** : chaque frame conserve volume et identité de silhouette.
- **Tiles pensés par les bords** : un tile ne vaut que s'il se raccorde proprement à ses voisins ; le juger sur ses raccords, pas isolé.
- **Aucun lissage en aval** : affichage et export à facteur entier, filtrage au plus proche voisin ; jamais de filtrage bilinéaire ni d'échelle non entière.
- **Palette indexée et limitée** : peu de couleurs, partagées ; une palette débridée trahit des assets générés sans verrouillage.

## 4. Organisation et coûts

- `list_projects()` pour obtenir un `project_id` ; `add_to_project(project_id, asset_id)` juste après chaque génération acceptée. Aucun projet PixelLab : le dire, en créer un ou ranger localement (dossier du kit de marque du projet) en attendant ; ne jamais sauter l'organisation en silence.
- Taguer chaque asset (`update_character_tags` / `update_object_tags`) avec un libellé projet ou thème, pour le retrouver (`list_characters(tags=...)`, `list_objects(tags=...)`) au lieu de le régénérer.
- `get_balance()` avant un gros lot : une fois les générations du cycle épuisées, les appels suivants sont facturés sur le solde sans avertissement. Connaître le chiffre avant, pas en cours de route.
- Facturation, déploiement ou question non couverte ici : `agent_help` avant d'improviser ; ce fichier peut dériver du produit réel.
