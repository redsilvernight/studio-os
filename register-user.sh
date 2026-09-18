#!/usr/bin/env bash
# Studi'OS — administrateur : provisionner un utilisateur humain sur
# l'instance déployée. Opération privilégiée côté serveur ; aucune inscription
# publique n'existe et aucune API anonyme ne crée de compte.
#
# Usage : ./register-user.sh
#
# Le script ne connaît que Docker Compose : il délègue toute la logique métier
# à la CLI `studio-admin` exécutée dans le conteneur `api`, exactement le même
# chemin que `POST /users` / `POST /machines`. Aucun accès direct à PostgreSQL,
# aucun hostname/IP/chemin propre au laptop : le même fichier fonctionne sur le
# déploiement Docker Compose local et sur celui du VPS.
set -euo pipefail
export MSYS_NO_PATHCONV=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="$ROOT_DIR/docker"

PASSWORD=""
MACHINE_TOKEN=""
MACHINE_ID=""
cleanup() { unset PASSWORD MACHINE_TOKEN 2>/dev/null || true; }
trap cleanup EXIT

die() {
  echo "erreur: $*" >&2
  exit 1
}

# --- Préflight -------------------------------------------------------------

command -v docker >/dev/null 2>&1 || die "docker introuvable. Installez Docker puis réessayez."
docker compose version >/dev/null 2>&1 || die "le plugin 'docker compose' v2 est introuvable."
[[ -d "$COMPOSE_DIR" ]] || die "répertoire docker/ introuvable à côté de register-user.sh"

compose() { ( cd "$COMPOSE_DIR" && docker compose "$@" ); }
run_admin() { compose run --rm -T api python -m studio_api.admin_cli "$@"; }

if [[ -z "$(compose ps -q postgres 2>/dev/null)" ]]; then
  die "les services Studi'OS ne sont pas démarrés. Lancez d'abord :
       cd docker && docker compose up -d"
fi

if ! run_admin user --help </dev/null >/dev/null 2>&1; then
  die "impossible d'exécuter 'studio-admin user' dans le conteneur api.
       L'image est peut-être absente ou antérieure à cette commande :
       cd docker && docker compose build api"
fi

# --- Saisie interactive ----------------------------------------------------

echo "Studi'OS — Provisionnement utilisateur"
echo "───────────────────────────────────────"
echo ""

read -rp "Nom affiché : " DISPLAY_NAME
while [[ -z "${DISPLAY_NAME// /}" ]]; do
  echo "Le nom affiché ne doit pas être vide." >&2
  read -rp "Nom affiché : " DISPLAY_NAME
done

read -rp "Email : " EMAIL
EMAIL="$(printf '%s' "$EMAIL" | tr '[:upper:]' '[:lower:]')"
while [[ -z "$EMAIL" || "$EMAIL" != *"@"* ]]; do
  echo "Adresse email invalide." >&2
  read -rp "Email : " EMAIL
  EMAIL="$(printf '%s' "$EMAIL" | tr '[:upper:]' '[:lower:]')"
done
SAFE_EMAIL="$(printf '%s' "$EMAIL" | tr -c '[:alnum:]._-' '_')"

ROLES=(developer admin agent readonly)
echo ""
echo "Rôles disponibles :"
for i in "${!ROLES[@]}"; do
  echo "  $((i + 1)). ${ROLES[$i]}"
