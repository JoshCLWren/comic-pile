import { useRef, useEffect } from 'react';
import * as THREE from 'three';

function normalize(v) {
  const len = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
  return [v[0] / len, v[1] / len, v[2] / len];
}

function addTriangle(verts, uvs, inds, v0, v1, v2, uv0, uv1, uv2) {
  const idx = verts.length / 3;
  verts.push(v0[0], v0[1], v0[2]);
  verts.push(v1[0], v1[1], v1[2]);
  verts.push(v2[0], v2[1], v2[2]);
  uvs.push(uv0[0], uv0[1]);
  uvs.push(uv1[0], uv1[1]);
  uvs.push(uv2[0], uv2[1]);
  inds.push(idx, idx + 1, idx + 2);
}

function createTextureAtlas(maxNumber) {
  const canvas = document.createElement('canvas');
  const tileSize = 256;
  const cols = Math.ceil(Math.sqrt(maxNumber));
  const rows = Math.ceil(maxNumber / cols);

  canvas.width = tileSize * cols;
  canvas.height = tileSize * rows;
  const ctx = canvas.getContext('2d');

  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  for (let i = 1; i <= maxNumber; i++) {
    const col = (i - 1) % cols;
    const row = Math.floor((i - 1) / cols);
    const x = col * tileSize;
    const y = row * tileSize;

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(x, y, tileSize, tileSize);

    ctx.strokeStyle = '#cccccc';
    ctx.lineWidth = 4;
    ctx.strokeRect(x + 2, y + 2, tileSize - 4, tileSize - 4);

    ctx.fillStyle = '#1a1a2e';
    ctx.font = `bold ${tileSize * 0.4}px Arial`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    const text = i.toString();
    ctx.fillText(text, x + tileSize / 2, y + tileSize / 2);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  return { texture, cols, rows };
}

function getUVForNumber(number, cols, rows) {
  const col = (number - 1) % cols;
  const row = Math.floor((number - 1) / cols);
  return {
    u0: col / cols,
    v0: 1 - (row + 1) / rows,
    u1: (col + 1) / cols,
    v1: 1 - row / rows
  };
}

function createD4Geometry(atlasInfo) {
  const { cols, rows } = atlasInfo;
  const verts = [];
  const uvs = [];
  const inds = [];

  const scale = 1 / Math.sqrt(3);
  const v = [
    [scale, scale, scale],
    [scale, -scale, -scale],
    [-scale, scale, -scale],
    [-scale, -scale, scale]
  ];

  const faces = [
    [0, 2, 1, 1],
    [0, 1, 3, 2],
    [0, 3, 2, 3],
    [1, 2, 3, 4]
  ];

  for (let i = 0; i < faces.length; i++) {
    const f = faces[i];
    const uv = getUVForNumber(f[3], cols, rows);
    const cx = (uv.u0 + uv.u1) / 2;
    const cy = (uv.v0 + uv.v1) / 2;
    const rx = (uv.u1 - uv.u0) * 0.4;
    const ry = (uv.v1 - uv.v0) * 0.4;

    addTriangle(
      verts,
      uvs,
      inds,
      v[f[0]],
      v[f[1]],
      v[f[2]],
      [cx, cy + ry],
      [cx - rx, cy - ry],
      [cx + rx, cy - ry]
    );
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(verts), 3));
  geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
  geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(inds), 1));
  geometry.computeVertexNormals();
  return geometry;
}

