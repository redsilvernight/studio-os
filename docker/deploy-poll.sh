#!/usr/bin/env bash
# Déploiement continu par polling de Studio OS sur le VPS OVH (DEC-0205).
# Équivalent Linux de deploy-poll.ps1 (Flo-laptop) : quand la pointe de
# deploy/ovh-vps change, sauvegarde PostgreSQL, construit api/mcp/dashboard,
# applique Alembic, recrée les services, recharge Caddy et attend /healthz.
# En cas d'échec, le code revient à la révision précédente ; les migrations
# ne sont jamais annulées. Lancé par studio-deploy-poll.timer (systemd).
# Usage : deploy-poll.sh [--force]
set -Eeuo pipefail

DEPLOY_DIR=${DEPLOY_DIR:-$HOME/studio-os-deploy}
BRANCH=${BRANCH:-deploy/ovh-vps}
REMOTE=${REMOTE:-origin}
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-docker}
STATE_DIR=${STATE_DIR:-$HOME/.local/state/studio-os-deploy}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}
KEEP_BACKUPS=${KEEP_BACKUPS:-14}
FORCE=0; [ "${1:-}" = "--force" ] && FORCE=1

mkdir -p "$STATE_DIR"
LOG="$STATE_DIR/deploy-$(date +%Y%m%d).log"
log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

[ -d "$DEPLOY_DIR/.git" ] || { log "pas un clone git : $DEPLOY_DIR"; exit 2; }
exec 9>"$STATE_DIR/deploy.lock"
flock -n 9 || { echo "déploiement déjà en cours"; exit 0; }

cd "$DEPLOY_DIR"
git fetch -q --prune "$REMOTE" "$BRANCH"
target=$(git rev-parse "$REMOTE/$BRANCH")
deployed=$(cat "$STATE_DIR/deployed.rev" 2>/dev/null || true)
failed=$(cat "$STATE_DIR/failed.rev" 2>/dev/null || true)
if [ "$FORCE" -eq 0 ]; then
  [ "$target" = "$deployed" ] && { echo "à jour : $target"; exit 0; }
  [ "$target" = "$failed" ] && { echo "$target a déjà échoué ; attente d'un nouveau commit"; exit 0; }
fi

prev=$(git rev-parse HEAD)
compose() { docker compose -f "$DEPLOY_DIR/docker/docker-compose.yml" "$@"; }
api_domain=$(grep -m1 '^API_DOMAIN=' "$DEPLOY_DIR/docker/.env" | cut -d= -f2-)

healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT))
  while [ $SECONDS -lt $deadline ]; do
    curl -fsS -m 5 --resolve "$api_domain:443:127.0.0.1" "https://$api_domain/healthz" >/dev/null 2>&1 && return 0
    sleep 5
  done
  return 1
}

rollout() {
  compose build api mcp dashboard
  compose run --rm --no-deps api alembic upgrade head
  compose up -d --no-deps api mcp dashboard
  compose up -d --no-deps caddy
  compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile
}

on_error() {
  trap - ERR
  log "ÉCHEC du déploiement de $target"
  echo "$target" > "$STATE_DIR/failed.rev"
  log "retour du code à $prev (migrations NON annulées)"
  git checkout -q --detach "$prev" && rollout >>"$LOG" 2>&1 || log "ROLLBACK EN ÉCHEC : intervention manuelle requise"
  exit 1
}
trap on_error ERR

log "déploiement de $target (code précédent $prev)"
mkdir -p "$DEPLOY_DIR/docker/backups"
backup="$DEPLOY_DIR/docker/backups/predeploy-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_user=$(grep -m1 '^POSTGRES_USER=' "$DEPLOY_DIR/docker/.env" | cut -d= -f2-)
pg_db=$(grep -m1 '^POSTGRES_DB=' "$DEPLOY_DIR/docker/.env" | cut -d= -f2-)
compose exec -T postgres pg_dump -U "$pg_user" -d "$pg_db" -Fc > "$backup"
log "sauvegarde PostgreSQL : $backup"
ls -1t "$DEPLOY_DIR"/docker/backups/predeploy-*.dump | tail -n +$((KEEP_BACKUPS + 1)) | xargs -r rm -f

git checkout -q --detach "$target"
rollout >>"$LOG" 2>&1
healthy || false
trap - ERR
echo "$target" > "$STATE_DIR/deployed.rev"
rm -f "$STATE_DIR/failed.rev"
log "déployé : $target"
