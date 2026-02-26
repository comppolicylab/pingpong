#!/bin/bash

set -e

# Preflight checks for required tools
REQUIRED_TOOLS=(curl docker git jq pnpm uv python)
MISSING_TOOLS=()

for tool in "${REQUIRED_TOOLS[@]}"; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    MISSING_TOOLS+=("${tool}")
  fi
done

if [[ ${#MISSING_TOOLS[@]} -gt 0 ]]; then
  echo "ERROR: Required tools not found: ${MISSING_TOOLS[*]}" >&2
  echo "Please install the missing tools and try again." >&2
  exit 1
fi

if [[ -z "${1:-}" ]]; then
  echo "Usage: $0 <branch-and-worktree-name>" >&2
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

BRANCH_NAME="$1"
WORKTREE_NAME="$1"
WORKTREE_ROOT="../pingpong-worktrees"
PORTS_FILE="${WORKTREE_ROOT}/.worktree-ports.json"

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

DB_SUFFIX="$(sanitize_db_suffix "${BRANCH_NAME}")"
WORKTREE_PATH="${WORKTREE_ROOT}/${DB_SUFFIX}"
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
  echo "WARNING: Docker compose file not found: ${DOCKER_COMPOSE_FILE}. Using default authz port 8080." >&2
  AUTHZ_PORT="8080"
fi
AUTHZ_API="${AUTHZ_SCHEME}://${AUTHZ_HOST}:${AUTHZ_PORT}"

# Track created resources for cleanup on failure
CREATED_DB=false
CREATED_AUTHZ_STORE=false
CREATED_AUTHZ_STORE_ID=""
CREATED_WORKTREE=false
CREATED_BRANCH=false
CREATED_PORTS=false

cleanup_on_failure() {
  local exit_code=$?
  if [[ ${exit_code} -eq 0 ]]; then
    return 0
  fi

  echo "" >&2
  echo "ERROR: Script failed. Cleaning up partially created resources..." >&2

  # Clean up in reverse order of creation
  if [[ "${CREATED_WORKTREE}" == "true" ]]; then
    echo "Removing worktree ${WORKTREE_PATH}..." >&2
    git worktree remove --force "${WORKTREE_PATH}" 2>/dev/null || rm -rf "${WORKTREE_PATH}"
    git worktree prune 2>/dev/null || true
  fi

  if [[ "${CREATED_BRANCH}" == "true" ]]; then
    echo "Removing branch ${BRANCH_NAME}..." >&2
    git branch -D "${BRANCH_NAME}" 2>/dev/null || true
  fi

  if [[ "${CREATED_AUTHZ_STORE}" == "true" && -n "${CREATED_AUTHZ_STORE_ID}" ]]; then
    echo "Removing authz store ${AUTHZ_STORE_NAME}..." >&2
    curl -sk -X DELETE -H "Authorization: Bearer ${AUTHZ_TOKEN}" "${AUTHZ_API}/stores/${CREATED_AUTHZ_STORE_ID}" 2>/dev/null || true
  fi

  if [[ "${CREATED_DB}" == "true" ]]; then
    echo "Removing database ${DB_NAME}..." >&2
    docker exec pingpong-db psql -Upingpong -c "DROP DATABASE IF EXISTS ${DB_NAME};" 2>/dev/null || true
  fi

  if [[ "${CREATED_PORTS}" == "true" ]]; then
    if [[ -f "${PORTS_FILE}" ]]; then
      if acquire_ports_lock; then
        tmp_ports="$(mktemp)"
        jq --arg name "${WORKTREE_NAME}" 'del(.[$name])' "${PORTS_FILE}" > "${tmp_ports}" \
          && mv "${tmp_ports}" "${PORTS_FILE}" || rm -f "${tmp_ports}"
        release_ports_lock
      else
        echo "WARNING: Could not acquire port lock during cleanup; skipping port reservation cleanup." >&2
      fi
    fi
  fi

  echo "Cleanup complete." >&2
  exit ${exit_code}
}

trap cleanup_on_failure EXIT

authz_api() {
  curl -sk -H "Authorization: Bearer ${AUTHZ_TOKEN}" "$@"
}

get_store_id_by_name() {
  local name="$1"
  authz_api "${AUTHZ_API}/stores" | jq -r --arg name "${name}" '.stores[] | select(.name == $name) | .id'
}

ensure_container_running() {
  local container_name="$1"
  local max_attempts=30
  local attempt=1

  if ! docker ps -a --format '{{.Names}}' | grep -Fxq "${container_name}"; then
    echo "${container_name} container not found. Please run ./start-dev-docker.sh first." >&2
    exit 1
  fi

  if ! docker ps --format '{{.Names}}' | grep -Fxq "${container_name}"; then
    echo "Starting ${container_name}..."
    docker start "${container_name}" >/dev/null
  fi

  while true; do
    if [[ "$(docker inspect -f '{{.State.Running}}' "${container_name}" 2>/dev/null)" == "true" ]]; then
      break
    fi
    if (( attempt >= max_attempts )); then
      echo "${container_name} failed to start. Please run ./start-dev-docker.sh first." >&2
      exit 1
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
}

wait_for_db_ready() {
  local max_attempts=30
  local attempt=1

  until docker exec pingpong-db pg_isready >/dev/null 2>&1; do
    if (( attempt >= max_attempts )); then
      echo "Database is not ready. Please run ./start-dev-docker.sh first." >&2
      exit 1
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
}

wait_for_authz_ready() {
  local max_attempts=30
  local attempt=1

  until docker exec pingpong-authz /usr/local/bin/grpc_health_probe -addr=authz:8081 >/dev/null 2>&1; do
    if (( attempt >= max_attempts )); then
      echo "Authz server is not ready. Please run ./start-dev-docker.sh first." >&2
      exit 1
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
}

ensure_container_running "pingpong-db"
wait_for_db_ready

if docker exec pingpong-db psql -Upingpong -tAc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | grep -q 1; then
  echo "ERROR: Database ${DB_NAME} already exists." >&2
  exit 1
fi

if docker ps -a --format '{{.Names}}' | grep -Fxq "pingpong-authz"; then
  if docker ps --format '{{.Names}}' | grep -Fxq "pingpong-authz"; then
    echo "Stopping pingpong-authz..."
    docker stop pingpong-authz >/dev/null
  fi
fi

echo "Cloning database pingpong -> ${DB_NAME}..."
docker exec pingpong-db psql -Upingpong -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'pingpong' AND pid <> pg_backend_pid();"

# Wait for connections to fully terminate before cloning
clone_attempt=0
max_clone_attempts=10
while ! docker exec pingpong-db psql -Upingpong -c "CREATE DATABASE ${DB_NAME} WITH TEMPLATE pingpong;" 2>/dev/null; do
  clone_attempt=$((clone_attempt + 1))
  if (( clone_attempt >= max_clone_attempts )); then
    echo "ERROR: Failed to clone database after ${max_clone_attempts} attempts." >&2
    exit 1
  fi
  echo "Waiting for connections to close (attempt ${clone_attempt}/${max_clone_attempts})..."
  sleep 0.5
done
CREATED_DB=true

ensure_container_running "pingpong-authz"
wait_for_authz_ready

# Check if authz store already exists
if authz_api "${AUTHZ_API}/stores" | grep -q "\"name\":\"${AUTHZ_STORE_NAME}\""; then
  echo "ERROR: Authz store ${AUTHZ_STORE_NAME} already exists." >&2
  exit 1
fi

# Get source store ID
SOURCE_STORE_ID="$(get_store_id_by_name "pingpong")"
if [[ -z "${SOURCE_STORE_ID}" ]]; then
  echo "ERROR: Source authz store 'pingpong' not found." >&2
  exit 1
fi

# Create new store
NEW_STORE_ID="$(authz_api -X POST "${AUTHZ_API}/stores" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${AUTHZ_STORE_NAME}\"}" | grep -o '"id":"[^"]*"' | head -1 | sed 's/"id":"\([^"]*\)"/\1/')"

if [[ -z "${NEW_STORE_ID}" ]]; then
  echo "ERROR: Failed to create authz store ${AUTHZ_STORE_NAME}." >&2
  exit 1
fi
CREATED_AUTHZ_STORE=true
CREATED_AUTHZ_STORE_ID="${NEW_STORE_ID}"

echo "Cloning authz store pingpong -> ${AUTHZ_STORE_NAME}..."

WORKDIR="$(mktemp -d)"
MODEL_FILE="${WORKDIR}/model.json"
TUPLES_FILE="${WORKDIR}/tuples.json"

SOURCE_READ_URL="${AUTHZ_API}/stores/${SOURCE_STORE_ID}/read"
DEST_WRITE_URL="${AUTHZ_API}/stores/${NEW_STORE_ID}/write"
SOURCE_MODELS_URL="${AUTHZ_API}/stores/${SOURCE_STORE_ID}/authorization-models"
DEST_MODELS_URL="${AUTHZ_API}/stores/${NEW_STORE_ID}/authorization-models"

AUTH_HEADER="Authorization: Bearer ${AUTHZ_TOKEN}"
JSON_HEADER="Content-Type: application/json"

# ====== 1. Copy latest authorization model ======
echo "Fetching latest authorization model from source store..."

curl -sk \
  -H "${AUTH_HEADER}" \
  "${SOURCE_MODELS_URL}" \
| jq '.authorization_models | sort_by(.created_at) | last' \
> "${MODEL_FILE}"

echo "Writing authorization model to destination store..."

DEST_MODEL_ID=$(
  curl -sk -X POST \
    -H "${AUTH_HEADER}" \
    -H "${JSON_HEADER}" \
    -d @"${MODEL_FILE}" \
    "${DEST_MODELS_URL}" \
  | jq -r '.authorization_model_id'
)

# ====== 2. Read all tuples from source store ======
echo "Reading tuples from source store..."

PAGE_SIZE=100
WRITE_BATCH_SIZE=100
PAGE_TOKEN=""
> "${TUPLES_FILE}"

while true; do
  if [[ -z "${PAGE_TOKEN}" ]]; then
    BODY="{\"page_size\": ${PAGE_SIZE}}"
  else
    BODY="{\"page_size\": ${PAGE_SIZE}, \"continuation_token\": \"${PAGE_TOKEN}\"}"
  fi

  RESPONSE=$(curl -sk -X POST \
    -H "${AUTH_HEADER}" \
    -H "${JSON_HEADER}" \
    -d "${BODY}" \
    "${SOURCE_READ_URL}")

  echo "${RESPONSE}" | jq -c '.tuples[]' >> "${TUPLES_FILE}"

  PAGE_TOKEN=$(echo "${RESPONSE}" | jq -r '.continuation_token')

  if [[ "${PAGE_TOKEN}" == "null" || -z "${PAGE_TOKEN}" ]]; then
    break
  fi
done

TUPLE_COUNT=$(wc -l < "${TUPLES_FILE}" | tr -d ' ')
echo "Fetched ${TUPLE_COUNT} tuples."

# ====== 3. Write tuples to destination store (batched) ======
echo "Writing tuples to destination store..."

# Transform tuples: extract .key from each tuple, remove null conditions, batch them, format for write API
# Input: [{key: {user, relation, object, condition}, timestamp}, ...]
# Output: {writes: {tuple_keys: [{user, relation, object}, ...]}}
JQ_BATCH_FILTER="[.[].key | {user, relation, object} + (if .condition then {condition} else {} end)] | . as \$keys | range(0; length; $WRITE_BATCH_SIZE) | {writes: {tuple_keys: \$keys[. : . + $WRITE_BATCH_SIZE]}}"

# Save batches to temp file to avoid subshell variable scope issues
BATCHES_FILE="${WORKDIR}/batches.json"
jq -s '.' "${TUPLES_FILE}" | jq -c "$JQ_BATCH_FILTER" > "${BATCHES_FILE}"

EXPECTED_BATCHES=$(( (TUPLE_COUNT + WRITE_BATCH_SIZE - 1) / WRITE_BATCH_SIZE ))
ACTUAL_BATCHES=$(wc -l < "${BATCHES_FILE}" | tr -d ' ')

BATCH_NUM=0
while read -r BATCH; do
    BATCH_NUM=$((BATCH_NUM + 1))
    RESULT=$(curl -sk -X POST \
      -H "Authorization: Bearer ${AUTHZ_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "${BATCH}" \
      "${DEST_WRITE_URL}")

    # Check for errors
    if echo "${RESULT}" | jq -e '.code' > /dev/null 2>&1; then
      echo "ERROR writing batch ${BATCH_NUM}: ${RESULT}" >&2
      exit 1
    fi
done < "${BATCHES_FILE}"

echo "Tuple copy complete."

# ====== 4. Verify tuple count in destination store ======
echo "Verifying tuple count in destination store..."

DEST_READ_URL="${AUTHZ_API}/stores/${NEW_STORE_ID}/read"
DEST_TUPLES_FILE="${WORKDIR}/dest_tuples.json"
DEST_PAGE_TOKEN=""
> "${DEST_TUPLES_FILE}"

while true; do
  if [[ -z "${DEST_PAGE_TOKEN}" ]]; then
    BODY="{\"page_size\": ${PAGE_SIZE}}"
  else
    BODY="{\"page_size\": ${PAGE_SIZE}, \"continuation_token\": \"${DEST_PAGE_TOKEN}\"}"
  fi

  RESPONSE=$(curl -sk -X POST \
    -H "${AUTH_HEADER}" \
    -H "${JSON_HEADER}" \
    -d "${BODY}" \
    "${DEST_READ_URL}")

  echo "${RESPONSE}" | jq -c '.tuples[]' >> "${DEST_TUPLES_FILE}"

  DEST_PAGE_TOKEN=$(echo "${RESPONSE}" | jq -r '.continuation_token')

  if [[ "${DEST_PAGE_TOKEN}" == "null" || -z "${DEST_PAGE_TOKEN}" ]]; then
    break
  fi
done

DEST_TUPLE_COUNT=$(wc -l < "${DEST_TUPLES_FILE}" | tr -d ' ')

echo "Source tuples: ${TUPLE_COUNT}, Destination tuples: ${DEST_TUPLE_COUNT}"

if [[ "${TUPLE_COUNT}" -ne "${DEST_TUPLE_COUNT}" ]]; then
  echo "ERROR: Tuple count mismatch! Expected ${TUPLE_COUNT}, got ${DEST_TUPLE_COUNT}" >&2
  echo "Source tuples saved to: ${TUPLES_FILE}"
  echo "Destination tuples saved to: ${DEST_TUPLES_FILE}"
  echo "Batches file saved to: ${BATCHES_FILE}"
  echo "To compare: diff <(jq -c '.key' ${TUPLES_FILE} | sort) <(jq -c '.key' ${DEST_TUPLES_FILE} | sort)"
  exit 1
fi

echo "Tuple verification passed."

# ====== Cleanup ======
rm -rf "${WORKDIR}"

echo "Created authz store ${AUTHZ_STORE_NAME} (${NEW_STORE_ID})"

if [[ -e "${WORKTREE_PATH}" ]]; then
  echo "ERROR: Worktree path already exists: ${WORKTREE_PATH}" >&2
  exit 1
fi

mkdir -p "${WORKTREE_ROOT}"

if git show-ref --verify --quiet "refs/heads/${BRANCH_NAME}"; then
  git worktree add "${WORKTREE_PATH}" "${BRANCH_NAME}"
  CREATED_WORKTREE=true
else
  git worktree add -b "${BRANCH_NAME}" "${WORKTREE_PATH}" main
  CREATED_WORKTREE=true
  CREATED_BRANCH=true
fi

copy_if_exists() {
  local source="$1"
  local normalized="${source%/}"

  if [[ ! -e "${normalized}" ]]; then
    return 0
  fi

  if command -v rsync >/dev/null 2>&1; then
    rsync -a "${normalized}" "${WORKTREE_PATH}/"
  else
    cp -R "${normalized}" "${WORKTREE_PATH}/"
  fi
}

copy_if_exists ".vscode/"
copy_if_exists "local_exports/"
copy_if_exists ".claude/"
copy_if_exists "config.dev.toml"
copy_if_exists "config.local.toml"

ensure_ports_file() {
  mkdir -p "${WORKTREE_ROOT}"
  if [[ ! -f "${PORTS_FILE}" ]]; then
    echo '{}' > "${PORTS_FILE}"
  fi
}

# Lockfile for port reservation to prevent race conditions
PORTS_LOCKFILE="${WORKTREE_ROOT}/.worktree-ports.lock"

acquire_ports_lock() {
  mkdir -p "${WORKTREE_ROOT}"
  # Use flock if available, otherwise fall back to mkdir-based locking
  if command -v flock >/dev/null 2>&1; then
    exec 9>"${PORTS_LOCKFILE}"
    if ! flock -w 30 9; then
      echo "ERROR: Could not acquire port reservation lock after 30 seconds." >&2
      echo "Another create-worktree.sh may be running. If not, remove ${PORTS_LOCKFILE}" >&2
      return 1
    fi
  else
    # Fallback: mkdir-based locking (atomic on POSIX)
    local max_attempts=60
    local attempt=0
    while ! mkdir "${PORTS_LOCKFILE}.d" 2>/dev/null; do
      attempt=$((attempt + 1))
      if (( attempt >= max_attempts )); then
        echo "ERROR: Could not acquire port reservation lock after 30 seconds." >&2
        echo "Another create-worktree.sh may be running. If not, remove ${PORTS_LOCKFILE}.d" >&2
        return 1
      fi
      sleep 0.5
    done
    # Store PID for debugging
    echo $$ > "${PORTS_LOCKFILE}.d/pid"
  fi
}

release_ports_lock() {
  if command -v flock >/dev/null 2>&1; then
    # flock is released automatically when fd 9 is closed
    exec 9>&-
  else
    rm -rf "${PORTS_LOCKFILE}.d" 2>/dev/null || true
  fi
}

get_worktree_path_for_branch() {
  local branch_name="$1"
  git worktree list --porcelain 2>/dev/null | awk -v branch="refs/heads/${branch_name}" '
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

# Clean up stale port reservations for non-existent worktrees
cleanup_stale_reservations() {
  ensure_ports_file
  if [[ ! -f "${PORTS_FILE}" ]]; then
    return 0
  fi

  local tmp_ports stale_count=0
  local worktrees
  worktrees=$(jq -r 'keys[]' "${PORTS_FILE}" 2>/dev/null) || return 0

  for worktree in ${worktrees}; do
    local legacy_worktree_path="${WORKTREE_ROOT}/${worktree}"
    local sanitized_worktree_path="${WORKTREE_ROOT}/$(sanitize_db_suffix "${worktree}")"
    local registered_worktree_path

    registered_worktree_path="$(get_worktree_path_for_branch "${worktree}")"
    if [[ -d "${legacy_worktree_path}" ]] || [[ -d "${sanitized_worktree_path}" ]] || [[ -n "${registered_worktree_path}" ]]; then
      continue
    fi

    echo "Removing stale port reservation for non-existent worktree: ${worktree}" >&2
    tmp_ports="$(mktemp)"
    if jq --arg name "${worktree}" 'del(.[$name])' "${PORTS_FILE}" > "${tmp_ports}"; then
      mv "${tmp_ports}" "${PORTS_FILE}"
      stale_count=$((stale_count + 1))
    else
      rm -f "${tmp_ports}"
    fi
  done

  if (( stale_count > 0 )); then
    echo "Cleaned up ${stale_count} stale port reservation(s)." >&2
  fi
}

is_port_reserved() {
  local port="$1"
  if [[ ! -f "${PORTS_FILE}" ]]; then
    return 1
  fi

  jq -e --argjson port "${port}" \
    'to_entries[] | .value | select(.server == $port or .frontend == $port)' \
    "${PORTS_FILE}" >/dev/null 2>&1
}

reserve_ports() {
  local worktree="$1"
  local server="$2"
  local frontend="$3"
  local tmp_ports

  ensure_ports_file
  tmp_ports="$(mktemp)"
  if jq --arg name "${worktree}" \
       --argjson server "${server}" \
       --argjson frontend "${frontend}" \
       '. + {($name): {server: $server, frontend: $frontend, updated_at: (now | todateiso8601)}}' \
       "${PORTS_FILE}" > "${tmp_ports}"; then
    if mv "${tmp_ports}" "${PORTS_FILE}"; then
      return 0
    fi
  fi
  rm -f "${tmp_ports}"
  return 1
}

is_port_in_use() {
  local port="$1"

  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"${port}" -sTCP:LISTEN -P -n >/dev/null 2>&1
    return $?
  fi

  if command -v nc >/dev/null 2>&1; then
    nc -z localhost "${port}" >/dev/null 2>&1
    return $?
  fi

  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :${port}" | grep -q "LISTEN"
    return $?
  fi

  echo "No port-checking tool found (need lsof, nc, or ss)." >&2
  return 2
}

find_next_available_port() {
  local start_port="$1"
  local port=$((start_port + 1))

  while true; do
    if ! is_port_in_use "${port}" && ! is_port_reserved "${port}"; then
      echo "${port}"
      return 0
    fi
    port=$((port + 1))
  done
}

# Acquire lock before port operations to prevent race conditions
echo "Acquiring port reservation lock..."
if ! acquire_ports_lock; then
  exit 1
fi

# Ensure lock is released on exit (add to existing trap)
release_lock_on_exit() {
  release_ports_lock
}
trap 'release_lock_on_exit; cleanup_on_failure' EXIT

# Clean up stale reservations from crashed/killed runs
cleanup_stale_reservations

ensure_ports_file
if jq -e --arg name "${WORKTREE_NAME}" 'has($name)' "${PORTS_FILE}" >/dev/null 2>&1; then
  echo "ERROR: Port reservation for ${WORKTREE_NAME} already exists in ${PORTS_FILE}." >&2
  echo "Run ./remove-worktree.sh ${WORKTREE_NAME} or remove the entry manually." >&2
  exit 1
fi

SERVER_PORT="$(find_next_available_port 8001)"
FRONTEND_PORT="$(find_next_available_port 5174)"

export SERVER_PORT
export FRONTEND_PORT

if ! reserve_ports "${WORKTREE_NAME}" "${SERVER_PORT}" "${FRONTEND_PORT}"; then
  echo "ERROR: Failed to reserve ports for ${WORKTREE_NAME}." >&2
  exit 1
fi
CREATED_PORTS=true

# Release lock now that ports are reserved
release_ports_lock

# Portable sed in-place: macOS requires -i '', GNU sed requires -i without argument
sed_inplace() {
  local pattern="$1"
  local file="$2"
  if [[ "$(uname)" == "Darwin" ]]; then
    sed -i '' -E "${pattern}" "${file}"
  else
    sed -i -E "${pattern}" "${file}"
  fi
}

# Escape sed replacement special characters (& and \)
sed_escape() {
  printf '%s' "$1" | sed 's/[&\\/]/\\&/g'
}

if [[ -f "${WORKTREE_PATH}/config.local.toml" ]]; then
  ESCAPED_DB_NAME="$(sed_escape "${DB_NAME}")"
  ESCAPED_AUTHZ_STORE_NAME="$(sed_escape "${AUTHZ_STORE_NAME}")"

  sed_inplace "s|^public_url = \".*\"|public_url = \"http://localhost:${FRONTEND_PORT}\"|" "${WORKTREE_PATH}/config.local.toml"
  sed_inplace "s|^database = \".*\"|database = \"${ESCAPED_DB_NAME}\"|" "${WORKTREE_PATH}/config.local.toml"
  sed_inplace "s|^store = \".*\"|store = \"${ESCAPED_AUTHZ_STORE_NAME}\"|" "${WORKTREE_PATH}/config.local.toml"
fi

# Create .env.dev at root for VSCode tasks (sources both ports)
cat > "${WORKTREE_PATH}/.env.dev" <<EOF
BACKEND_PORT=${SERVER_PORT}
FRONTEND_PORT=${FRONTEND_PORT}
EOF

# Create .env.local for Vite's loadEnv (proxy configuration)
cat > "${WORKTREE_PATH}/web/pingpong/.env.local" <<EOF
VITE_BACKEND_PORT=${SERVER_PORT}
VITE_FRONTEND_PORT=${FRONTEND_PORT}
EOF

echo "Installing backend deps (uv)..."
(cd "${WORKTREE_PATH}" && uv sync)

echo "Installing frontend deps (pnpm)..."
(cd "${WORKTREE_PATH}/web/pingpong" && pnpm install --frozen-lockfile)

# Open in VSCode if available
if command -v code >/dev/null 2>&1; then
  echo "Opening worktree in VSCode..."
  code --new-window "${WORKTREE_PATH}"
fi