function createD6Geometry(atlasInfo) {
  const { cols, rows } = atlasInfo;
  const verts = [];
  const uvs = [];
  const inds = [];
  const s = 0.9;

  const corners = [
    [-s, -s, -s],
    [s, -s, -s],
    [s, s, -s],
    [-s, s, -s],
    [-s, -s, s],
    [s, -s, s],
    [s, s, s],
    [-s, s, s]
  ];

  const faces = [
    [4, 5, 6, 7, 1],
    [1, 0, 3, 2, 6],
    [5, 1, 2, 6, 3],
    [0, 4, 7, 3, 4],
    [7, 6, 2, 3, 2],
    [0, 1, 5, 4, 5]
  ];

  for (let i = 0; i < faces.length; i++) {
    const f = faces[i];
    const uv = getUVForNumber(f[4], cols, rows);
    const idx = verts.length / 3;

    verts.push(corners[f[0]][0], corners[f[0]][1], corners[f[0]][2]);
    verts.push(corners[f[1]][0], corners[f[1]][1], corners[f[1]][2]);
    verts.push(corners[f[2]][0], corners[f[2]][1], corners[f[2]][2]);
    verts.push(corners[f[3]][0], corners[f[3]][1], corners[f[3]][2]);

    uvs.push(uv.u0, uv.v0);
    uvs.push(uv.u1, uv.v0);
    uvs.push(uv.u1, uv.v1);
    uvs.push(uv.u0, uv.v1);

    inds.push(idx, idx + 1, idx + 2, idx, idx + 2, idx + 3);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(verts), 3));
  geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
  geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(inds), 1));
  geometry.computeVertexNormals();
  return geometry;
}

function createD8Geometry(atlasInfo) {
  const { cols, rows } = atlasInfo;
  const verts = [];
  const uvs = [];
  const inds = [];
  const a = 1.0;

  const v = [
    [0, a, 0],
    [0, -a, 0],
    [a, 0, 0],
    [-a, 0, 0],
    [0, 0, a],
    [0, 0, -a]
  ];

  const faces = [
    [0, 4, 2, 1],
    [0, 2, 5, 2],
    [0, 5, 3, 3],
    [0, 3, 4, 4],
    [1, 2, 4, 5],
    [1, 5, 2, 6],
    [1, 3, 5, 7],
    [1, 4, 3, 8]
  ];

  for (let i = 0; i < faces.length; i++) {
    const f = faces[i];
    const uv = getUVForNumber(f[3], cols, rows);
    const cx = (uv.u0 + uv.u1) / 2;
    const cy = (uv.v0 + uv.v1) / 2;
    const rx = (uv.u1 - uv.u0) * 0.4;
    const ry = (uv.v1 - uv.v0) * 0.4;

    addTriangle(verts, uvs, inds, v[f[0]], v[f[1]], v[f[2]], [cx, cy + ry], [cx - rx, cy - ry], [cx + rx, cy - ry]);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(verts), 3));
  geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
  geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(inds), 1));
  geometry.computeVertexNormals();
  return geometry;
}

