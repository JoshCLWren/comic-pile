AGENT ASSIGNMENT - Phase 1, Worktree p1-wt1
============================================

Phase: 1 (Cleanup & FastAPI Setup)
Worktree: comic-pile-p1-wt1 (create this)
Branch: phase/1-cleanup-fastapi-setup
Dependencies: None (can start immediately)

TASK 1.1: Rename package `comic-pile/` → `comic_pile/`
Status: pending

Instructions:
- Directory already renamed from comic-pile to comic_pile
- Your task is complete! Mark as done.
- Verify: Import comic_pile.core should work
- Update: Already done, just verify

TASK 1.2: Update imports across all files
Status: pending

Instructions:
- File: main.py - Change "from comic-pile.core" to "from comic_pile.core"
- File: tests/test_example.py - Change "from comic-pile.core" to "from comic_pile.core"
- No other files need changes
- Test: Import should work without errors
- Commit: feat(1.2): update imports from comic-pile to comic_pile

QUALITY CHECKS (Before marking complete):
1. pytest --cov=comic_pile --cov-fail-under=96
2. bash scripts/lint.sh
3. pyright .

UPDATE TASKS.md after completing each task.