done
read -rp "Rôle [1] : " ROLE_CHOICE
ROLE_CHOICE="${ROLE_CHOICE:-1}"
if ! [[ "$ROLE_CHOICE" =~ ^[0-9]+$ ]] || (( ROLE_CHOICE < 1 || ROLE_CHOICE > ${#ROLES[@]} )); then
  die "choix de rôle invalide: $ROLE_CHOICE"
fi
ROLE="${ROLES[$((ROLE_CHOICE - 1))]}"

generate_password() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 24
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_urlsafe(24))'
  elif [[ -r /dev/urandom ]]; then
    head -c 32 /dev/urandom | base64
  else
    die "aucune source cryptographique sûre disponible (openssl, python3 ou /dev/urandom requis)."
  fi
}

credentials_dir() {
  local candidate
  for candidate in \
    "${STUDIO_CREDENTIALS_DIR:-}" \
    "$HOME/Desktop" \
    "$HOME/OneDrive/Desktop" \
    "$HOME/Bureau" \
    "$HOME/OneDrive/Bureau" \
    "$HOME"; do
    if [[ -n "$candidate" && -d "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  printf '%s' "$HOME"
}

write_credentials_file() {
  local dir file
  dir="$(credentials_dir)"
  file="$dir/studi-os-credentials-${SAFE_EMAIL}-$(date +%Y%m%d-%H%M%S).txt"
  (
    umask 077
    {
      echo "Studi'OS — Identifiants de compte"
      echo "Généré le : $(date '+%Y-%m-%d %H:%M:%S')"
      echo ""
      echo "Compte"
      echo "──────"
      if [[ "$EXISTING" -eq 1 ]]; then
        echo "Email     : $EMAIL"
        echo "(rôle et mot de passe existants inchangés)"
      else
        echo "Nom       : $DISPLAY_NAME"
        echo "Email     : $EMAIL"
        echo "Rôle      : $ROLE"
      fi
      if [[ "$USER_CREATED" -eq 1 && "$PASSWORD_SET" -eq 1 ]]; then
        echo ""
        echo "Mot de passe dashboard"
        echo "──────────────────────"
        echo "$PASSWORD"
      fi
      if [[ "$MACHINE_CREATED" -eq 1 ]]; then
        echo ""
        echo "Machine"
        echo "───────"
        echo "Nom       : $MACHINE_NAME"
        echo "ID        : $MACHINE_ID"
        echo "Token     : $MACHINE_TOKEN"
      fi
      echo ""
      echo "SÉCURITÉ"
      echo "Fichier contenant des secrets : ne pas versionner, ne pas partager."
      echo "Enregistrez ces identifiants dans un gestionnaire de secrets,"
      echo "puis supprimez ce fichier."
    } > "$file"
  )
  chmod 600 "$file" 2>/dev/null || true
  printf '%s' "$file"
}

echo ""
echo "Mot de passe :"
echo "  1. Saisir manuellement"
echo "  2. Générer automatiquement"
read -rp "Choix [1] : " PW_CHOICE
PW_CHOICE="${PW_CHOICE:-1}"
PASSWORD_GENERATED=0
case "$PW_CHOICE" in
  2)
    PASSWORD="$(generate_password)"
    PASSWORD_GENERATED=1
    ;;
  1)
    while true; do
      read -rsp "Mot de passe : " PASSWORD
      echo ""
      read -rsp "Confirmer  : " PASSWORD_CONFIRM
      echo ""
      if [[ -n "$PASSWORD" && "$PASSWORD" == "$PASSWORD_CONFIRM" ]]; then
        break
      fi
      echo "Les mots de passe sont vides ou ne correspondent pas. Recommencez." >&2
    done
    unset PASSWORD_CONFIRM
    ;;
  *)
    die "choix de mot de passe invalide: $PW_CHOICE"
    ;;
esac

CREATE_MACHINE=0
MACHINE_NAME=""
read -rp "Créer une machine pour cet utilisateur ? [Y/n] : " MACHINE_ANSWER
case "${MACHINE_ANSWER:-Y}" in
  [Yy]*) CREATE_MACHINE=1 ;;
  *) CREATE_MACHINE=0 ;;
esac
if [[ "$CREATE_MACHINE" -eq 1 ]]; then
  read -rp "Nom de la machine : " MACHINE_NAME
  while [[ -z "${MACHINE_NAME// /}" ]]; do
    echo "Le nom de la machine ne doit pas être vide." >&2
    read -rp "Nom de la machine : " MACHINE_NAME
  done
fi

# --- Provisionnement -------------------------------------------------------

echo ""
echo "[1/3] Création de l'utilisateur..."
USER_CREATED=0
EXISTING=0
if run_admin user create --display-name "$DISPLAY_NAME" --email "$EMAIL" --role "$ROLE" </dev/null; then
  USER_CREATED=1
else
  rc=$?
  if [[ "$rc" -eq 2 ]]; then
    EXISTING=1
  else
    die "la création de l'utilisateur a échoué (code $rc).
       Aucun mot de passe ni machine n'a été créé. Vérifiez que la base est migrée
       (cd docker && docker compose run --rm api alembic upgrade head) puis réessayez."
  fi
fi

PASSWORD_SET=0
if [[ "$USER_CREATED" -eq 1 ]]; then
  echo "[2/3] Définition du mot de passe..."
  if printf '%s\n' "$PASSWORD" | run_admin set-password --email "$EMAIL" --password-stdin; then
    PASSWORD_SET=1
  else
    rc=$?
    echo "" >&2
    echo "⚠ ÉCHEC PARTIEL : l'utilisateur $EMAIL a bien été créé, mais la définition" >&2
    echo "  du mot de passe a échoué (code $rc). Aucune machine n'a été créée." >&2
    echo "  Reprenez sans risque de doublon avec :" >&2
    echo "    cd docker && printf '%s\\n' '<mot-de-passe>' | \\" >&2
    echo "      docker compose run --rm -T api python -m studio_api.admin_cli \\" >&2
    echo "      set-password --email '$EMAIL' --password-stdin" >&2
    exit 1
  fi
