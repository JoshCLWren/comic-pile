import { describe, expect, it } from 'vitest'
import { buildD10Faces, D10_FACE_NUMBERS } from '../components/d10Geometry'

function sub(a, b) {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

function cross(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ]
}

function dot(a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

describe('d10Geometry', () => {
  it('builds 10 coplanar quad faces', () => {
    const { faces } = buildD10Faces()
    expect(faces).toHaveLength(10)

    faces.forEach((face) => {
      expect(face).toHaveLength(4)
      const [a, b, c, d] = face
      const normal = cross(sub(b, a), sub(c, a))
      const deviation = dot(normal, sub(d, a))
      expect(Math.abs(deviation)).toBeLessThan(1e-6)
    })
  })

  it('zigzags the belt height around the equator', () => {
    const { upperRing, lowerRing, topApex, bottomApex } = buildD10Faces()
    expect(topApex[1]).toBeGreaterThan(0)
    expect(bottomApex[1]).toBeLessThan(0)
    upperRing.forEach((vertex) => {
      expect(vertex[1]).toBeGreaterThan(0)
    })
    lowerRing.forEach((vertex) => {
      expect(vertex[1]).toBeLessThan(0)
    })
  })

  it('keeps numbering alternating with opposite sums of 11', () => {
    expect(D10_FACE_NUMBERS).toHaveLength(10)
    expect(new Set(D10_FACE_NUMBERS).size).toBe(10)
    for (let i = 0; i < 5; i++) {
      expect(D10_FACE_NUMBERS[i] + D10_FACE_NUMBERS[i + 5]).toBe(11)
    }
    for (let i = 0; i < D10_FACE_NUMBERS.length - 1; i++) {
      const currentHigh = D10_FACE_NUMBERS[i] > 5
      const nextHigh = D10_FACE_NUMBERS[i + 1] > 5
      expect(currentHigh).not.toBe(nextHigh)
    }
  })
})