function createD10Geometry(atlasInfo) {
  const { cols, rows } = atlasInfo;
  const verts = [];
  const uvs = [];
  const inds = [];

  // Pentagonal trapezohedron geometry
  // 12 vertices: top apex, bottom apex, 5 upper ring, 5 lower ring
  const R = 1;
  const H = 0.75;

  const topApex = [0, H, 0];
  const bottomApex = [0, -H, 0];

  const upperRing = [];
  const lowerRing = [];

  for (let i = 0; i < 5; i++) {
    const angle = (i * 2 * Math.PI) / 5;
    upperRing.push([Math.cos(angle) * R, 0, Math.sin(angle) * R]);

    const offsetAngle = angle + Math.PI / 5;
    lowerRing.push([Math.cos(offsetAngle) * R, 0, Math.sin(offsetAngle) * R]);
  }

  // Define 10 kite faces as quads (4 vertices each)
  // Even indices (0, 2, 4, 6, 8) are upper faces
  // Odd indices (1, 3, 5, 7, 9) are lower faces
  const faces = [];

  for (let i = 0; i < 5; i++) {
    // Upper face
    faces.push([
      topApex,
      upperRing[i],
      lowerRing[i],
      upperRing[(i + 1) % 5]
    ]);

    // Lower face
    faces.push([
      bottomApex,
      lowerRing[i],
      upperRing[(i + 1) % 5],
      lowerRing[(i + 1) % 5]
    ]);
  }

  // Face numbering (alternating high/low)
  // Opposite faces sum to 11
  const faceNumbers = [1, 9, 2, 8, 3, 7, 4, 6, 5, 10];

  function calculateFaceCenter(quad) {
    const [a, b, c, d] = quad;
    const cx = (a[0] + b[0] + c[0] + d[0]) / 4;
    const cy = (a[1] + b[1] + c[1] + d[1]) / 4;
    const cz = (a[2] + b[2] + c[2] + d[2]) / 4;
    return [cx, cy, cz];
  }

  function calculateFaceNormal(a, b, c) {
    const v1 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    const v2 = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    const normal = [
      v1[1] * v2[2] - v1[2] * v2[1],
      v1[2] * v2[0] - v1[0] * v2[2],
      v1[0] * v2[1] - v1[1] * v2[0]
    ];
    const len = Math.sqrt(normal[0] * normal[0] + normal[1] * normal[1] + normal[2] * normal[2]);
    return [normal[0] / len, normal[1] / len, normal[2] / len];
  }

  function calculateFaceBasis(normal) {
    let arb = [1, 0, 0];
    if (Math.abs(normal[0]) > 0.9) {
      arb = [0, 1, 0];
    }
    const cross = [
      normal[1] * arb[2] - normal[2] * arb[1],
      normal[2] * arb[0] - normal[0] * arb[2],
      normal[0] * arb[1] - normal[1] * arb[0]
    ];
    const uAxis = [
      normal[1] * cross[2] - normal[2] * cross[1],
      normal[2] * cross[0] - normal[0] * cross[2],
      normal[0] * cross[1] - normal[1] * cross[0]
    ];
    const vAxis = [
      normal[1] * uAxis[2] - normal[2] * uAxis[1],
      normal[2] * uAxis[0] - normal[0] * uAxis[2],
      normal[0] * uAxis[1] - normal[1] * uAxis[0]
    ];
    return { uAxis, vAxis };
  }

  function projectVertexToPlane(vertex, center, uAxis, vAxis) {
    const vx = vertex[0] - center[0];
    const vy = vertex[1] - center[1];
    const vz = vertex[2] - center[2];
    const u = vx * uAxis[0] + vy * uAxis[1] + vz * uAxis[2];
    const v = vx * vAxis[0] + vy * vAxis[1] + vz * vAxis[2];
    return { u, v };
  }

  function calculateUVBounds(projA, projB, projC, projD) {
    const uMin = Math.min(projA.u, projB.u, projC.u, projD.u);
    const uMax = Math.max(projA.u, projB.u, projC.u, projD.u);
    const vMin = Math.min(projA.v, projB.v, projC.v, projD.v);
    const vMax = Math.max(projA.v, projB.v, projC.v, projD.v);
    return { uMin, uMax, vMin, vMax };
  }

  function mapToTextureTile(u, v, bounds, tileUv) {
    const { uMin, uMax, vMin, vMax } = bounds;
    const uNorm = uMax > uMin ? (u - uMin) / (uMax - uMin) : 0.5;
    const vNorm = vMax > vMin ? (v - vMin) / (vMax - vMin) : 0.5;
    return {
      u: tileUv.u0 + uNorm * (tileUv.u1 - tileUv.u0),
      v: tileUv.v0 + vNorm * (tileUv.v1 - tileUv.v0)
    };
  }

  // Triangulate each quad into 2 triangles with proper UV mapping
  faces.forEach((quad, faceIndex) => {
    const [a, b, c, d] = quad;
    const number = faceNumbers[faceIndex];

    const center = calculateFaceCenter(quad);
    const normal = calculateFaceNormal(a, b, c);
    const { uAxis, vAxis } = calculateFaceBasis(normal);

    const projA = projectVertexToPlane(a, center, uAxis, vAxis);
    const projB = projectVertexToPlane(b, center, uAxis, vAxis);
    const projC = projectVertexToPlane(c, center, uAxis, vAxis);
    const projD = projectVertexToPlane(d, center, uAxis, vAxis);

    const bounds = calculateUVBounds(projA, projB, projC, projD);
    const tileUv = getUVForNumber(number, cols, rows);

    const uvA = mapToTextureTile(projA.u, projA.v, bounds, tileUv);
    const uvB = mapToTextureTile(projB.u, projB.v, bounds, tileUv);
    const uvC = mapToTextureTile(projC.u, projC.v, bounds, tileUv);
    const uvD = mapToTextureTile(projD.u, projD.v, bounds, tileUv);

    addTriangle(verts, uvs, inds, a, b, c, [uvA.u, uvA.v], [uvB.u, uvB.v], [uvC.u, uvC.v]);
    addTriangle(verts, uvs, inds, a, c, d, [uvA.u, uvA.v], [uvC.u, uvC.v], [uvD.u, uvD.v]);
  });

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(verts), 3));
  geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
  geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(inds), 1));
  geometry.computeVertexNormals();
  return geometry;
}

