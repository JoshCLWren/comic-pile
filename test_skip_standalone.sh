#!/usr/bin/env bash

# Test the _should_skip_model function logic

_test_skip_model() {
  local model="$1"
  echo "Testing: '$model'"
  
  # Trim whitespace
  model=$(echo "$model" | xargs)
  
  # Skip empty models
  if [[ -z "$model" ]]; then
    echo "  -> SKIP (empty)"
    return 0
  fi
  
  # Convert to lowercase for case-insensitive matching
  local lower_model
  lower_model=$(echo "$model" | tr '[:upper:]' '[:lower:]')
  echo "  Lowercase: '$lower_model'"
  
  # Explicitly skip the problematic model that causes ProviderModelNotFoundError
  if [[ "$lower_model" == "mistralai/mistral-small-3.1-24b-instruct" ]] || \
     [[ "$lower_model" == "mistralai/mistral-small-3.1-24b-instruct:free" ]] || \
     [[ "$lower_model" == "mistralai/mistral-small-3.1-24b-instruct:beta" ]]; then
    echo "  -> SKIP (explicit match)"
    return 0
  fi
  
  # Skip mistralai models that cause ProviderModelNotFoundError
  # This includes all mistralai provider models
  if [[ "$lower_model" == mistralai/* ]]; then
    echo "  -> SKIP (mistralai provider)"
    return 0
  fi
  
  # Also skip specific problematic model IDs regardless of provider
  # Match mistral-small-3.1-24b-instruct with any suffix (including :free, :beta, etc.)
  if [[ "$lower_model" =~ mistral-small-3\.1-24b-instruct ]]; then
    echo "  -> SKIP (pattern match)"
    return 0
  fi
  
  # Skip any model containing "mistralai" anywhere in the name
  if [[ "$lower_model" =~ mistralai ]]; then
    echo "  -> SKIP (contains mistralai)"
    return 0
  fi
  
  echo "  -> KEEP"
  return 1
}

echo "Testing model filtering logic:"
echo "================================"

# Test cases
_test_skip_model "mistralai/mistral-small-3.1-24b-instruct"
_test_skip_model "mistralai/mistral-small-3.1-24b-instruct:free"
_test_skip_model "mistralai/mistral-small-3.1-24b-instruct:beta"
_test_skip_model "mistralai/Mistral-7B-Instruct"
_test_skip_model "opencode/nemotron-3-super-free"
_test_skip_model "mistral/mistral-medium-latest"
_test_skip_model "mistral/magistral-medium-latest"
_test_skip_model "anyprovider/mistral-small-3.1-24b-instruct:beta"
_test_skip_model "mistralai/some-other-model"

echo "================================"