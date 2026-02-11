#!/bin/bash

set -e

if [[ -z "${1:-}" ]]; then
  echo "Usage: $0 <worktree-name>" >&2
  exit 1
fi

# Validate worktree name: allow alphanumeric, hyphens, underscores, and slashes for nested branches
if [[ ! "$1" =~ ^[a-zA-Z0-9][a-zA-Z0-9_/-]*$ ]]; then
  echo "ERROR: Invalid worktree name '$1'" >&2
  echo "Names must start with alphanumeric and contain only letters, numbers, hyphens, underscores, or slashes." >&2
  exit 1
fi

# Reject path traversal attempts and consecutive slashes
if [[ "$1" == *".."* ]] || [[ "$1" == *"//"* ]] || [[ "$1" == */ ]]; then
  echo "ERROR: Invalid worktree name '$1' (contains '..' or invalid slashes)" >&2
  exit 1
fi

WORKTREE_NAME="$1"
WORKTREE_ROOT="../pingpong-worktrees"
PORTS_FILE="${WORKTREE_ROOT}/.worktree-ports.json"
PORTS_LOCKFILE="${WORKTREE_ROOT}/.worktree-ports.lock"

# Lockfile functions shared with create-worktree.sh
acquire_ports_lock() {
  mkdir -p "${WORKTREE_ROOT}"
  if command -v flock >/dev/null 2>&1; then
    exec 9>"${PORTS_LOCKFILE}"
    if ! flock -w 30 9; then
      echo "ERROR: Could not acquire port reservation lock after 30 seconds." >&2
      echo "Another worktree script may be running. If not, remove ${PORTS_LOCKFILE}" >&2
      return 1
    fi
  else
    local max_attempts=60
    local attempt=0
    while ! mkdir "${PORTS_LOCKFILE}.d" 2>/dev/null; do
      attempt=$((attempt + 1))
      if (( attempt >= max_attempts )); then
        echo "ERROR: Could not acquire port reservation lock after 30 seconds." >&2
        echo "Another worktree script may be running. If not, remove ${PORTS_LOCKFILE}.d" >&2
        return 1
      fi
      sleep 0.5
    done
    echo $$ > "${PORTS_LOCKFILE}.d/pid"
  fi
}

release_ports_lock() {
  if command -v flock >/dev/null 2>&1; then
    exec 9>&- 2>/dev/null || true
  else
    rm -rf "${PORTS_LOCKFILE}.d" 2>/dev/null || true
  fi
}

sanitize_db_suffix() {
  local raw="$1"
  local lower
  local cleaned
  local max_len=40

  lower="$(printf '%s' "${raw}" | tr '[:upper:]' '[:lower:]')"
  cleaned="$(printf '%s' "${lower}" | sed -E 's/[^a-z0-9_]+/_/g; s/^_+//; s/_+$//')"

  if [[ -z "${cleaned}" ]]; then
    cleaned="branch"
  fi

  if [[ "${cleaned}" =~ ^[0-9] ]]; then
    cleaned="b_${cleaned}"
  fi

  cleaned="${cleaned:0:${max_len}}"
  cleaned="$(printf '%s' "${cleaned}" | sed -E 's/_+$//')"

  if [[ -z "${cleaned}" ]]; then
    cleaned="branch"
  fi

  echo "${cleaned}"
}

DB_SUFFIX="$(sanitize_db_suffix "${WORKTREE_NAME}")"
SANITIZED_WORKTREE_PATH="${WORKTREE_ROOT}/${DB_SUFFIX}"
LEGACY_WORKTREE_PATH="${WORKTREE_ROOT}/${WORKTREE_NAME}"
DB_NAME="pingpong_${DB_SUFFIX}"
AUTHZ_STORE_NAME="pingpong_${DB_SUFFIX}"

# Parse authz settings from config file
CONFIG_FILE="${CONFIG_FILE:-config.local.toml}"
if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "ERROR: Config file not found: ${CONFIG_FILE}" >&2
  exit 1
