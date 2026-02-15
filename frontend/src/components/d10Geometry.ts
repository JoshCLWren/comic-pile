export const D10_FACE_NUMBERS = [1, 9, 2, 8, 3, 7, 4, 6, 5, 10]

type Vector3 = [number, number, number]

function computeApexHeight(upperA: Vector3, lowerA: Vector3, upperB: Vector3): number {
  const cb: Vector3 = [lowerA[0] - upperA[0], lowerA[1] - upperA[1], lowerA[2] - upperA[2]]
  const db: Vector3 = [upperB[0] - upperA[0], upperB[1] - upperA[1], upperB[2] - upperA[2]]
  const normal: Vector3 = [
    cb[1] * db[2] - cb[2] * db[1],
    cb[2] * db[0] - cb[0] * db[2],
    cb[0] * db[1] - cb[1] * db[0],
  ]
  if (Math.abs(normal[1]) < 1e-6) {
    return 0.95
  }
  return upperA[1] - (normal[0] * (-upperA[0]) + normal[2] * (-upperA[2])) / normal[1]
}

export interface D10Geometry {
  faces: Vector3[][]
  faceNumbers: number[]
  upperRing: Vector3[]
  lowerRing: Vector3[]
  topApex: Vector3
  bottomApex: Vector3
}

export function buildD10Faces(): D10Geometry {
  const R = 1
  const beltHeight = 0.105

  const upperRing: Vector3[] = []
  const lowerRing: Vector3[] = []

  for (let i = 0; i < 5; i++) {
    const angle = (i * 2 * Math.PI) / 5
    upperRing.push([Math.cos(angle) * R, beltHeight, Math.sin(angle) * R])

    const offsetAngle = angle + Math.PI / 5
    lowerRing.push([Math.cos(offsetAngle) * R, -beltHeight, Math.sin(offsetAngle) * R])
  }

  const H = computeApexHeight(upperRing[0], lowerRing[0], upperRing[1])
  const topApex: Vector3 = [0, H, 0]
  const bottomApex: Vector3 = [0, -H, 0]

  const faces: Vector3[][] = []

  for (let i = 0; i < 5; i++) {
    faces.push([topApex, upperRing[i], lowerRing[i], upperRing[(i + 1) % 5]])
    faces.push([bottomApex, lowerRing[i], upperRing[(i + 1) % 5], lowerRing[(i + 1) % 5]])
  }

  return {
    faces,
    faceNumbers: D10_FACE_NUMBERS,
    upperRing,
    lowerRing,
    topApex,
    bottomApex,
  }
}
