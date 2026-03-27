#!/bin/bash
# Lint JavaScript files in static/js directory
if [ -d "static/js" ] && ls static/js/*.js >/dev/null 2>&1; then
  if [ "$1" = "--fix" ]; then
    npx eslint static/js/*.js --fix
  else
    npx eslint static/js/*.js
  fi
else
  echo "No JavaScript files to lint"
fi
exit 0
