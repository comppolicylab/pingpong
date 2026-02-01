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
WORKTREE_PATH="${WORKTREE_ROOT}/${WORKTREE_NAME}"
AUTHZ_API="https://localhost:8080"
AUTHZ_TOKEN="devkey"

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
DB_NAME="pingpong_${DB_SUFFIX}"
AUTHZ_STORE_NAME="pingpong_${DB_SUFFIX}"

authz_api() {
  curl -sk -H "Authorization: Bearer ${AUTHZ_TOKEN}" "$@"
}

get_store_id_by_name() {
  local name="$1"
  authz_api "${AUTHZ_API}/stores" | jq -r --arg name "${name}" '.stores[] | select(.name == $name) | .id'
}

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
if [[ -e "${WORKTREE_PATH}" ]]; then
  echo "Removing git worktree..."
  GIT_ERROR=$(git worktree remove --force "${WORKTREE_PATH}" 2>&1) || {
    echo "Warning: Failed to remove worktree via git: ${GIT_ERROR}"
    echo "Removing directory manually..."
    rm -rf "${WORKTREE_PATH}"
    git worktree prune
  }
  echo "Worktree removed."
else
  echo "Worktree path does not exist, skipping..."
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
  echo "Removing git branch ${BRANCH_NAME}..."
  git branch -D "${BRANCH_NAME}"
  echo "Branch removed."
else
  echo "Branch ${BRANCH_NAME} does not exist, skipping..."
fi

echo ""
echo "Cleanup complete for ${WORKTREE_NAME}"
