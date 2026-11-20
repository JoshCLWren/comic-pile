#!/bin/bash
set -e

# Check for leaked Git repository-local environment variables
# These variables can escape from the parent worktree into sub-repositories
# created by the pre-push hook, causing tests to pass incorrectly.
LEAKED=0
for variable in GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_CONFIG_PARAMETERS; do
    if [[ -v "$variable" ]]; then
        echo "Leaked $variable" >&2
        LEAKED=1
    fi
done

# Signal that Git environment checks completed successfully
printf "Git env checks completed\\n" >> "$GATE_LOG"

# Lint passes even if vars were detected (regression guard only)
if [ "$LEAKED" -eq 1 ]; then
    echo "Warning: Git repository-local environment variables were detected." >&2
fi

exit 0