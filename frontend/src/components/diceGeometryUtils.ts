import * as THREE from 'three'
import type { DiceTextureAtlas } from './diceAtlas'

export type Vector3Tuple = [number, number, number]
export type Vector2Tuple = [number, number]
export type QuadFace = [Vector3Tuple, Vector3Tuple, Vector3Tuple, Vector3Tuple]
export type FaceProjection = { u: number; v: number }
export type FaceBasis = { uAxis: Vector3Tuple; vAxis: Vector3Tuple }
export type UVBounds = { uMin: number; uMax: number; vMin: number; vMax: number }
export type NormalizedUvPoint = { uNorm: number; vNorm: number }
export type ProjectedOffset = { x: number; y: number }
export type NumberNormals = Map<number, THREE.Vector3>

export function normalize(v: Vector3Tuple): Vector3Tuple {
  const len = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
  return [v[0] / len, v[1] / len, v[2] / len];
}

export function addTriangle(
  verts: number[],
  uvs: number[],
  inds: number[],
  v0: Vector3Tuple,
  v1: Vector3Tuple,
  v2: Vector3Tuple,
  uv0: Vector2Tuple,
  uv1: Vector2Tuple,
  uv2: Vector2Tuple,
): void {
  const idx = verts.length / 3
  verts.push(v0[0], v0[1], v0[2]);
  verts.push(v1[0], v1[1], v1[2]);
  verts.push(v2[0], v2[1], v2[2]);
  uvs.push(uv0[0], uv0[1]);
  uvs.push(uv1[0], uv1[1]);
  uvs.push(uv2[0], uv2[1]);
  inds.push(idx, idx + 1, idx + 2)
}

export function getNumberFromUv(u: number, v: number, cols: number, rows: number): number {
  const col = Math.max(0, Math.min(cols - 1, Math.floor(u * cols)))
  const row = Math.max(0, Math.min(rows - 1, Math.floor((1 - v) * rows)))
  return row * cols + col + 1
}

export function buildNumberNormals(
  geometry: THREE.BufferGeometry,
  cols: number,
  rows: number,
): NumberNormals {
  const position = geometry.getAttribute('position')
  const uv = geometry.getAttribute('uv')
  const index = geometry.getIndex()
  const normals = new Map<number, THREE.Vector3>()
  const counts = new Map<number, number>()

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
    normal.divideScalar(counts.get(number) ?? 1).normalize()
  }

  return normals
}