import { describe, expect, it } from 'vitest'
import { createD2Geometry } from '../components/Dice3D'
import { isDiceSide } from '../components/diceTypes'
import * as THREE from 'three'

describe('d2Geometry', () => {
  it('creates a cylinder geometry with 2 faces', () => {
    // Mock atlas info
    const atlasInfo = {
      cols: 2,
      rows: 1,
      uvInset: 0.05,
      texture: new THREE.CanvasTexture(document.createElement('canvas')),
      triangleUvRadius: 0.8,
      d12UvRadius: 0.8,
      d10UvPadding: 0.08,
      d10AutoCenter: true,
      d10TopOffsetX: 0,
      d10TopOffsetY: 0,
      d10BottomOffsetX: 0,
      d10BottomOffsetY: 0,
    }

    const geometry = createD2Geometry(atlasInfo)
    
    // Basic geometry properties
    expect(geometry).toBeInstanceOf(THREE.BufferGeometry)
    expect(geometry.getAttribute('position')).toBeDefined()
    expect(geometry.getAttribute('uv')).toBeDefined()
    expect(geometry.getIndex()).toBeDefined()
    
    // Check that we have vertices for both faces plus edge
    // SAFETY: createD2Geometry always produces BufferGeometry with these attributes.
    const positionAttribute = geometry.getAttribute('position') as THREE.BufferAttribute
    // SAFETY: geometry created by createD2Geometry always has uv attribute.
    const uvAttribute = geometry.getAttribute('uv') as THREE.BufferAttribute
    // SAFETY: createD2Geometry always sets the index attribute.
    const indexAttribute = geometry.getIndex() as THREE.BufferAttribute
    
    const positionCount = positionAttribute.count
    const uvCount = uvAttribute.count
    const indexCount = indexAttribute.count
    
    // Should have: 1 center + 33 vertices for top face (center + 32 edge points)
    // + 1 center + 33 vertices for bottom face + 66 edge vertices
    // Total: 1 + 33 + 1 + 33 + 66 = 134 vertices
    expect(positionCount).toBe(134)
    expect(uvCount).toBe(134)
    
    // Should have triangles for both faces and the edge
    // Top face: 32 triangles, Bottom face: 32 triangles, Edge: 64 triangles
    // Total: 32 + 32 + 64 = 96 triangles = 384 indices
    expect(indexCount).toBe(384)
    
    // Check that vertex normals are computed
    expect(geometry.getAttribute('normal')).toBeDefined()
  })

  it('creates proper UV mapping for face 1', () => {
    const atlasInfo = {
      cols: 2,
      rows: 1,
      uvInset: 0.05,
      texture: new THREE.CanvasTexture(document.createElement('canvas')),
      triangleUvRadius: 0.8,
      d12UvRadius: 0.8,
      d10UvPadding: 0.08,
      d10AutoCenter: true,
      d10TopOffsetX: 0,
      d10TopOffsetY: 0,
      d10BottomOffsetX: 0,
      d10BottomOffsetY: 0,
    }

    const geometry = createD2Geometry(atlasInfo)
    // SAFETY: geometry created by createD2Geometry always has uv attribute.
    const uvAttribute = geometry.getAttribute('uv') as THREE.BufferAttribute
    
    // First vertex should be the center of face 1
    const centerU = uvAttribute.getX(0)
    const centerV = uvAttribute.getY(0)
    
    // Should be approximately the center of the first texture tile
    // For 2x1 grid, first tile is u: 0.05 to 0.5, v: 0.05 to 0.95
    expect(centerU).toBeGreaterThanOrEqual(0.25)
    expect(centerU).toBeLessThanOrEqual(0.35)
    expect(centerV).toBeGreaterThanOrEqual(0.45)
    expect(centerV).toBeLessThanOrEqual(0.55)
  })

  it('creates proper UV mapping for face 2', () => {
    const atlasInfo = {
      cols: 2,
      rows: 1,
      uvInset: 0.05,
      texture: new THREE.CanvasTexture(document.createElement('canvas')),
      triangleUvRadius: 0.8,
      d12UvRadius: 0.8,
      d10UvPadding: 0.08,
      d10AutoCenter: true,
      d10TopOffsetX: 0,
      d10TopOffsetY: 0,
      d10BottomOffsetX: 0,
      d10BottomOffsetY: 0,
    }

    const geometry = createD2Geometry(atlasInfo)
    // SAFETY: geometry created by createD2Geometry always has uv attribute.
    const uvAttribute = geometry.getAttribute('uv') as THREE.BufferAttribute
    
    // The center of the bottom face should be around vertex 34 (1 + 33 + 1)
    const bottomCenterIndex = 34
    const centerU = uvAttribute.getX(bottomCenterIndex)
    const centerV = uvAttribute.getY(bottomCenterIndex)
    
    // Should be approximately the center of the second texture tile
    // For 2x1 grid, second tile is u: 0.5 to 0.95, v: 0.05 to 0.95
    expect(centerU).toBeGreaterThanOrEqual(0.65)
    expect(centerU).toBeLessThanOrEqual(0.75)
    expect(centerV).toBeGreaterThanOrEqual(0.45)
    expect(centerV).toBeLessThanOrEqual(0.55)
  })
})

describe('isDiceSide', () => {
  it('returns true for valid dice sides', () => {
    expect(isDiceSide(2)).toBe(true)
    expect(isDiceSide(4)).toBe(true)
    expect(isDiceSide(6)).toBe(true)
    expect(isDiceSide(8)).toBe(true)
    expect(isDiceSide(10)).toBe(true)
    expect(isDiceSide(12)).toBe(true)
    expect(isDiceSide(20)).toBe(true)
    expect(isDiceSide(30)).toBe(true)
    expect(isDiceSide(50)).toBe(true)
    expect(isDiceSide(100)).toBe(true)
  })

  it('returns false for invalid dice sides', () => {
    expect(isDiceSide(1)).toBe(false)
    expect(isDiceSide(3)).toBe(false)
    expect(isDiceSide(5)).toBe(false)
    expect(isDiceSide(7)).toBe(false)
    expect(isDiceSide(9)).toBe(false)
    expect(isDiceSide(11)).toBe(false)
    expect(isDiceSide(13)).toBe(false)
    expect(isDiceSide(15)).toBe(false)
    expect(isDiceSide(25)).toBe(false)
    expect(isDiceSide(0)).toBe(false)
    expect(isDiceSide(-1)).toBe(false)
    expect(isDiceSide(101)).toBe(false)
  })

  it('returns false for non-integer values', () => {
    expect(isDiceSide(2.5)).toBe(false)
    expect(isDiceSide(4.1)).toBe(false)
    expect(isDiceSide(6.9)).toBe(false)
    expect(isDiceSide(NaN)).toBe(false)
    expect(isDiceSide(Infinity)).toBe(false)
  })

  it('has correct type narrowing behavior', () => {
    // Test that TypeScript narrows the type correctly
    const testValue: number = 2
    
    if (isDiceSide(testValue)) {
      // This should be valid - testValue should be narrowed to DiceSide
      const diceSide: 2 | 4 | 6 | 8 | 10 | 12 | 20 | 30 | 50 | 100 = testValue
      expect(diceSide).toBe(2)
    }
    
    const invalidValue: number = 3
    if (!isDiceSide(invalidValue)) {
      // This should be valid - invalidValue should not be a DiceSide
      expect(invalidValue).not.toBeOneOf([2, 4, 6, 8, 10, 12, 20, 30, 50, 100])
    }
  })
})