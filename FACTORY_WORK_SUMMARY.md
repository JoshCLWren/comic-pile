Factory 17 has completed the UX unification implementation for issue #1667. The roll result display has been transformed from a flat list of technical details into a reader-first hierarchy with:

1. **Consistent terminology**: "Connected to:" replaces "Routes:" for uniform vocabulary
2. **Reader-first organization**: Information is now presented in logical tiers with primary information upfront
3. **Collapsible sections**: Technical details are hidden by default, showing only essential information
4. **Comic-centric display**: Titles and meaningful context replace raw IDs throughout
5. **Preserved functionality**: All existing features and interactions remain intact

The changes are contained in `frontend/src/pages/RollPage/components/ThreadPool.tsx` and verified with comprehensive tests. No commits or pushes have been made - the wrapper persists all changes as required.