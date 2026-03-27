#!/usr/bin/env bash
# Test every opencode model with a simple "say hello in one word" prompt.
# Runs up to PARALLEL jobs at once. Results saved to .opencode_logs/model_test_results.txt
#
# Usage:
#   ./scripts/test_models.sh
#   PARALLEL=20 ./scripts/test_models.sh   # more parallelism

set -uo pipefail

PARALLEL="${PARALLEL:-10}"
RESULTS_FILE="$(dirname "$0")/../.opencode_logs/model_test_results.txt"
mkdir -p "$(dirname "$RESULTS_FILE")"
> "$RESULTS_FILE"  # truncate

# Helper function to filter problematic models (same logic as pipeline)
_is_problematic_model() {
    local model="$1"
    # Filter out models that start with problematic providers (case-insensitive)
    if echo "$model" | grep -qiE "^openrouter/|^opencode/|^opencode-go/|^anthropic/|^github-copilot/|^mistralai/"; then
        echo "WARNING: Filtering out problematic model: $model" >&2
        return 0
    fi
    # Filter out models that contain mistralai provider in the path (case-insensitive)
    if echo "$model" | grep -qi "/mistralai/"; then
        echo "WARNING: Filtering out problematic model: $model" >&2
        return 0
    fi
    # Filter out models ending with :free (case-insensitive)
    if echo "$model" | grep -qi ":free$"; then
        echo "WARNING: Filtering out problematic model: $model" >&2
        return 0
    fi
     # Filter out specific problematic models
     # Note: Removed mistral-small-3.1-24b-instruct:free as it's now supported
     # if echo "$model" | grep -qiE "^mistralai/mistral-small-3\.1-24b-instruct:free$|^mistralai/mistral-small-3\.1-24b-instruct:free/"; then
     #     echo "WARNING: Filtering out problematic model: $model" >&2
     #     return 0
     # fi
     # if echo "$model" | grep -qi "mistral-small-3\.1-24b-instruct:free"; then
     #     echo "WARNING: Filtering out problematic model: $model" >&2
     #     return 0
     # fi
    return 1
}

MODELS_RAW=$(opencode models 2>/dev/null)
# Filter models
FILTERED_MODELS=()
while IFS= read -r model; do
    [[ -z "$model" ]] && continue
    if ! _is_problematic_model "$model"; then
        FILTERED_MODELS+=("$model")
    fi
done <<< "$MODELS_RAW"

MODELS=$(printf '%s\n' "${FILTERED_MODELS[@]}")
TOTAL=${#FILTERED_MODELS[@]}

echo "Testing $TOTAL models ($PARALLEL at a time)..."
echo "Results: $RESULTS_FILE"
echo ""

test_model() {
    local model="$1"
    local output exit_code=0
    output=$(timeout 30s opencode run -m "$model" "say hello in one word" 2>&1) || exit_code=$?

    if [[ $exit_code -eq 124 ]]; then
        echo "TIMEOUT  $model"
    elif echo "$output" | grep -qiE "ProviderModelNotFoundError|Model not found|Insufficient balance|not supported|unauthorized|invalid api|authentication"; then
        reason=$(echo "$output" | grep -iE "Error:|ProviderModel|balance|not found|not supported|unauthorized|invalid|authentication" | head -1 | sed 's/\x1b\[[0-9;]*m//g' | xargs)
        echo "FAIL     $model  [$reason]"
    elif [[ $exit_code -ne 0 ]]; then
        echo "FAIL     $model  [exit $exit_code]"
    else
        # Strip ANSI codes and extract last non-empty line as the response
        response=$(echo "$output" | sed 's/\x1b\[[0-9;]*m//g' | grep -v "^>" | grep -v "^$" | tail -1 | xargs)
        echo "OK       $model  [$response]"
    fi
}

export -f test_model

echo "$MODELS" | xargs -P "$PARALLEL" -I{} bash -c 'test_model "$@"' _ {} | tee "$RESULTS_FILE"

echo ""
echo "=== Summary ==="
ok=$(grep -c "^OK" "$RESULTS_FILE" || echo 0)
fail=$(grep -c "^FAIL" "$RESULTS_FILE" || echo 0)
timeout=$(grep -c "^TIMEOUT" "$RESULTS_FILE" || echo 0)
echo "OK:      $ok"
echo "FAIL:    $fail"
echo "TIMEOUT: $timeout"
echo ""
echo "Working models:"
grep "^OK" "$RESULTS_FILE" | awk '{print $2}'