function createD12Geometry(atlasInfo) {
  const { cols, rows } = atlasInfo;
  const verts = [];
  const uvs = [];
  const inds = [];

  const phi = (1 + Math.sqrt(5)) / 2;
  const a = 1 / Math.sqrt(3);
  const b = a / phi;
  const c = a * phi;

  const v = [
    [a, a, a],
    [a, a, -a],
    [a, -a, a],
    [a, -a, -a],
    [-a, a, a],
    [-a, a, -a],
    [-a, -a, a],
    [-a, -a, -a],
    [0, b, c],
    [0, b, -c],
    [0, -b, c],
    [0, -b, -c],
    [b, c, 0],
    [b, -c, 0],
    [-b, c, 0],
    [-b, -c, 0],
    [c, 0, b],
    [c, 0, -b],
    [-c, 0, b],
    [-c, 0, -b]
  ];

  const faces = [
    [0, 8, 4, 14, 12, 1],
    [0, 16, 2, 10, 8, 2],
    [0, 12, 1, 17, 16, 3],
    [8, 10, 6, 18, 4, 4],
    [2, 16, 17, 3, 13, 5],
    [1, 12, 14, 5, 9, 6],
    [4, 18, 19, 5, 14, 7],
    [1, 9, 11, 3, 17, 8],
    [2, 13, 15, 6, 10, 9],
    [6, 15, 7, 19, 18, 10],
    [3, 11, 7, 15, 13, 11],
    [5, 19, 7, 11, 9, 12]
  ];

  for (let fi = 0; fi < faces.length; fi++) {
    const f = faces[fi];
    const uv = getUVForNumber(f[5], cols, rows);
    const cx = (uv.u0 + uv.u1) / 2;
    const cy = (uv.v0 + uv.v1) / 2;
    const rx = (uv.u1 - uv.u0) * 0.42;
    const ry = (uv.v1 - uv.v0) * 0.42;

    const center = [0, 0, 0];
    for (let j = 0; j < 5; j++) {
      center[0] += v[f[j]][0];
      center[1] += v[f[j]][1];
      center[2] += v[f[j]][2];
    }
    center[0] /= 5;
    center[1] /= 5;
    center[2] /= 5;

    const baseIdx = verts.length / 3;

    for (let j = 0; j < 5; j++) {
      verts.push(v[f[j]][0], v[f[j]][1], v[f[j]][2]);
      const angle = (j * 2 * Math.PI / 5) - Math.PI / 2;
      uvs.push(cx + Math.cos(angle) * rx, cy + Math.sin(angle) * ry);
    }

    verts.push(center[0], center[1], center[2]);
    uvs.push(cx, cy);
    const centerIdx = baseIdx + 5;

    for (let j = 0; j < 5; j++) {
      const next = (j + 1) % 5;
      inds.push(centerIdx, baseIdx + j, baseIdx + next);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(verts), 3));
  geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
  geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(inds), 1));
  geometry.computeVertexNormals();
  return geometry;
}

