import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Dice3D from '../components/Dice3D'

vi.mock('three', () => {
  class BufferGeometry {
    constructor() {
      this.attributes = {
        position: {
          count: 3,
          getX: () => 0,
          getY: () => 0,
          getZ: () => 0,
        },
        uv: {
          getX: () => 0.1,
          getY: () => 0.1,
        },
      }
      this.index = {
        count: 3,
        getX: (idx) => idx,
      }
    }
    getAttribute(name) {
      return this.attributes[name]
    }
    getIndex() {
      return this.index
    }
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

  class Vector3 {
    constructor(x = 0, y = 0, z = 0) {
      this.x = x
      this.y = y
      this.z = z
    }
    crossVectors() {
      return this
    }
    normalize() {
      return this
    }
    add() {
      return this
    }
    divideScalar() {
      return this
    }
    clone() {
      return new Vector3(this.x, this.y, this.z)
    }
  }

  class Quaternion {
    setFromUnitVectors() {
      return this
    }
  }

  class Euler {
    setFromQuaternion() {
      return this
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
    Vector3,
    Quaternion,
    Euler,
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

it('renders dice container', () => {
  render(<Dice3D sides={6} value={3} />)
  expect(document.querySelector('.dice-3d')).toBeInTheDocument()
})
