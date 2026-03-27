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

MODELS=$(opencode models 2>/dev/null)

# Filter out models known to cause ProviderModelNotFoundError
# Skip any mistralai provider models and mistral-small-3.1-24b-instruct variants
FILTERED_MODELS=$(echo "$MODELS" | grep -v '^mistralai/' | grep -v 'mistral-small-3\.1-24b-instruct')

TOTAL=$(echo "$FILTERED_MODELS" | wc -l)

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
        local cleaned
        cleaned=$(echo "$output" | sed 's/\x1b\[[0-9;]*m//g')
        if echo "$cleaned" | grep -qiE "Error:|not found|not supported|unauthorized|invalid|authentication|does not exist|no endpoint"; then
            reason=$(echo "$cleaned" | grep -iE "Error:|not found|not supported|unauthorized|invalid|authentication|does not exist|no endpoint" | head -1 | xargs)
            echo "FAIL     $model  [$reason]"
        else
            response=$(echo "$cleaned" | grep -v "^>" | grep -v "^$" | tail -1 | xargs)
            echo "OK       $model  [$response]"
        fi
    fi
}

export -f test_model

echo "$FILTERED_MODELS" | xargs -P "$PARALLEL" -I{} bash -c 'test_model "$@"' _ {} | tee "$RESULTS_FILE"

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
