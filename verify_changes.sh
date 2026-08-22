#!/bin/bash

# Check for raw IDs in the main thread display
echo "Checking for raw IDs in ThreadPool component..."

# Look for patterns that might indicate raw IDs
grep -n "Issue [0-9]\+" /home/runner/work/comic-pile/comic-pile/frontend/src/pages/RollPage/components/ThreadPool.tsx || echo "No bare Issue IDs found"

grep -n "ComicVine #" /home/runner/work/comic-pile/comic-pile/frontend/src/pages/RollPage/components/ThreadPool.tsx || echo "No ComicVine IDs found"

# Check that comic titles are displayed
grep -n "The Amazing Spider-Man" /home/runner/work/comic-pile/comic-pile/frontend/src/pages/RollPage/components/ThreadPool.tsx && echo "Found comic title" || echo "Need to verify comic titles"

grep -n "Batman" /home/runner/work/comic-pile/comic-pile/frontend/src/pages/RollPage/components/ThreadPool.tsx && echo "Found comic title" || echo "Need to verify comic titles"

echo "Verification complete."