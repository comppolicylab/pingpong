#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

DB_DIR=".codeql/db"
OUT_DIR=".codeql/results"
LOG_DIR=".codeql/logs"

usage() {
  cat <<'EOF'
Usage: ./run-codeql-pr.sh <language|all>

Supported languages:
  actions
  javascript-typescript (or javascript)
  python
  all

You can also set CODEQL_LANGUAGE instead of passing a positional argument.
EOF
}

resolve_language_config() {
  local lang="$1"

  CODEQL_LANGUAGE_NAME=""
  CODEQL_PACK=""
  CODEQL_SUITE_FILE=""

  case "$lang" in
    actions)
      CODEQL_LANGUAGE_NAME="actions"
      CODEQL_PACK="codeql/actions-queries"
      CODEQL_SUITE_FILE="actions-security-and-quality.qls"
      ;;
    javascript | javascript-typescript)
      CODEQL_LANGUAGE_NAME="javascript-typescript"
      CODEQL_PACK="codeql/javascript-queries"
      CODEQL_SUITE_FILE="javascript-security-and-quality.qls"
      ;;
    python)
      CODEQL_LANGUAGE_NAME="python"
      CODEQL_PACK="codeql/python-queries"
      CODEQL_SUITE_FILE="python-security-and-quality.qls"
      ;;
    *)
      return 1
      ;;
  esac
}

cleanup_language_artifacts() {
  local lang="$1"
  local db_path
  local stale_db_path

  if ! resolve_language_config "$lang"; then
    echo "Unsupported language: $lang" >&2
    usage
    exit 2
  fi

  db_path="$DB_DIR/$CODEQL_LANGUAGE_NAME"

  if [ -e "$db_path" ]; then
    stale_db_path="${db_path}.stale.$$.$(date +%s)"
    mv "$db_path" "$stale_db_path"

    # Finder can recreate .DS_Store files while the old DB is being deleted.
    # Move the DB out of the way first so a new run can proceed regardless.
    find "$stale_db_path" -name '.DS_Store' -delete 2>/dev/null || true
    rm -rf "$stale_db_path" 2>/dev/null || true
  fi

  rm -f "$OUT_DIR/$CODEQL_LANGUAGE_NAME.sarif"
  rm -f "$LOG_DIR/$CODEQL_LANGUAGE_NAME.create-db.log" "$LOG_DIR/$CODEQL_LANGUAGE_NAME.analyze.log"
}

build_gitignored_lgtm_filters() {
  local -a filters=()
  local entry path

  while IFS= read -r -d '' entry; do
    [[ "$entry" == '!! '* ]] || continue

    path="${entry#!! }"
    path="${path%/}"
    [ -n "$path" ] || continue

    filters+=("exclude:$path")
  done < <(git status --ignored --porcelain=v1 -z --untracked-files=normal)

  if [ "${#filters[@]}" -gt 0 ]; then
    printf '%s\n' "${filters[@]}"
  fi
}

print_phase_summary() {
  local lang="$1"
  local phase="$2"
  local log_file="$3"

  case "$phase" in
    create-db)
      if grep -q "Successfully created database" "$log_file"; then
        local created_line
        created_line="$(grep "Successfully created database" "$log_file" | tail -n 1)"
        echo "[$lang][$phase] $created_line"
      fi
      ;;
    analyze)
      if grep -q "CodeQL scanned" "$log_file"; then
        local scanned_line
        scanned_line="$(grep "CodeQL scanned" "$log_file" | tail -n 1)"
        echo "[$lang][$phase] $scanned_line"
      fi
      ;;
  esac
}

run_with_live_progress() {
  local lang="$1"
  local phase="$2"
  shift 2

  local log_file="$LOG_DIR/$lang.$phase.log"
  local started_at
  started_at="$(date +%s)"

  : > "$log_file"
  echo "[$lang][$phase] Starting..."

  "$@" >"$log_file" 2>&1 &
  local cmd_pid=$!

  (
    while kill -0 "$cmd_pid" 2>/dev/null; do
      sleep 20
      if kill -0 "$cmd_pid" 2>/dev/null; then
        local elapsed=$(( $(date +%s) - started_at ))
        echo "[$lang][$phase] Still running... ${elapsed}s elapsed"
      fi
    done
  ) &
  local heartbeat_pid=$!

  set +e
  wait "$cmd_pid"
  local status=$?
  set -e

  kill "$heartbeat_pid" 2>/dev/null || true
  wait "$heartbeat_pid" 2>/dev/null || true

  local elapsed=$(( $(date +%s) - started_at ))
  if [ "$status" -ne 0 ]; then
    echo "[$lang][$phase] Failed after ${elapsed}s. Showing the last 80 log lines:"
    tail -n 80 "$log_file"
    return "$status"
  fi

  print_phase_summary "$lang" "$phase" "$log_file"
  echo "[$lang][$phase] Completed in ${elapsed}s"
}

