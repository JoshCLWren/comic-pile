import { render } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Dice3D from '../components/Dice3D'

vi.mock('three', () => {
  class BufferGeometry {
    attributes: Record<string, unknown>
    index: { count: number; getX: (idx: number) => number }

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
        getX: (idx: number) => idx,
      }
    }
    getAttribute(name: string) {
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
    array: Float32Array | Uint32Array
    itemSize: number

    constructor(array: Float32Array | Uint32Array, itemSize: number) {
      this.array = array
      this.itemSize = itemSize
    }
  }
  class CanvasTexture {
    canvas: HTMLCanvasElement
    needsUpdate: boolean

    constructor(canvas: HTMLCanvasElement) {
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
    position: { set: ReturnType<typeof vi.fn> }

    constructor() {
      this.position = { set: vi.fn() }
    }
  }
  class WebGLRenderer {
    domElement: HTMLCanvasElement

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
    position: { set: ReturnType<typeof vi.fn> }

    constructor() {
      this.position = { set: vi.fn() }
    }
  }
  class MeshStandardMaterial {
    map: unknown

    constructor({ map }: { map: unknown }) {
      this.map = map
    }
    dispose() {}
  }
  class Mesh {
    geometry: unknown
    material: unknown
    castShadow: boolean
    rotation: { x: number; y: number; z: number; set: ReturnType<typeof vi.fn> }

    constructor(geometry: unknown, material: unknown) {
      this.geometry = geometry
      this.material = material
      this.castShadow = false
      this.rotation = { x: 0, y: 0, z: 0, set: vi.fn() }
    }
  }

  class Vector3 {
    x: number
    y: number
    z: number

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
    LinearFilter: 'LinearFilter',
    ClampToEdgeWrapping: 'ClampToEdgeWrapping',
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
  } as unknown as CanvasRenderingContext2D)
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