fi

# Extract values from [authz] section of TOML config
get_toml_value() {
  local file="$1"
  local section="$2"
  local key="$3"
  local default="$4"
  # Find section, then extract key value (handles quotes)
  awk -v section="[$section]" -v key="$key" '
    $0 == section { in_section=1; next }
    /^\[/ { in_section=0 }
    in_section && $1 == key && $2 == "=" {
      val=$3
      for(i=4;i<=NF;i++) val=val" "$i
      gsub(/^["'\'']|["'\'']$/, "", val)
      print val
      exit
    }
  ' "$file" || echo "$default"
}

AUTHZ_SCHEME="$(get_toml_value "${CONFIG_FILE}" "authz" "scheme" "https")"
AUTHZ_HOST="$(get_toml_value "${CONFIG_FILE}" "authz" "host" "localhost")"
AUTHZ_TOKEN="$(get_toml_value "${CONFIG_FILE}" "authz" "key" "devkey")"

# Get authz port from docker-compose.yml (first port in authz service ports mapping)
DOCKER_COMPOSE_FILE="${DOCKER_COMPOSE_FILE:-docker-compose.yml}"
if [[ -f "${DOCKER_COMPOSE_FILE}" ]]; then
  AUTHZ_PORT="$(awk '/^  authz:/,/^  [a-z]/' "${DOCKER_COMPOSE_FILE}" | grep -E '^\s+ports:' | grep -oE '"[0-9]+:' | head -1 | tr -d '":' || echo "8080")"
  [[ -z "${AUTHZ_PORT}" ]] && AUTHZ_PORT="8080"
else
  echo "Warning: Docker compose file not found: ${DOCKER_COMPOSE_FILE}, using default authz port 8080" >&2
  AUTHZ_PORT="8080"
fi
AUTHZ_API="${AUTHZ_SCHEME}://${AUTHZ_HOST}:${AUTHZ_PORT}"

authz_api() {
  curl -sk -H "Authorization: Bearer ${AUTHZ_TOKEN}" "$@"
}

get_store_id_by_name() {
  local name="$1"
  authz_api "${AUTHZ_API}/stores" | jq -r --arg name "${name}" '.stores[] | select(.name == $name) | .id'
}

get_worktree_path_for_branch() {
  local branch_name="$1"
  git worktree list --porcelain | awk -v branch="refs/heads/${branch_name}" '
    $1 == "worktree" {
      path = $0
      sub(/^worktree /, "", path)
    }
    $1 == "branch" && $2 == branch {
      print path
      exit
    }
  '
}

REGISTERED_WORKTREE_PATH="$(get_worktree_path_for_branch "${WORKTREE_NAME}")"
if [[ -n "${REGISTERED_WORKTREE_PATH}" ]]; then
  WORKTREE_PATH="${REGISTERED_WORKTREE_PATH}"
elif [[ -e "${SANITIZED_WORKTREE_PATH}" ]]; then
  WORKTREE_PATH="${SANITIZED_WORKTREE_PATH}"
elif [[ -e "${LEGACY_WORKTREE_PATH}" ]]; then
  WORKTREE_PATH="${LEGACY_WORKTREE_PATH}"
else
  WORKTREE_PATH="${SANITIZED_WORKTREE_PATH}"
fi

echo "Removing worktree: ${WORKTREE_NAME}"
echo "  Database: ${DB_NAME}"
echo "  Authz store: ${AUTHZ_STORE_NAME}"
echo "  Worktree path: ${WORKTREE_PATH}"
echo ""

# Confirm removal
read -p "Are you sure you want to remove these resources? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

# ====== 1. Remove git worktree ======
TARGET_WORKTREE_PATH="${REGISTERED_WORKTREE_PATH:-${WORKTREE_PATH}}"
if [[ -n "${REGISTERED_WORKTREE_PATH}" ]] || [[ -e "${TARGET_WORKTREE_PATH}" ]]; then
  echo "Removing git worktree..."
  GIT_ERROR=$(git worktree remove --force "${TARGET_WORKTREE_PATH}" 2>&1) || {
    echo "Warning: Failed to remove worktree via git: ${GIT_ERROR}"
    if [[ -e "${TARGET_WORKTREE_PATH}" ]]; then
      echo "Removing directory manually..."
      rm -rf "${TARGET_WORKTREE_PATH}"
    else
      echo "Worktree path not found on disk; pruning stale worktree metadata..."
    fi
    git worktree prune
  }
  echo "Worktree removed."
else
  echo "Worktree path does not exist and branch is not in git worktree list, skipping..."
fi

# ====== 2. Remove database ======
if docker ps --format '{{.Names}}' | grep -Fxq "pingpong-db"; then
  if docker exec pingpong-db psql -Upingpong -tAc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | grep -q 1; then
    echo "Removing database ${DB_NAME}..."
    # Terminate connections to the database
    docker exec pingpong-db psql -Upingpong -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();" > /dev/null 2>&1 || true
    docker exec pingpong-db psql -Upingpong -c "DROP DATABASE ${DB_NAME};"
    echo "Database removed."
  else
    echo "Database ${DB_NAME} does not exist, skipping..."
  fi
else
  echo "pingpong-db container not running, skipping database removal..."
fi

# ====== 3. Remove authz store ======
if docker ps --format '{{.Names}}' | grep -Fxq "pingpong-authz"; then
  STORE_ID="$(get_store_id_by_name "${AUTHZ_STORE_NAME}")"
  if [[ -n "${STORE_ID}" ]]; then
    echo "Removing authz store ${AUTHZ_STORE_NAME} (${STORE_ID})..."
    RESULT=$(authz_api -X DELETE "${AUTHZ_API}/stores/${STORE_ID}")
    if echo "${RESULT}" | jq -e '.code' > /dev/null 2>&1; then
      echo "Warning: Failed to delete authz store: ${RESULT}"
    else
      echo "Authz store removed."
    fi
  else
    echo "Authz store ${AUTHZ_STORE_NAME} does not exist, skipping..."
  fi
else
  echo "pingpong-authz container not running, skipping authz store removal..."
fi

# ====== 4. Remove git branch ======
BRANCH_NAME="${WORKTREE_NAME}"
if git show-ref --verify --quiet "refs/heads/${BRANCH_NAME}"; then
  REMAINING_WORKTREE_PATH="$(get_worktree_path_for_branch "${BRANCH_NAME}")"
  if [[ -n "${REMAINING_WORKTREE_PATH}" ]]; then
    echo "Warning: Branch ${BRANCH_NAME} is still checked out at ${REMAINING_WORKTREE_PATH}; skipping branch deletion."
  else
    echo "Removing git branch ${BRANCH_NAME}..."
    git branch -D "${BRANCH_NAME}"
    echo "Branch removed."
  fi
else
  echo "Branch ${BRANCH_NAME} does not exist, skipping..."
fi

echo ""
echo "Cleanup complete for ${WORKTREE_NAME}"

# Release port reservation (with lock to prevent race conditions)
if [[ -f "${PORTS_FILE}" ]]; then
  if acquire_ports_lock; then
    tmp_ports="$(mktemp)"
    if jq --arg name "${WORKTREE_NAME}" 'del(.[$name])' "${PORTS_FILE}" > "${tmp_ports}"; then
      mv "${tmp_ports}" "${PORTS_FILE}"
      echo "Released reserved ports for ${WORKTREE_NAME}."
    else
      rm -f "${tmp_ports}"
      echo "Warning: Failed to update ${PORTS_FILE} when releasing ports." >&2
    fi
    release_ports_lock
  else
    echo "Warning: Could not acquire lock to release ports. Manual cleanup may be needed." >&2
  fi
fi
