#!/usr/bin/env bash
# Revoke a machine credential.
# Usage: ./revoke-machine.sh <machine_id>
set -euo pipefail
export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/dotenv.sh"
load_dotenv "${SCRIPT_DIR}/.env"

MACHINE_ID="${1:?usage: revoke-machine.sh <machine_id>}"

docker compose run --rm api python -m studio_api.admin_cli machine revoke "$MACHINE_ID"
