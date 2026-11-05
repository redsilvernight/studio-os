---
kind: skill
stable_key: sound-design
scope: studio
description: "Sound design de jeu Godot : direction artistique (hiérarchie, identité, juiciness) et implémentation (buses, AudioStreamPlayer, pool, musique adaptative), sourcing SFX. Pas pour l'audio vidéo."
---

# Sound design (jeu)

Deux couches indissociables : le choix artistique (ce que le son fait ressentir, sa place dans le mix) et l'implémentation (buses et nœuds Godot). Un bon choix mal câblé sonne mal ; un câblage propre sans direction sonne générique.

## Prérequis

- Godot 4 et le projet accessible localement.
- Fiches de référence du skill : principes artistiques, implémentation Godot, banque de SFX (catalogues, licences, ajout avec confirmation).
- Absent : le signaler, proposer l'installation, ne jamais improviser un substitut.

## Quand charger quoi

- Première direction sonore d'un projet : principes artistiques d'abord (hiérarchie, layering, identité, silence, musique adaptative), avant tout GDScript.
- Câblage sur une direction décidée : implémentation Godot (buses, `AudioStreamPlayer`/`2D`/`3D`, pool, autoload, ducking, `linear_to_db()`).
- Besoin d'un SFX précis : fiche banque de SFX ; pour une musique, réutiliser la bibliothèque musicale du studio, sans la dupliquer. Tout téléchargement : source, licence, accord explicite.

## Périmètre

Le son dans le jeu (gameplay, menus). Le mixage d'une vidéo relève de `tiktok-pipeline`, même si la même piste sert aux deux.
