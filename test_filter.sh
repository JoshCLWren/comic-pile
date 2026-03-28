#!/usr/bin/env bash

# Test the _should_skip_model function from opencode_pipeline.sh

_should_skip_model() {
  local model="$1"
  # Trim whitespace
  model=$(echo "$model" | xargs)

  # Skip empty models
  if [[ -z "$model" ]]; then
    return 0
  fi

  # Convert to lowercase for case-insensitive matching
  local lower_model
  lower_model=$(echo "$model" | tr '[:upper:]' '[:lower:]')

# Skip only problematic model identifiers
    # Placeholder for future specific model skipping logic
    # For now, we rely on the broader patterns below
    :

   # Also skip specific problematic model IDs regardless of provider
   # Match mistral-small-3.1-24b-instruct with any suffix (including :free, :beta, etc.)
   if [[ "$lower_model" =~ mistral-small-3\.1-24b-instruct(:[^:]+)?$ ]]; then
     return 0
   fi

  # Skip any model containing "mistralai" anywhere in the name
  if [[ "$lower_model" =~ mistralai ]]; then
    return 0
  fi

  return 1
}

# Test cases
test_model() {
  local model="$1"
  local expected="$2"
  
  if _should_skip_model "$model"; then
    result="SKIP"
  else
    result="KEEP"
  fi
  
  if [[ "$result" == "$expected" ]]; then
    echo "✓ PASS: $model -> $result"
  else
    echo "✗ FAIL: $model -> $result (expected: $expected)"
  fi
}

echo "Testing model filtering logic:"
echo "================================"

test_model "nvidia/mistralai/mistral-small-3.1-24b-instruct-2503" "SKIP"
test_model "openrouter/mistralai/mistral-small-3.1-24b-instruct" "SKIP"
test_model "mistralai/Mistral-7B-Instruct" "SKIP"
test_model "opencode/nemotron-3-super-free" "KEEP"
test_model "mistral/mistral-medium-latest" "KEEP"
test_model "mistral/magistral-medium-latest" "KEEP"
test_model "anyprovider/mistral-small-3.1-24b-instruct:beta" "SKIP"
test_model "mistralai/some-other-model" "SKIP"
test_model "mistralai/mistral-small-3.1-24b-instruct" "SKIP"
test_model "mistralai/mistral-small-3.1-24b-instruct:free" "SKIP"


echo "================================"