import { render } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Dice3D from '../components/Dice3D'
import { DEFAULT_DICE_RENDER_CONFIG } from '../components/diceRenderConfig'

const diceMock = vi.hoisted(() => ({ failRenderer: false, noIndex: false, emptyBox: false, noMap: false, noGeometry: false, noMaterial: false }))

vi.mock('three', () => {
  class BufferGeometry {
    attributes: Record<
      string,
      {
        count?: number
        getX: (idx: number) => number
        getY?: (idx: number) => number
        getZ?: (idx: number) => number
      }
    >
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
      return diceMock.noIndex ? null : this.index
    }
    setAttribute() {}
    setIndex() {}
    computeVertexNormals() {}
    dispose() {}
  }
  class BufferAttribute {
    array: unknown
    itemSize: number

    constructor(array: unknown, itemSize: number) {
      this.array = array
      this.itemSize = itemSize
    }
  }
  class CanvasTexture {
    canvas: unknown
    needsUpdate: boolean

    constructor(canvas: unknown) {
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
      if (diceMock.failRenderer) throw new Error('WebGL unavailable')
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
      this.map = diceMock.noMap ? undefined : map
    }
    dispose() {}
  }
  class Mesh {
    geometry: unknown
    material: unknown
    castShadow: boolean
    rotation: { x: number; y: number; z: number; set: ReturnType<typeof vi.fn> }

    constructor(geometry: unknown, material: unknown) {
      this.geometry = diceMock.noGeometry ? undefined : geometry
      this.material = diceMock.noMaterial ? undefined : material
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
    project() {
      return this
    }
  }

  class Box3 {
    min = new Vector3(-1, -1, -1)
    max = new Vector3(1, 1, 1)
    setFromObject() { return this }
    isEmpty() { return diceMock.emptyBox }
  }

  class Quaternion {
    setFromUnitVectors() {
      return this
    }
  }

  class Euler {
    x = 0
    y = 0
    z = 0

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
    Box3,
    MathUtils: { clamp: (value: number, min: number, max: number) => Math.min(Math.max(value, min), max) },
  }
})

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 0,
    font: '',
    textAlign: 'left',
    textBaseline: 'top',
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

it('builds each supported geometry and handles animation/value changes', () => {
  for (const sides of [4, 6, 8, 10, 12, 20, 30, 50, 100] as const) {
    const { unmount } = render(
      <Dice3D sides={sides} value={sides > 1 ? sides - 1 : 1} isRolling showValue={false} color={0xffaa00} />,
    )
    expect(document.querySelector('.dice-3d')).toBeInTheDocument()
    unmount()
  }
  const { rerender } = render(<Dice3D sides={6} value={1} isRolling={false} />)
  rerender(<Dice3D sides={6} value={6} isRolling />)
  expect(document.querySelector('.dice-3d')).toBeInTheDocument()
})

it('falls back to a six-sided geometry for an unsupported side count', () => {
  render(<Dice3D sides={7 as never} value={1} />)
  expect(document.querySelector('.dice-3d')).toBeInTheDocument()
})

it('applies the d10 auto-centering render option', () => {
  render(
    <Dice3D
      sides={10}
      value={5}
      renderConfig={{
        ...DEFAULT_DICE_RENDER_CONFIG,
        global: { ...DEFAULT_DICE_RENDER_CONFIG.global, d10AutoCenter: true },
      }}
    />,
  )
  expect(document.querySelector('.dice-3d')).toBeInTheDocument()
})

it('renders safely when WebGL initialization fails', () => {
  diceMock.failRenderer = true
  expect(() => render(<Dice3D sides={6} value={1} />)).not.toThrow()
  diceMock.failRenderer = false
})

it('handles non-indexed geometry and an empty projected bounding box', () => {
  diceMock.noIndex = true
  diceMock.emptyBox = true
  const { unmount } = render(<Dice3D sides={6} value={2} lockMotion />)
  expect(document.querySelector('.dice-3d')).toBeInTheDocument()
  unmount()
  diceMock.noIndex = false
  diceMock.emptyBox = false
})

it('switches animation modes for rolling, frozen, and locked presentation', () => {
  const { rerender, unmount } = render(<Dice3D sides={6} value={2} isRolling />)
  rerender(<Dice3D sides={6} value={3} freeze />)
  rerender(<Dice3D sides={6} value={4} lockMotion />)
  expect(document.querySelector('.dice-3d')).toBeInTheDocument()
  unmount()
})

it('runs rolling, locked, frozen, and idle animation branches', () => {
  let nextFrame: FrameRequestCallback | undefined
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => {
    nextFrame = callback
    return 1
  }))
  const onRollComplete = vi.fn()
  const { rerender, unmount } = render(
    <Dice3D sides={6} value={2} isRolling lockMotion onRollComplete={onRollComplete} />,
  )
  nextFrame?.(0)
  rerender(<Dice3D sides={6} value={3} freeze />)
  for (let frame = 1; frame < 25; frame += 1) nextFrame?.(frame)
  rerender(<Dice3D sides={6} value={4} isRolling />)
  nextFrame?.(2)
  rerender(<Dice3D sides={6} value={5} />)
  nextFrame?.(3)
  expect(document.querySelector('.dice-3d')).toBeInTheDocument()
  unmount()
})

it('falls back cleanly when canvas or WebGL initialization is unavailable', () => {
  const context = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  expect(() => render(<Dice3D sides={6} value={1} />)).toThrow('Unable to create 2D canvas context')
  context.mockRestore()

  diceMock.failRenderer = true
  const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  const { container } = render(<Dice3D sides={6} value={1} />)
  expect(container.querySelector('.dice-3d')).toBeInTheDocument()
  expect(errorSpy).toHaveBeenCalledWith('WebGL initialization failed:', expect.any(Error))
  errorSpy.mockRestore()
  diceMock.failRenderer = false
})

it('disposes dice materials that do not have a texture map', () => {
  diceMock.noMap = true
  const { unmount } = render(<Dice3D sides={6} value={1} />)
  expect(document.querySelector('.dice-3d')).toBeInTheDocument()
  unmount()
  diceMock.noMap = false
})

it('cleans up meshes that have no geometry or material', () => {
  diceMock.noGeometry = true
  diceMock.noMaterial = true
  const { unmount } = render(<Dice3D sides={6} value={1} />)
  expect(document.querySelector('.dice-3d')).toBeInTheDocument()
  unmount()
  diceMock.noGeometry = false
  diceMock.noMaterial = false
})
