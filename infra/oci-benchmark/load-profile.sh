#!/usr/bin/env bash
# Source this file: source ./load-profile.sh
# Do not enable set -e/-u/-o pipefail here: when sourced, those options mutate the
# caller's interactive shell and can terminate it (especially zsh prompts).

OCI_CONFIG_FILE="${OCI_CONFIG_FILE:-$HOME/.oci/config}"
OCI_PROFILE="${OCI_PROFILE:-DEFAULT}"

if [ ! -f "$OCI_CONFIG_FILE" ]; then
  echo "OCI config not found: $OCI_CONFIG_FILE" >&2
  return 1 2>/dev/null || exit 1
fi

read_profile_value() {
  local key="$1"
  awk -v profile="$OCI_PROFILE" -v key="$key" '
    $0 == "[" profile "]" { in_profile=1; next }
    /^\[/ { in_profile=0 }
    in_profile && index($0, key "=") == 1 { sub("^[^=]*=", ""); print; exit }
  ' "$OCI_CONFIG_FILE"
}

TENANCY="$(read_profile_value tenancy)"
REGION="$(read_profile_value region)"

if [ -z "$TENANCY" ] || [ -z "$REGION" ]; then
  echo "Could not read tenancy/region from profile [$OCI_PROFILE] in $OCI_CONFIG_FILE" >&2
  unset TENANCY REGION
  return 1 2>/dev/null || exit 1
fi

export TF_VAR_tenancy_ocid="$TENANCY"
export TF_VAR_compartment_ocid="$TENANCY"
export TF_VAR_region="$REGION"
unset TENANCY REGION

echo "Loaded OCI profile [$OCI_PROFILE] for region $TF_VAR_region"
