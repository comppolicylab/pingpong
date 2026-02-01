#!/bin/bash

set -e

PREFIX="${1:-}"
AUTHZ_API="https://localhost:8080"
AUTHZ_TOKEN="devkey"

authz_api() {
  curl -sk -H "Authorization: Bearer ${AUTHZ_TOKEN}" "$@"
}

# ====== Find matching databases ======
# Match pingpong_* (excludes main 'pingpong' database)
MATCHING_DBS=()
if docker ps --format '{{.Names}}' | grep -Fxq "pingpong-db"; then
  DB_PATTERN="pingpong_${PREFIX}%"
  while IFS= read -r db; do
    [[ -n "${db}" ]] && MATCHING_DBS+=("${db}")
  done < <(docker exec pingpong-db psql -Upingpong -tAc "SELECT datname FROM pg_database WHERE datname LIKE '${DB_PATTERN}'")
else
  echo "Warning: pingpong-db container not running, cannot list databases."
fi

# ====== Find matching authz stores ======
# Match pingpong_* (excludes main 'pingpong' store)
STORE_PREFIX="pingpong_${PREFIX}"
MATCHING_STORES=()
if docker ps --format '{{.Names}}' | grep -Fxq "pingpong-authz"; then
  STORES_JSON=$(authz_api "${AUTHZ_API}/stores" 2>/dev/null || echo '{"stores":[]}')
  while IFS= read -r store_info; do
    [[ -n "${store_info}" ]] && MATCHING_STORES+=("${store_info}")
  done < <(echo "${STORES_JSON}" | jq -r '.stores[] | select(.name | startswith("'"${STORE_PREFIX}"'")) | "\(.id):\(.name)"')
else
  echo "Warning: pingpong-authz container not running, cannot list authz stores."
fi

# ====== Show what will be removed ======
if [[ -n "${PREFIX}" ]]; then
  echo "Resources matching 'pingpong_${PREFIX}*':"
else
  echo "All worktree resources (pingpong_*):"
fi
echo ""

if [[ ${#MATCHING_DBS[@]} -eq 0 ]]; then
  echo "Databases: (none found)"
else
  echo "Databases:"
  for db in "${MATCHING_DBS[@]}"; do
    echo "  - ${db}"
  done
fi

echo ""

if [[ ${#MATCHING_STORES[@]} -eq 0 ]]; then
  echo "Authz stores: (none found)"
else
  echo "Authz stores:"
  for store in "${MATCHING_STORES[@]}"; do
    store_name="${store#*:}"
    echo "  - ${store_name}"
  done
fi

echo ""

if [[ ${#MATCHING_DBS[@]} -eq 0 && ${#MATCHING_STORES[@]} -eq 0 ]]; then
  echo "No resources found matching prefix."
  exit 0
fi

# ====== Confirm removal ======
read -p "Are you sure you want to remove these resources? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

# ====== Remove databases ======
if [[ ${#MATCHING_DBS[@]} -gt 0 ]]; then
  echo ""
  echo "Removing databases..."
  for db in "${MATCHING_DBS[@]}"; do
    echo "  Dropping ${db}..."
    docker exec pingpong-db psql -Upingpong -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${db}' AND pid <> pg_backend_pid();" > /dev/null 2>&1 || true
    docker exec pingpong-db psql -Upingpong -c "DROP DATABASE \"${db}\";"
  done
  echo "Databases removed."
fi

# ====== Remove authz stores ======
if [[ ${#MATCHING_STORES[@]} -gt 0 ]]; then
  echo ""
  echo "Removing authz stores..."
  for store in "${MATCHING_STORES[@]}"; do
    store_id="${store%%:*}"
    store_name="${store#*:}"
    echo "  Deleting ${store_name} (${store_id})..."
    RESULT=$(authz_api -X DELETE "${AUTHZ_API}/stores/${store_id}")
    if echo "${RESULT}" | jq -e '.code' > /dev/null 2>&1; then
      echo "    Warning: Failed to delete: ${RESULT}"
    fi
  done
  echo "Authz stores removed."
fi

echo ""
echo "Cleanup complete."
