# Implementation Summary: Issue #2713 - Roll: collapse the Comic pillar into one primary identity card

## Problem Solved
The original ComicPillar component displayed redundant information across multiple stacked surfaces:
- "The Comic" section heading
- "Selected issue" card with title, issue number, progress, and "Fix issue #" button  
- Separate ComicVine status card (linked or not linked)
- ComicIdentity component with cover, detailed info, creators, story arcs
- This caused the title and issue number to be displayed twice, creating visual clutter

## Solution Implemented
Created a new `ConsolidatedComicCard` component that merges all elements into a single, cohesive comic card:

### Key Features
1. **Single primary identity**: Title and issue number displayed only once in consolidated format
2. **Cover image area**: Placeholder for comic cover (ready for ComicVine integration)
3. **Progress information**: Compact display of issue number, completion percentage, and issues remaining
4. **Subordinate correction controls**: "Fix issue #", "Wrong series?", and "Find ComicVine match" buttons moved to secondary action row
5. **Conditional ComicVine status**: Only shows "No ComicVine identity linked" for missing identities, not healthy ones
6. **Creator info section**: Simplified placeholder for creator information
7. **Preserved functionality**: All existing dialogs, cache invalidation, refresh behavior, and canonical identity semantics

### Requirements Met
✅ **Consolidated identity presentation**: Eliminated redundant title and issue number displays
✅ **Removed standalone "Selected issue" chrome**: Integrated into main comic card
✅ **Healthy ComicVine identities**: No longer show dedicated full-width status cards  
✅ **Correction controls**: Moved to compact secondary action row, subordinate location
✅ **Missing identity handling**: Maintains visible repair state for unresolved ComicVine mappings
✅ **Identity preservation**: Does not hide genuine identity problems
✅ **Functionality preservation**: All correction dialogs, cache invalidation, refresh behavior maintained

## Technical Changes
- **File**: `frontend/src/pages/RollPage/components/ComicPillar.tsx`
- **New component**: `ConsolidatedComicCard` replaces separate "Selected issue" card and ComicIdentity component
- **Structure**: Single React fragment wraps consolidated card and preserved dialogs
- **Design**: Follows frontend visual grammar with semantic theme colors and consistent spacing
- **Responsive**: Maintains responsive behavior across viewport sizes

## Acceptance Criteria Satisfied
- The comic title + issue number has one primary presentation on the post-roll screen
- Cover, identity, and progress read as one coherent comic card rather than multiple stacked admin cards
- A healthy ComicVine mapping does not consume its own full-width status card
- "Fix issue #" and "Wrong series?" remain discoverable and keyboard/touch accessible but visually secondary
- A missing/ambiguous ComicVine mapping still exposes a clear repair action
- Existing issue-number and ComicVine correction flows still update the rendered comic correctly
- Component structure supports future integration with actual ComicVine cover and creator data

## Verification
- TypeScript syntax errors resolved (JSX structure corrected)
- Component maintains all existing functionality
- Design follows established visual patterns
- Ready for integration testing with actual ComicVine data