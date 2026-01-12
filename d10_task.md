Task: Fix D10 Geometry in Three.js Dice Component
File: frontend/src/components/Dice3D.jsx
Problem: The createD10Geometry function is broken with syntax errors (duplicate declarations) and incorrect geometry logic.
What a D10 actually is:

10 kite-shaped faces (pentagonal trapezohedron)
Each face displays ONE number (1-10)
In the mesh, each kite is rendered as 2 triangles sharing a belt edge
Both triangles of a kite must share the SAME UV coordinates so the number appears continuous

Working reference geometry (from byWulf/threejs-dice):
// 12 vertices: 2 poles + 10 belt vertices
const vertices = [0, 0, 1, 0, 0, -1]; // poles
for (let i = 0; i < 10; i++) {
  const b = (i * Math.PI * 2) / 10;
  vertices.push(-Math.cos(b), -Math.sin(b), 0.105 * (i % 2 ? 1 : -1));
}

// 20 triangular faces forming 10 kites
const faces = [
  [0, 2, 3], [0, 3, 4], [0, 4, 5], [0, 5, 6], [0, 6, 7],
  [0, 7, 8], [0, 8, 9], [0, 9, 10], [0, 10, 11], [0, 11, 2],
  [1, 3, 2], [1, 4, 3], [1, 5, 4], [1, 6, 5], [1, 7, 6],
  [1, 8, 7], [1, 9, 8], [1, 10, 9], [1, 11, 10], [1, 2, 11]
];
// Kite i = faces[i] (top triangle) + faces[i+10] (bottom triangle)
// Both should get UV for number (i+1)

Key insight from Oracle agent:
The previous code flattened the faces array into numbers, then tried to index it as if it were still nested arrays, causing undefined values and NaN geometry.
Correct approach:

Keep faces as array of 3-element arrays (don't flatten)
For each kite i (0-9):

Top triangle: faces[i] with vertices at indices faces[i][0], faces[i][1], faces[i][2]
Bottom triangle: faces[i+10] with same number UV


Use helper to extract vertex coordinates: getV = (idx) => [vertices[idx*3], vertices[idx*3+1], vertices[idx*3+2]]

Steps:

First, read the current createD10Geometry function to see the damage
Compare against other working dice functions (createD6Geometry, createD8Geometry) in same file for the pattern
Rewrite createD10Geometry following the pattern but with D10-specific geometry
Test that linting passes AND the app runs without THREE.js errors

Do NOT:

Flatten the faces array then try to index it
Create 20 separate numbered faces (only 10 numbers should appear)
Add code without removing duplicate declarations first
