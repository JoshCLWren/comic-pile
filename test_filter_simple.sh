#!/usr/bin/env bash

_is_problematic_model() {
    local model="$1"
    # Filter out models that start with problematic providers (case-insensitive)
    if echo "$model" | grep -qiE "^openrouter/|^opencode/|^opencode-go/|^anthropic/|^github-copilot/"; then
        echo "WARNING: Filtering out problematic model: $model" >&2
        return 0
    fi
    # Filter out models that contain mistralai provider in the path (case-insensitive)
    # Filter out all mistralai models as they are not available
    if echo "$model" | grep -qi "/mistralai/"; then
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

# Test another model for comparison
echo "Testing model: nvidia/deepseek-ai/deepseek-r1"
if _is_problematic_model "nvidia/deepseek-ai/deepseek-r1"; then
    echo "✗ Model incorrectly filtered"
else
    echo "✓ Model correctly NOT filtered"
fi