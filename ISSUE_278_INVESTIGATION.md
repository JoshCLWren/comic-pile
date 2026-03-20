# Issue #278: d10 Adjacent Face Numbers Bug Documentation

## Problem Description

When the d10 is rolled (or at rest with a side face toward the camera), two consecutive numbers — e.g. 4 and 5, or 3 and 4 — are simultaneously visible on neighbouring faces.

## Root Cause Analysis

### Issue #1: Incorrect D10_FACE_NUMBERS Array

**Current Array:**
```typescript
export const D10_FACE_NUMBERS = [1, 9, 2, 8, 3, 7, 4, 6, 5, 10]
```

**Analysis:**
- Face indices 0, 2, 4, 6, 8 are upper faces (kites from top apex)
- Face indices 1, 3, 5, 7, 9 are lower faces (kites from bottom apex)

**Current Number Assignment:**
| Face Index | Face Type | Number | High/Low (>5?) |
|------------|-----------|--------|----------------|
| 0 | Upper | 1 | Low (≤5) |
| 1 | Lower | 9 | High (>5) |
| 2 | Upper | 2 | Low (≤5) |
| 3 | Lower | 8 | High (>5) |
| 4 | Upper | 3 | Low (≤5) |
| 5 | Lower | 7 | High (>5) |
| 6 | Upper | 4 | Low (≤5) |
| 7 | Lower | 6 | High (>5) |
| 8 | Upper | 5 | Low (≤5) |
| 9 | Lower | 10 | High (>5) |

**Problem:** The test at d10Geometry.test.ts:46-54 expects alternating high/low numbers around the belt. The current array passes this test, BUT there's a critical issue:

- Faces 8 and 9 have numbers 5 and 10
- This puts 5 (low) on an upper face and 10 (high) on a lower face
- When looking at adjacent visible faces, this can create consecutive number pairs

**Expected Fix (Issue #277):**
The array should be:
```typescript
export const D10_FACE_NUMBERS = [1, 10, 2, 9, 3, 8, 4, 7, 5, 6]
```

This ensures:
- Odd numbers (1, 3, 5, 7, 9) on one half
- Even numbers (2, 4, 6, 8, 10) on the other half
- Adjacent faces differ by 2 or more (no consecutive numbers)

### Issue #2: Number Glyph Positioning

**Current d10 Configuration:**
```typescript
d10UvPadding: 0.06,
d10TopOffsetX: 0,
d10TopOffsetY: 0,
d10BottomOffsetX: 0,
d10BottomOffsetY: 0,
```

**Problem:**
Numbers may be positioned too close to face edges, causing them to "bleed" toward neighboring quads where faces meet.

**Expected Fix (Issue #278):**
After fixing the D10_FACE_NUMBERS array, adjust:
1. `d10UvPadding` - Ensure numbers are centered within each quad
2. `d10TopOffsetX/Y` - Fine-tune upper face (1-5) positioning
3. `d10BottomOffsetX/Y` - Fine-tune lower face (6-10) positioning

## Verification Steps

1. Fix D10_FACE_NUMBERS array to prevent adjacent consecutive numbers
2. Verify d10UvPadding and offsets are properly configured
3. Test in DicePlayground.tsx - check all 10 faces render correctly
4. Verify no two adjacent visible faces show consecutive numbers (differ by 1)
5. Verify odd-only on top, even-only on bottom (or vice versa)

## Expected Behavior After Fix

When viewing the d10 from any angle:
- Adjacent visible faces should show numbers that differ by 2 or more
- Numbers should be centered within each face
- No consecutive numbers should be visible simultaneously on neighbouring faces