function createD20Geometry(atlasInfo) {
  const { cols, rows } = atlasInfo;
  const verts = [];
  const uvs = [];
  const inds = [];

  const t = (1 + Math.sqrt(5)) / 2;
  const s = 1.0;

  const v = [
    normalize([-s, t * s, 0]),
    normalize([s, t * s, 0]),
    normalize([-s, -t * s, 0]),
    normalize([s, -t * s, 0]),
    normalize([0, -s, t * s]),
    normalize([0, s, t * s]),
    normalize([0, -s, -t * s]),
    normalize([0, s, -t * s]),
    normalize([t * s, 0, -s]),
    normalize([t * s, 0, s]),
    normalize([-t * s, 0, -s]),
    normalize([-t * s, 0, s])
  ];

  const faces = [
    [0, 11, 5, 1],
    [0, 5, 1, 2],
    [0, 1, 7, 3],
    [0, 7, 10, 4],
    [0, 10, 11, 5],
    [1, 5, 9, 6],
    [5, 11, 4, 7],
    [11, 10, 2, 8],
    [10, 7, 6, 9],
    [7, 1, 8, 10],
    [3, 9, 4, 11],
    [3, 4, 2, 12],
    [3, 2, 6, 13],
    [3, 6, 8, 14],
    [3, 8, 9, 15],
    [4, 9, 5, 16],
    [2, 4, 11, 17],
    [6, 2, 10, 18],
    [8, 6, 7, 19],
    [9, 8, 1, 20]
  ];

  for (let i = 0; i < faces.length; i++) {
    const f = faces[i];
    const uv = getUVForNumber(f[3], cols, rows);
    const cx = (uv.u0 + uv.u1) / 2;
    const cy = (uv.v0 + uv.v1) / 2;
    const rx = (uv.u1 - uv.u0) * 0.4;
    const ry = (uv.v1 - uv.v0) * 0.4;

    addTriangle(verts, uvs, inds, v[f[0]], v[f[1]], v[f[2]], [cx, cy + ry], [cx - rx, cy - ry], [cx + rx, cy - ry]);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(verts), 3));
  geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
  geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(inds), 1));
  geometry.computeVertexNormals();
  return geometry;
}

function buildGeometry(sides, atlasInfo) {
  switch (sides) {
    case 4:
      return createD4Geometry(atlasInfo);
    case 6:
      return createD6Geometry(atlasInfo);
    case 8:
      return createD8Geometry(atlasInfo);
    case 10:
      return createD10Geometry(atlasInfo);
    case 12:
      return createD12Geometry(atlasInfo);
    case 20:
      return createD20Geometry(atlasInfo);
    default:
      return createD6Geometry(atlasInfo);
  }
}

function getNumberFromUv(u, v, cols, rows) {
  const col = Math.max(0, Math.min(cols - 1, Math.floor(u * cols)))
  const row = Math.max(0, Math.min(rows - 1, Math.floor((1 - v) * rows)))
  return row * cols + col + 1
}

function buildNumberNormals(geometry, cols, rows) {
  const position = geometry.getAttribute('position')
  const uv = geometry.getAttribute('uv')
  const index = geometry.getIndex()
  const normals = new Map()
  const counts = new Map()

  const triangleCount = index ? index.count / 3 : position.count / 3

  for (let i = 0; i < triangleCount; i++) {
    const a = index ? index.getX(i * 3) : i * 3
    const b = index ? index.getX(i * 3 + 1) : i * 3 + 1
    const c = index ? index.getX(i * 3 + 2) : i * 3 + 2

    const ax = position.getX(a)
    const ay = position.getY(a)
    const az = position.getZ(a)
    const bx = position.getX(b)
    const by = position.getY(b)
    const bz = position.getZ(b)
    const cx = position.getX(c)
    const cy = position.getY(c)
    const cz = position.getZ(c)

    const ab = new THREE.Vector3(bx - ax, by - ay, bz - az)
    const ac = new THREE.Vector3(cx - ax, cy - ay, cz - az)
    const normal = new THREE.Vector3().crossVectors(ab, ac).normalize()

    const u = (uv.getX(a) + uv.getX(b) + uv.getX(c)) / 3
    const v = (uv.getY(a) + uv.getY(b) + uv.getY(c)) / 3
    const number = getNumberFromUv(u, v, cols, rows)

    const current = normals.get(number) ?? new THREE.Vector3()
    current.add(normal)
    normals.set(number, current)
    counts.set(number, (counts.get(number) ?? 0) + 1)
  }

  for (const [number, normal] of normals.entries()) {
    normal.divideScalar(counts.get(number)).normalize()
  }

  return normals
}

function getFaceRotation(value, normalMap) {
  const normal = normalMap?.get(value)
  if (!normal) {
    return { x: 0, y: 0, z: 0 }
  }

  const target = new THREE.Vector3(0, 0, 1)
  const quaternion = new THREE.Quaternion().setFromUnitVectors(normal.clone().normalize(), target)
  const euler = new THREE.Euler().setFromQuaternion(quaternion)
  return { x: euler.x, y: euler.y, z: euler.z }
}

