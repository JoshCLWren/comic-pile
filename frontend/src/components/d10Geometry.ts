export const D10_FACE_NUMBERS = [1, 9, 2, 8, 3, 7, 4, 6, 5, 10]

function computeApexHeight(upperA, lowerA, upperB) {
  const cb = [lowerA[0] - upperA[0], lowerA[1] - upperA[1], lowerA[2] - upperA[2]]
  const db = [upperB[0] - upperA[0], upperB[1] - upperA[1], upperB[2] - upperA[2]]
  const normal = [
    cb[1] * db[2] - cb[2] * db[1],
    cb[2] * db[0] - cb[0] * db[2],
    cb[0] * db[1] - cb[1] * db[0],
  ]
  if (Math.abs(normal[1]) < 1e-6) {
    return 0.95
  }
  return upperA[1] - (normal[0] * (-upperA[0]) + normal[2] * (-upperA[2])) / normal[1]
}

export function buildD10Faces() {
  const R = 1
  const beltHeight = 0.105

  const upperRing = []
  const lowerRing = []

  for (let i = 0; i < 5; i++) {
    const angle = (i * 2 * Math.PI) / 5
    upperRing.push([Math.cos(angle) * R, beltHeight, Math.sin(angle) * R])

    const offsetAngle = angle + Math.PI / 5
    lowerRing.push([Math.cos(offsetAngle) * R, -beltHeight, Math.sin(offsetAngle) * R])
  }

  const H = computeApexHeight(upperRing[0], lowerRing[0], upperRing[1])
  const topApex = [0, H, 0]
  const bottomApex = [0, -H, 0]

  const faces = []

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
