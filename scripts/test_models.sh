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
TOTAL=$(echo "$MODELS" | wc -l)

echo "Testing $TOTAL models ($PARALLEL at a time)..."
echo "Results: $RESULTS_FILE"
echo ""

test_model() {
  local model="$1"
  local output exit_code=0

  # Map invalid model names to valid ones
  local actual_model="$model"
  # Trim whitespace
  actual_model=$(echo "$actual_model" | xargs)
  
  # Explicitly handle the known problematic model first
  if [[ "$actual_model" == "mistralai/mistral-small-3.1-24b-instruct:free" ]]; then
    actual_model="nvidia/mistralai/mistral-small-3.1-24b-instruct-2503"
  fi
  
  case "$actual_model" in
    # Mistral Small 3.1 - map all variants to the working NVIDIA version
    "mistralai/mistral-small-3.1-24b-instruct:free"|"openrouter/mistralai/mistral-small-3.1-24b-instruct:free"|"openrouter/mistralai/mistral-small-3.1-24b-instruct"|"mistralai/mistral-small-3.1-24b-instruct")
      actual_model="nvidia/mistralai/mistral-small-3.1-24b-instruct-2503"
      ;;
    *)
      # Keep the model as-is for other cases
      ;;
  esac
    
    output=$(timeout 30s opencode run -m "$actual_model" "say hello in one word" 2>&1) || exit_code=$?

    if [[ $exit_code -eq 124 ]]; then
        echo "TIMEOUT  $actual_model"
    elif echo "$output" | grep -qiE "ProviderModelNotFoundError|Model not found|Insufficient balance|not supported|unauthorized|invalid api|authentication"; then
        reason=$(echo "$output" | grep -iE "Error:|ProviderModel|balance|not found|not supported|unauthorized|invalid|authentication" | head -1 | sed 's/\x1b\[[0-9;]*m//g' | xargs)
        echo "FAIL     $actual_model  [$reason]"
    elif [[ $exit_code -ne 0 ]]; then
        echo "FAIL     $actual_model  [exit $exit_code]"
    else
        # Strip ANSI codes and extract last non-empty line as the response
        response=$(echo "$output" | sed 's/\x1b\[[0-9;]*m//g' | grep -v "^>" | grep -v "^$" | tail -1 | xargs)
        echo "OK       $actual_model  [$response]"
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