export default function Dice3D({
  sides = 6,
  value = 1,
  isRolling = false,
  freeze = false,
  color = 0xffffff,
  onRollComplete = null,
}) {
  const containerRef = useRef(null);
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const rendererRef = useRef(null);
  const meshRef = useRef(null);
  const targetRotationRef = useRef(null);
  const numberNormalsRef = useRef(null);
  const previousSidesRef = useRef(sides);

  useEffect(() => {
    if (!containerRef.current) return;

    const container = containerRef.current;
    const w = container.clientWidth || 200;
    const h = container.clientHeight || 200;

    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 1000);
    camera.position.set(0, 0, 4);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    rendererRef.current = renderer;

    container.appendChild(renderer.domElement);

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
    scene.add(ambientLight);

    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(5, 5, 5);
    scene.add(directionalLight);

    const fillLight = new THREE.DirectionalLight(0xffffff, 0.3);
    fillLight.position.set(-3, -3, 3);
    scene.add(fillLight);

    return () => {
      if (container && renderer.domElement && renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
      if (meshRef.current) {
        scene.remove(meshRef.current);
        if (meshRef.current.geometry) meshRef.current.geometry.dispose();
        if (meshRef.current.material) {
          if (meshRef.current.material.map) meshRef.current.material.map.dispose();
          meshRef.current.material.dispose();
        }
      }
      renderer.dispose();
    };
  }, []);

  useEffect(() => {
    if (!sceneRef.current) return;

    if (meshRef.current) {
      sceneRef.current.remove(meshRef.current);
      if (meshRef.current.geometry) meshRef.current.geometry.dispose();
      if (meshRef.current.material) {
        if (meshRef.current.material.map) meshRef.current.material.map.dispose();
        meshRef.current.material.dispose();
      }
    }

    const atlasInfo = createTextureAtlas(sides);
    const geometry = buildGeometry(sides, atlasInfo);
    numberNormalsRef.current = buildNumberNormals(geometry, atlasInfo.cols, atlasInfo.rows)
    const material = new THREE.MeshStandardMaterial({
      map: atlasInfo.texture,
      color,
      metalness: 0.15,
      roughness: 0.4
    });

    const mesh = new THREE.Mesh(geometry, material);
    mesh.castShadow = true;
    sceneRef.current.add(mesh);
    meshRef.current = mesh;

    previousSidesRef.current = sides;
  }, [sides, color]);

  useEffect(() => {
    let animationFrameId;

    const animate = () => {
      if (!meshRef.current) return;

      if (isRolling) {
        meshRef.current.rotation.x += 0.2;
        meshRef.current.rotation.y += 0.25;
        meshRef.current.rotation.z += 0.15;
      } else if (targetRotationRef.current) {
        const { x, y, z } = targetRotationRef.current;
        const dx = x - meshRef.current.rotation.x;
        const dy = y - meshRef.current.rotation.y;
        const dz = z - meshRef.current.rotation.z;

        meshRef.current.rotation.x += dx * 0.12;
        meshRef.current.rotation.y += dy * 0.12;
        meshRef.current.rotation.z += dz * 0.12;

        if (Math.abs(dx) < 0.01 && Math.abs(dy) < 0.01 && Math.abs(dz) < 0.01) {
          meshRef.current.rotation.set(x, y, z);
          targetRotationRef.current = null;
          if (onRollComplete) onRollComplete();
        }
      } else if (!freeze) {
        meshRef.current.rotation.y += 0.008;
      }

      if (rendererRef.current && sceneRef.current && cameraRef.current) {
        rendererRef.current.render(sceneRef.current, cameraRef.current);
      }

      animationFrameId = requestAnimationFrame(animate);
    };

    animate();

    return () => {
      if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
      }
    };
  }, [isRolling, onRollComplete, freeze]);

  useEffect(() => {
    if (!isRolling && meshRef.current) {
      targetRotationRef.current = getFaceRotation(value, numberNormalsRef.current)
    }
  }, [value, isRolling, sides])

  return (
    <div
      ref={containerRef}
      className="dice-3d"
      style={{ width: '100%', height: '100%', position: 'relative' }}
    />
  )
}

