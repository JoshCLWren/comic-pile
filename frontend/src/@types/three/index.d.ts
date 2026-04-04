declare module 'three' {
  export const LinearFilter: number
  export const ClampToEdgeWrapping: number

  export class BufferAttribute {
    constructor(array: ArrayLike<number>, itemSize: number)
    readonly count: number
    getX(index: number): number
    getY(index: number): number
    getZ(index: number): number
  }

  export class BufferGeometry {
    setAttribute(name: string, attribute: BufferAttribute): this
    getAttribute(name: string): BufferAttribute
    setIndex(attribute: BufferAttribute): this
    getIndex(): BufferAttribute | null
    computeVertexNormals(): void
    dispose(): void
  }

  export class CanvasTexture {
    constructor(canvas: HTMLCanvasElement)
    generateMipmaps: boolean
    minFilter: number
    magFilter: number
    wrapS: number
    wrapT: number
    needsUpdate: boolean
    dispose(): void
  }

  export class Scene {
    add(object: object): void
    remove(object: object): void
  }

  export class PerspectiveCamera {
    constructor(fov: number, aspect: number, near: number, far: number)
    position: Vector3
  }

  export class WebGLRenderer {
    constructor(options?: { antialias?: boolean; alpha?: boolean })
    domElement: HTMLCanvasElement
    setSize(width: number, height: number): void
    setPixelRatio(ratio: number): void
    setClearColor(color: number, alpha?: number): void
    render(scene: Scene, camera: PerspectiveCamera): void
    dispose(): void
  }

  export class AmbientLight {
    constructor(color?: number, intensity?: number)
  }

  export class DirectionalLight {
    constructor(color?: number, intensity?: number)
    position: Vector3
  }

  export class MeshStandardMaterial {
    constructor(parameters?: {
      map?: CanvasTexture
      color?: number
      metalness?: number
      roughness?: number
    })
    map?: CanvasTexture
    dispose(): void
  }

  export class Euler {
    x: number
    y: number
    z: number
    setFromQuaternion(quaternion: Quaternion): this
  }

  export class Quaternion {
    setFromUnitVectors(vFrom: Vector3, vTo: Vector3): this
  }

  export class Vector3 {
    constructor(x?: number, y?: number, z?: number)
    x: number
    y: number
    z: number
    set(x: number, y: number, z: number): this
    clone(): Vector3
    add(vector: Vector3): this
    divideScalar(scalar: number): this
    normalize(): this
    crossVectors(a: Vector3, b: Vector3): this
    project(camera: PerspectiveCamera): this
  }

  export class Box3 {
    min: Vector3
    max: Vector3
    setFromObject(object: object): this
    isEmpty(): boolean
  }

  export class Mesh<
    TGeometry extends BufferGeometry = BufferGeometry,
    TMaterial extends MeshStandardMaterial = MeshStandardMaterial
  > {
    constructor(geometry: TGeometry, material: TMaterial)
    geometry: TGeometry
    material: TMaterial
    rotation: {
      x: number
      y: number
      z: number
      set(x: number, y: number, z: number): void
    }
    castShadow: boolean
  }

  export const MathUtils: {
    clamp(value: number, min: number, max: number): number
  }
}
