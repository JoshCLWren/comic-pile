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

    # Skip specific problematic model IDs regardless of provider
    # Match mistral-small-3.1-24b-instruct with any suffix (including :free, :beta, etc.)
    if [[ "$lower_model" =~ mistral-small-3\.1-24b-instruct ]]; then
      return 0
    fi

  # Skip any model containing "mistralai" anywhere in the name
  if [[ "$lower_model" =~ mistralai ]]; then
    return 0
  fi

  return 1
}

# Test the specific model mentioned in the error
model="mistralai/mistral-small-3.1-24b-instruct:free"
if _should_skip_model "$model"; then
  echo "Model '$model' should be skipped (returns 0)"
  exit 0
else
  echo "Model '$model' should NOT be skipped (returns 1)"
  exit 1
fi