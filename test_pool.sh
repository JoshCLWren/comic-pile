#!/usr/bin/env bash

# Test model pool loading without sourcing the full pipeline

_is_problematic_model() {
    local model="$1"
    # Filter out models that start with problematic providers (case-insensitive)
    if echo "$model" | grep -qiE "^openrouter/|^opencode/|^opencode-go/|^anthropic/|^github-copilot/"; then
        echo "WARNING: Filtering out problematic model: $model" >&2
        return 0
    fi
    # Filter out specific problematic mistralai models (case-insensitive)
    # Note: We now allow valid mistralai models but filter out specific problematic ones
    if echo "$model" | grep -qi "mistralai/mistral-small-3.1-24b-instruct:free"; then
        echo "WARNING: Filtering out problematic model: $model" >&2
        return 0
    fi
    # Filter out mistral-small-3.1-24b-instruct (case-insensitive)
    if echo "$model" | grep -qi "mistral-small-3.1-24b-instruct"; then
        echo "WARNING: Filtering out problematic model: $model" >&2
        return 0
    fi
    # Filter out models ending with :free (case-insensitive)
    # Note: All :free models are problematic and should be filtered out
    if echo "$model" | grep -qi ":free$"; then
        echo "WARNING: Filtering out problematic model: $model" >&2
        return 0
    fi
    return 1
}

# Load model test results
MODEL_POOL=()
if [[ -f ".opencode_logs/model_test_results.txt" ]]; then
    while IFS= read -r model; do
        if ! _is_problematic_model "$model"; then
            MODEL_POOL+=("$model")
        fi
    done < <(grep "^OK" ".opencode_logs/model_test_results.txt" | awk '{print $2}')
fi

echo "MODEL_POOL size: ${#MODEL_POOL[@]}"
echo "First few models:"
for i in {0..4}; do
    [[ -n "${MODEL_POOL[$i]}" ]] && echo "  ${MODEL_POOL[$i]}"
done

# Check if fallback is needed
if [[ ${#MODEL_POOL[@]} -eq 0 ]]; then
    echo "Using fallback models"
    local fallback_models=(
        "cerebras/zai-glm-4.7"
        "nvidia/deepseek-ai/deepseek-r1"
        "mistral/mistral-medium-latest"
        "nvidia/google/codegemma-7b"
    )
    for model in "${fallback_models[@]}"; do
        if ! _is_problematic_model "$model"; then
            MODEL_POOL+=("$model")
        fi
    done
fi

echo "Final MODEL_POOL size: ${#MODEL_POOL[@]}"