run_codeql() {
  local lang="$1"

  if ! resolve_language_config "$lang"; then
    echo "Unsupported language: $lang" >&2
    usage
    exit 2
  fi

  local db="$DB_DIR/$CODEQL_LANGUAGE_NAME"
  local out="$OUT_DIR/$CODEQL_LANGUAGE_NAME.sarif"
  local lgtm_index_filters="${LGTM_INDEX_FILTERS:-}"
  local gitignored_excludes

  gitignored_excludes="$(build_gitignored_lgtm_filters)"
  if [ -n "$gitignored_excludes" ]; then
    if [ -n "$lgtm_index_filters" ]; then
      lgtm_index_filters="${gitignored_excludes}"$'\n'"${lgtm_index_filters}"
    else
      lgtm_index_filters="$gitignored_excludes"
    fi
    echo "[$CODEQL_LANGUAGE_NAME] Excluding Git-ignored paths from this run."
  fi

  # Prevent non-actions analyses from including GitHub Actions workflow coverage.
  if [ "$CODEQL_LANGUAGE_NAME" != "actions" ]; then
    local workflow_excludes=$'exclude:.github/workflows\nexclude:.github/reusable_workflows'
    if [ -n "$lgtm_index_filters" ]; then
      lgtm_index_filters="${workflow_excludes}"$'\n'"${lgtm_index_filters}"
    else
      lgtm_index_filters="$workflow_excludes"
    fi
    echo "[$CODEQL_LANGUAGE_NAME] Excluding GitHub Actions workflows from this run."
  fi

  local -a create_cmd=(
    codeql database create "$db"
    --language="$CODEQL_LANGUAGE_NAME"
    --source-root=.
    --overwrite
  )

  if [ -n "$lgtm_index_filters" ]; then
    create_cmd=(env "LGTM_INDEX_FILTERS=$lgtm_index_filters" "${create_cmd[@]}")
  fi

  run_with_live_progress "$CODEQL_LANGUAGE_NAME" "create-db" "${create_cmd[@]}"

  run_with_live_progress "$CODEQL_LANGUAGE_NAME" "analyze" \
    codeql database analyze "$db" \
      "$CODEQL_PACK:codeql-suites/$CODEQL_SUITE_FILE" \
      --format=sarifv2.1.0 \
      --output="$out" \
      --download \
      --sarif-category="$CODEQL_LANGUAGE_NAME"
}

target_language="${1:-${CODEQL_LANGUAGE:-}}"
if [ -z "$target_language" ]; then
  usage
  exit 2
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "Missing required dependency: jq" >&2
  exit 2
fi

mkdir -p "$DB_DIR" "$OUT_DIR" "$LOG_DIR"

declare -a languages_to_run
case "$target_language" in
  all)
    rm -rf "$DB_DIR" "$OUT_DIR" "$LOG_DIR"
    mkdir -p "$DB_DIR" "$OUT_DIR" "$LOG_DIR"
    languages_to_run=("actions" "javascript-typescript" "python")
    ;;
  actions | python | javascript | javascript-typescript)
    languages_to_run=("$target_language")
    ;;
  *)
    echo "Unsupported language: $target_language" >&2
    usage
    exit 2
    ;;
esac

for lang in "${languages_to_run[@]}"; do
  cleanup_language_artifacts "$lang"
  run_codeql "$lang"
done

total=0

for lang in "${languages_to_run[@]}"; do
  resolve_language_config "$lang"
  sarif="$OUT_DIR/$CODEQL_LANGUAGE_NAME.sarif"

  if [ ! -f "$sarif" ]; then
    continue
  fi

  lang_name="$CODEQL_LANGUAGE_NAME"
  count="$(jq '[.runs[].results[]] | length' "$sarif")"
  if [ "$count" -gt 0 ]; then
    echo "=== $lang_name: $count finding(s) ==="
    jq -r '
      [.runs[].results[]] | to_entries[] |
      "\(.key + 1). [\(.value.level // "warning")] \(.value.message.text)\n" +
      "   Rule: \(.value.ruleId)\n" +
      "   File: \(.value.locations[0].physicalLocation.artifactLocation.uri // "unknown"):" +
      "\(.value.locations[0].physicalLocation.region.startLine // "?")\n"
    ' "$sarif"
  else
    echo "=== $lang_name: no findings ==="
  fi

  total=$(( total + count ))
done

if [ "$total" -gt 0 ]; then
  echo "Total findings: $total"
  exit 1
fi
