import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Dice3D from '../components/Dice3D'

vi.mock('three', () => {
  class BufferGeometry {
    setAttribute() {}
    setIndex() {}
    computeVertexNormals() {}
    dispose() {}
  }
  class BufferAttribute {
    constructor(array, itemSize) {
      this.array = array
      this.itemSize = itemSize
    }
  }
  class CanvasTexture {
    constructor(canvas) {
      this.canvas = canvas
      this.needsUpdate = false
    }
    dispose() {}
  }
  class Scene {
    add() {}
    remove() {}
  }
  class PerspectiveCamera {
    constructor() {
      this.position = { set: vi.fn() }
    }
  }
  class WebGLRenderer {
    constructor() {
      this.domElement = document.createElement('canvas')
    }
    setSize() {}
    setPixelRatio() {}
    setClearColor() {}
    render() {}
    dispose() {}
  }
  class AmbientLight {}
  class DirectionalLight {
    constructor() {
      this.position = { set: vi.fn() }
    }
  }
  class MeshStandardMaterial {
    constructor({ map }) {
      this.map = map
    }
    dispose() {}
  }
  class Mesh {
    constructor(geometry, material) {
      this.geometry = geometry
      this.material = material
      this.castShadow = false
      this.rotation = { x: 0, y: 0, z: 0, set: vi.fn() }
    }
  }

  return {
    BufferGeometry,
    BufferAttribute,
    CanvasTexture,
    Scene,
    PerspectiveCamera,
    WebGLRenderer,
    AmbientLight,
    DirectionalLight,
    MeshStandardMaterial,
    Mesh,
  }
})

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 0,
    font: '',
    textAlign: '',
    textBaseline: '',
    fillRect: vi.fn(),
    strokeRect: vi.fn(),
    fillText: vi.fn(),
  })
  vi.stubGlobal('requestAnimationFrame', vi.fn())
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('renders dice value overlay when enabled', () => {
  render(<Dice3D sides={6} value={3} showValue />)
  expect(screen.getByText('3')).toBeInTheDocument()
})
