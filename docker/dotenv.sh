#!/usr/bin/env bash
# Safe .env loader for the docker/*.sh scripts.
# Reads KEY=VALUE lines literally (no execution, no expansion), like
# Read-DotEnv in docker/deploy-local.ps1 and `docker compose --env-file`.
# Values with spaces must be quoted in .env (see docker/.env.example).
#
# Usage: source "${SCRIPT_DIR}/dotenv.sh" && load_dotenv "${SCRIPT_DIR}/.env"
load_dotenv() {
  local env_file="${1:-./.env}"
  [[ -f "$env_file" ]] || {
    echo "load_dotenv: file not found: $env_file" >&2
    return 1
  }
  local line rest key value first last
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    rest="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$rest" ]] && continue
    [[ "$rest" == \#* ]] && continue
    if [[ "$rest" == export\ * ]]; then
      rest="${rest#export }"
      rest="${rest#"${rest%%[![:space:]]*}"}"
    fi
    [[ "$rest" == *=* ]] || continue
    key="${rest%%=*}"
    value="${rest#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ "${#value}" -ge 2 ]]; then
      first="${value:0:1}"
      last="${value: -1}"
      if [[ "$first" == '"' && "$last" == '"' ]] || [[ "$first" == "'" && "$last" == "'" ]]; then
        value="${value:1:-1}"
      fi
    fi
    printf -v "$key" '%s' "$value"
    export "$key"
  done <"$env_file"
  return 0
}
