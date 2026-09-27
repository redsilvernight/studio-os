# C2 — Tests E2E inscription + upgrade N-1 → N

Roadmap « Desktop Distribution, Updates & Public Registration », étape C2.
Ce document relie chaque critère à des tests exécutables ; il ne consigne pas
de résultat d'exécution (voir le journal AI work de la tâche Studio OS).

## Cas d'échec (tâche `12b0c96f`)

| Cas | Test(s) | Niveau |
|---|---|---|
| Session expirée, falsifiée (autre clé, `alg=none`, altérée) | `tests/api/test_c2_failure_cases.py::test_expired_or_forged_session_is_refused_and_a_new_login_works` | API, parcours auto-inscrit |
| Session révoquée (mot de passe, reset, revoke-sessions) | `tests/api/test_session_cycle.py`, `tests/api/test_public_registration.py::test_reset_password_revokes_sessions_and_replays` | API |
| Compte désactivé en cours de session (JWT, machine, projets, login, enrôlement) puis réactivé | `tests/api/test_c2_failure_cases.py::test_account_disabled_mid_session_loses_session_machine_and_projects`, `tests/api/test_account_states.py`, `tests/api/test_events.py::test_stream_closes_at_once_when_the_owner_is_disabled` | API |
| Accès à un projet non accordé (lecture, listes filtrées, écriture) | `tests/api/test_c2_failure_cases.py::test_a_project_never_granted_is_unreadable_through_every_route`, `tests/api/test_a5_onboarding_journey.py`, `tests/api/test_authz.py` | API |
| Élévation de privilège (champs injectés, membres, projets, administration des utilisateurs, machine d'un autre, écriture readonly) | `tests/api/test_c2_failure_cases.py::test_self_registered_user_cannot_gain_any_privilege_through_the_api`, `tests/api/test_public_registration.py::test_self_registered_account_gets_no_privilege_by_field_injection`, `tests/api/test_account_states.py::test_no_endpoint_modifies_the_callers_own_account` | API |
| Réseau : serveur injoignable (enrôlement, identité, file hors ligne) | `tests/client/test_daemon_enrollment.py::test_unreachable_server_is_retryable`, `tests/client/test_machine_identity.py::test_unreachable_server_without_cache_yields_no_identity`, `tests/client/test_offline_replay_acceptance.py` | Client/daemon |
| Réseau : serveur d'update injoignable, téléchargement coupé (réessayable) | `desktop/src-tauri/src/updater.rs::the_update_flow_accepts_a_signed_release_and_refuses_every_bad_one` | Desktop (Rust) |
| Update invalide : métadonnées, autre clé, artefact corrompu, version gonflée/downgrade | idem `updater.rs` ; erreurs non divulgatrices : `errors_never_leak_transport_detail` | Desktop (Rust) |

Commandes (PostgreSQL de test migré requis, `STUDIO_TEST_DATABASE_URL`) :

```powershell
uv run pytest tests/api/test_c2_failure_cases.py tests/api/test_session_cycle.py tests/api/test_account_states.py tests/api/test_public_registration.py tests/api/test_a5_onboarding_journey.py -q
cd desktop/src-tauri; cargo test --lib updater   # signer : `npm ci` dans desktop/, sinon le test signé est ignoré
```

## Parcours nouvel utilisateur (tâche `2295a9ad`)

Voir `docs/DESKTOP_C2_NEW_USER_E2E.md` (Web et Desktop contre une API réelle jetable).

## N-1 → N (tâche `f22d8b10`)

Vraie release N-1 installée (canal `dev`, profil réel de l'utilisateur), mise à
jour par l'UI vers la release N signée publiée sur GitHub :

1. Avant : relever le SHA-256 des fichiers de `%APPDATA%\StudioOS-Dev` (hors
   `cache/`) et de `%APPDATA%\dev.studio-os.desktop-dev\shell-settings.json` ;
   noter la version affichée (Paramètres › Application).
2. Paramètres › Application › Détails techniques › « Rechercher une mise à
   jour » → « Installer la version N » ; l'application redémarre seule.
3. Après, contrôles :
   - `ProductVersion` de l'exécutable installé et version de l'assistant local = N ;
   - hashes inchangés pour `format.json`, `identity/*.json`, `workspaces/*.json`,
     `shell-settings.json`, base `outbox/*.sqlite3` (lecture Python : le daemon
     la verrouille), file intègre (`pragma integrity_check`) ;
   - assistant local « En marche », heartbeat et rejeu de la file « Fonctionne » ;
   - le poste reste le même dans Machines (pas de réenrôlement ni de doublon).

La reconnexion web après redémarrage n'est pas exigée ni interdite : le JWT
n'est gardé qu'en mémoire. Les invariants signés du flux (clé, artefact,
downgrade) restent couverts par `updater.rs` (section cas d'échec).