else
  echo "[2/3] Utilisateur $EMAIL déjà existant : rôle et mot de passe laissés intacts."
fi

MACHINE_CREATED=0
MACHINE_OUTPUT=""
if [[ "$CREATE_MACHINE" -eq 1 ]]; then
  echo "[3/3] Création de la machine '$MACHINE_NAME'..."
  if MACHINE_OUTPUT="$(run_admin machine create --owner-email "$EMAIL" --display-name "$MACHINE_NAME" </dev/null)"; then
    MACHINE_CREATED=1
    MACHINE_ID="$(printf '%s\n' "$MACHINE_OUTPUT" \
      | sed -n 's/^machine created: //p')"
    MACHINE_TOKEN="$(printf '%s\n' "$MACHINE_OUTPUT" \
      | sed -n 's/^token (store now, never shown again): //p')"
  else
    rc=$?
    echo "" >&2
    if [[ "$USER_CREATED" -eq 1 ]]; then
      echo "⚠ ÉCHEC PARTIEL : utilisateur et mot de passe en place, mais la création" >&2
    else
      echo "⚠ ÉCHEC PARTIEL : aucune modification de compte, mais la création" >&2
    fi
    echo "  de la machine '$MACHINE_NAME' a échoué (code $rc)." >&2
    if [[ -n "$MACHINE_OUTPUT" ]]; then
      printf '%s\n' "$MACHINE_OUTPUT" >&2
    fi
    echo "  Réessayez la machine seule avec :" >&2
    echo "    cd docker && docker compose run --rm api python -m studio_api.admin_cli \\" >&2
    echo "      machine create --owner-email '$EMAIL' --display-name '$MACHINE_NAME'" >&2
  fi
else
  echo "[3/3] Aucune machine demandée."
fi

# --- Affichage final -------------------------------------------------------

echo ""
if [[ "$EXISTING" -eq 1 ]]; then
  echo "• Utilisateur déjà existant (aucune modification)"
else
  echo "✓ Utilisateur créé"
  if [[ "$PASSWORD_SET" -eq 1 ]]; then
    echo "✓ Mot de passe configuré"
  fi
fi
if [[ "$MACHINE_CREATED" -eq 1 ]]; then
  echo "✓ Machine créée"
fi

echo ""
echo "Compte Studi'OS"
echo "────────────────────────────────"
if [[ "$EXISTING" -eq 1 ]]; then
  echo "Email     : $EMAIL"
  echo "(rôle et mot de passe existants inchangés)"
else
  echo "Nom       : $DISPLAY_NAME"
  echo "Email     : $EMAIL"
  echo "Rôle      : $ROLE"
fi
if [[ "$MACHINE_CREATED" -eq 1 ]]; then
  echo "Machine   : $MACHINE_NAME"
fi

if [[ "$PASSWORD_GENERATED" -eq 1 && "$PASSWORD_SET" -eq 1 ]]; then
  echo ""
  echo "Mot de passe généré"
  echo "────────────────────────────────"
  echo "$PASSWORD"
  echo "Conservez-le dans un gestionnaire de secrets."
fi

if [[ "$MACHINE_CREATED" -eq 1 ]]; then
  echo ""
  echo "Machine token"
  echo "────────────────────────────────"
  if [[ -n "$MACHINE_ID" ]]; then
    echo "ID machine : $MACHINE_ID"
  fi
  if [[ -n "$MACHINE_TOKEN" ]]; then
    echo "$MACHINE_TOKEN"
  else
    printf '%s\n' "$MACHINE_OUTPUT"
  fi
  echo ""
  echo "ATTENTION"
  echo "Ce token ne sera plus affiché par Studi'OS."
  echo "Conserve-le dans un gestionnaire de secrets approprié."
fi

echo ""
if [[ "$EXISTING" -eq 1 && "$MACHINE_CREATED" -eq 0 ]]; then
  echo "Rien d'autre à faire : l'utilisateur est inchangé."
fi

if [[ "$USER_CREATED" -eq 1 || "$MACHINE_CREATED" -eq 1 ]]; then
  CREDENTIALS_FILE="$(write_credentials_file)"
  echo ""
  echo "Identifiants enregistrés dans :"
  echo "  $CREDENTIALS_FILE"
  echo "(fichier local contenant des secrets — ne pas versionner)"
fi
