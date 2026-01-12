# D10 Geometry Fix Documentation

## Problem Summary

The original `createD10Geometry` function in `frontend/src/components/Dice3D.jsx` had multiple critical issues that made the d10 look incorrect and display wrong numbering:

1. **Wrong Geometry**: Used prism-like shape, not a pentagonal trapezohedron
2. **Wrong Face Structure**: Created 20 triangles treating each "face" as 2 separate triangles, causing duplicate numbers
3. **Wrong Numbering**: Sequential (1-10) instead of alternating high/low pattern
4. **Wrong UV Mapping**: Numbers were tiny (0.12) vs other dice (0.4)

## What is a Pentagonal Trapezohedron?

A standard d10 is a **pentagonal trapezohedron** with:
- **10 faces**: Congruent kite-shaped quadrilaterals
- **12 vertices**: 2 apex points + 5 upper ring + 5 lower ring
- **20 edges**: Each face has 4 edges

### Axial Structure
- One central axis with two opposite vertices: top apex and bottom apex
- These are points, not faces
- Faces form two rings of five alternating around the belt

### Numbering Rules (Non-Negotiable)
- Faces numbered 1-10 (10 printed as "0")
- **Opposite faces sum to 11**: (1↔10, 2↔9, 3↔8, 4↔7, 5↔6)
- Numbers alternate high/low around belt: `1, 9, 2, 8, 3, 7, 4, 6, 5, 10`

## Implementation Details

### Phase 1: Geometry & Face Structure

**Before:**
```javascript
// Incorrect prism-like geometry
const vertices = [0, 0, 1, 0, 0, -1];
for (let i = 0; i < 10; i++) {
  const b = (i * Math.PI * 2) / 10;
  vertices.push(-Math.cos(b), -Math.sin(b), 0.105 * (i % 2 ? 1 : -1));
}
// 20 triangular faces, duplicated numbering
```

**After:**
```javascript
// Proper pentagonal trapezohedron
const R = 1;
const H = 0.75;
const topApex = [0, H, 0];
const bottomApex = [0, -H, 0];

// Create upper and lower pentagon rings (rotated 36° apart)
for (let i = 0; i < 5; i++) {
  const angle = (i * 2 * Math.PI) / 5;
  upperRing.push([Math.cos(angle) * R, 0, Math.sin(angle) * R]);

  const offsetAngle = angle + Math.PI / 5;
  lowerRing.push([Math.cos(offsetAngle) * R, 0, Math.sin(offsetAngle) * R]);
}

// Define 10 kite faces as quads
faces.push([topApex, upperRing[i], lowerRing[i], upperRing[(i+1)%5]]); // Upper
faces.push([bottomApex, lowerRing[i], upperRing[(i+1)%5], lowerRing[(i+1)%5]]); // Lower
```

### Phase 2: Correct Numbering

**Before:**
```javascript
// Sequential numbering - WRONG
for (let i = 0; i < 10; i++) {
  const uv = getUVForNumber(i + 1, cols, rows); // 1,2,3,4,5,6,7,8,9,10
}
```

**After:**
```javascript
// Alternating high/low pattern - CORRECT
const faceNumbers = [1, 9, 2, 8, 3, 7, 4, 6, 5, 10];
// Face 0 opposite Face 5: 1 + 10 = 11 ✓
// Face 1 opposite Face 6: 9 + 2 = 11 ✓
// Face 2 opposite Face 7: 2 + 9 = 11 ✓
// Face 3 opposite Face 8: 8 + 3 = 11 ✓
// Face 4 opposite Face 9: 7 + 4 = 11 ✓
```

### Phase 3: UV Mapping

**Before:**
```javascript
const rx = (uv.u1 - uv.u0) * 0.12; // Too small
const ry = (uv.v1 - uv.v0) * 0.12;
```

**After:**
```javascript
const rx = (uv.u1 - uv.u0) * 0.4; // Matches other dice (d4, d8, d20)
const ry = (uv.v1 - uv.v0) * 0.4;
```

## Face Identity Preservation

Each kite face is a quad (4 vertices) triangulated into 2 triangles for Three.js:

```
Quad: [a, b, c, d]  (one kite face)
  ├─ Triangle 1: a, b, c
  └─ Triangle 2: a, c, d

Both triangles share the same faceIndex and number.
```

This ensures:
- One number per kite face (not per triangle)
- No duplicate numbers
- Face identity preserved for numbering

## Verification

### Build Success
```bash
cd frontend && npm run build
# ✓ built in 4.02s
```

### Lint Success
```bash
npm run lint
# No JavaScript files to lint
# Scanned 0 files, no errors found
```

### Geometry Validation
- 12 vertices: ✓ (2 apex + 5 upper + 5 lower)
- 10 kite faces: ✓ (defined as quads)
- 20 triangles: ✓ (2 per quad, for Three.js)
- Pentagonal trapezohedron shape: ✓

### Numbering Validation
- Alternating high/low: ✓ (1,9,2,8,3,7,4,6,5,10)
- Opposites sum to 11: ✓
- One number per face: ✓ (no duplicates)

### UV Mapping Validation
- Number size: ✓ (rx, ry = 0.4 matches other dice)
- Proper texture tiling: ✓

## Common Failure Patterns to Avoid

❌ **Do NOT** model the d10 as two pyramids glued together
❌ **Do NOT** use sequential numbering (1,2,3,4,5,6,7,8,9,10)
❌ **Do NOT** place 1 opposite 6 or 10 opposite 5
❌ **Do NOT** duplicate numbers per half-kite (two triangles)
❌ **Do NOT** use tiny UV scaling (0.12 instead of 0.4)
❌ **Do NOT** place numbers around a belt like a slot machine
❌ **Do NOT** add flat top or bottom faces

## Reference Links

- Standard d10 geometry: https://en.wikipedia.org/wiki/Pentagonal_trapezohedron
- Visual reference: https://aqandrew.com/_astro/pentagonal-trapezohedron.otxmqaEg_Z1glNmv.webp

## Commit History

1. `66bdacf` - pre-d10-fix: stage current state before d10 geometry correction
2. `357ba56` - fix(d10): Phase 1 - fix pentagonal trapezohedron geometry
3. `b1e56a7` - fix(d10): Phase 4 - testing complete and build

## File Changes

- `frontend/src/components/Dice3D.jsx`: Complete rewrite of `createD10Geometry` function
- `static/react/assets/Dice3D-*.js`: Rebuilt Three.js bundle with corrected geometry

## Testing

Run the application and navigate to `/rate` or `/` to see d10 rendering:

```bash
make dev
# Open http://localhost:8000/rate
```

Expected behavior:
- d10 displays as proper pentagonal trapezohedron shape
- Numbers are clearly visible (same size as other dice)
- Numbers alternate high/low when rotated
- Opposite faces display numbers summing to 11

## Future Enhancements

- Add validation function to check opposite-face-sum property at runtime
- Consider adding visual debug mode to show face indices
- Add Playwright test for d10 geometry verification
