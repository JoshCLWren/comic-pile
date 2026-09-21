import { useRef, useEffect, useLayoutEffect } from 'react'
import * as THREE from 'three'
import { buildD10Faces } from './d10Geometry'
import { getDiceRenderConfigForSides } from './diceRenderConfig'
import type { Dice3DProps, DiceRenderGlobalConfig, DiceSide } from './diceTypes'
import { isDiceSide } from './diceTypes'
import { createTextureAtlas, getUVForNumber, type DiceTextureAtlas, type TextureTileUv } from './diceAtlas'
import { normalize, addTriangle, getNumberFromUv, buildNumberNormals, getFaceRotation, type Vector3Tuple, type Vector2Tuple, type QuadFace, type FaceProjection, type FaceBasis, type UVBounds, type NormalizedUvPoint, type ProjectedOffset, type FaceRotation, type NumberNormals, buildGeometry, createD4Geometry, createD6Geometry, createD8Geometry, createD10Geometry, createD12Geometry, createD20Geometry, createD30Geometry, createD50Geometry, createD100Geometry } from './diceGeometryUtils'

function lerp(start: number, end: number, alpha: number): number {
  return start + (end - start) * alpha;
}

function getProjectedCenterOffsetPx(
  mesh: THREE.Mesh,
  camera: THREE.PerspectiveCamera,
  width: number,
  height: number,
): ProjectedOffset {
  try {
    const worldBox = new THREE.Box3().setFromObject(mesh);
    if (worldBox.isEmpty()) {
      return { x: 0, y: 0 };
    }

    const { min, max } = worldBox;
    const corners = [
      new THREE.Vector3(min.x, min.y, min.z),
      new THREE.Vector3(min.x, min.y, max.z),
      new THREE.Vector3(min.x, max.y, min.z),
      new THREE.Vector3(min.x, max.y, max.z),
      new THREE.Vector3(max.x, min.y, min.z),
      new THREE.Vector3(max.x, min.y, max.z),
      new THREE.Vector3(max.x, max.y, min.z),
      new THREE.Vector3(max.x, max.y, max.z),
    ];

    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;

    for (const corner of corners) {
      const projected = corner.project(camera);
      minX = Math.min(minX, projected.x);
      maxX = Math.max(maxX, projected.x);
      minY = Math.min(minY, projected.y);
      maxY = Math.max(maxY, projected.y);
    }

    const centerNdcX = (minX + maxX) * 0.5;
    const centerNdcY = (minY + maxY) * 0.5;

    const offsetX = -centerNdcX * (width * 0.5);
    const offsetY = centerNdcY * (height * 0.5);

    // Guard against occasional projection spikes during init/resizing.
    const maxOffset = Math.min(width, height) * 0.18;
    return {
      x: THREE.MathUtils.clamp(offsetX, -maxOffset, maxOffset),
      y: THREE.MathUtils.clamp(offsetY, -maxOffset, maxOffset),
    };
  } catch {
    return { x: 0, y: 0 };
  }
}

export default function Dice3D({
  sides = 6,
  value = 1,
  isRolling = false,
  freeze = false,
  lockMotion = false,
  color = 0xffffff,
  onRollComplete = null,
  renderConfig = null,
}: Dice3DProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const sceneRef = useRef<THREE.Scene | null>(null)
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null)
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null)
  const meshRef = useRef<THREE.Mesh | null>(null)
  const targetRotationRef = useRef<FaceRotation | null>(null)
  const numberNormalsRef = useRef<NumberNormals | null>(null)
  const previousSidesRef = useRef<number>(sides)
  const opticalOffsetRef = useRef<ProjectedOffset>({ x: 0, y: 0 })
  const viewportSizeRef = useRef({ w: 200, h: 200 })
  const isRollingRef = useRef<boolean>(isRolling)
  const onRollCompleteRef = useRef<(() => void) | null>(onRollComplete)
  isRollingRef.current = isRolling;
  onRollCompleteRef.current = onRollComplete;

  // Sync ref in layout so the animation loop sees it before the next frame.
  useLayoutEffect(() => {
    isRollingRef.current = isRolling;
  }, [isRolling]);

  useEffect(() => {
    if (!containerRef.current) return;

    const container = containerRef.current;
    const w = container.clientWidth || 200;
    const h = container.clientHeight || 200;
    viewportSizeRef.current = { w, h };

    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 1000);
    camera.position.set(0, 0, 4);
    cameraRef.current = camera;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch (e) {
      console.error('WebGL initialization failed:', e);
      sceneRef.current = null;
      cameraRef.current = null;
      return;
    }

    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    rendererRef.current = renderer;

    const applySize = () => {
      const nextW = container.clientWidth;
      const nextH = container.clientHeight;
      if (!nextW || !nextH) return;
      const { w: currentW, h: currentH } = viewportSizeRef.current;
      if (currentW === nextW && currentH === nextH) return;
      viewportSizeRef.current = { w: nextW, h: nextH };
      camera.aspect = nextW / nextH;
      camera.updateProjectionMatrix();
      renderer.setSize(nextW, nextH);
    };

    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => applySize());
      resizeObserver.observe(container);
    }

    container.appendChild(renderer.domElement);

    // Center the canvas inside its position:relative container.
    const canvas = renderer.domElement;
    canvas.style.position = 'absolute';
    canvas.style.top = '50%';
    canvas.style.left = '50%';
    canvas.style.transform = 'translate(-50%, -50%)';

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
    scene.add(ambientLight);

    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(5, 5, 5);
    scene.add(directionalLight);

    const fillLight = new THREE.DirectionalLight(0xffffff, 0.3);
    fillLight.position.set(-3, -3, 3);
    scene.add(fillLight);

    return () => {
      if (resizeObserver) resizeObserver.disconnect();
      if (container && renderer.domElement && renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
      if (meshRef.current) {
        scene.remove(meshRef.current);
        if (meshRef.current.geometry) meshRef.current.geometry.dispose();
        if (meshRef.current.material) {
          if (meshRef.current.material.map) meshRef.current.material.map.dispose();
          meshRef.current.material.dispose();
        }
      }
      renderer.dispose();
    };
  }, []);

  useEffect(() => {
    if (!sceneRef.current) return;

    if (meshRef.current) {
      sceneRef.current.remove(meshRef.current);
      if (meshRef.current.geometry) meshRef.current.geometry.dispose();
      if (meshRef.current.material) {
        if (meshRef.current.material.map) meshRef.current.material.map.dispose();
        meshRef.current.material.dispose();
      }
    }

    const resolvedSides: DiceSide = isDiceSide(sides) ? sides : 6
    const resolvedConfig = getDiceRenderConfigForSides(resolvedSides, renderConfig);
    const atlasInfo = createTextureAtlas(sides, resolvedConfig);
    const geometry = buildGeometry(sides, atlasInfo);
    numberNormalsRef.current = buildNumberNormals(geometry, atlasInfo.cols, atlasInfo.rows)
    const material = new THREE.MeshStandardMaterial({
      map: atlasInfo.texture,
      color,
      metalness: 0.15,
      roughness: 0.4
    });

    const mesh = new THREE.Mesh(geometry, material);
    mesh.castShadow = true;
    sceneRef.current.add(mesh);
    meshRef.current = mesh;

    previousSidesRef.current = sides;
  }, [sides, color, renderConfig]);

  useEffect(() => {
    if (!rendererRef.current) return;

    let animationFrameId: number | null = null

    const animate = () => {
      if (!meshRef.current) {
        animationFrameId = requestAnimationFrame(animate);
        return;
      }
      const rolling = isRollingRef.current;

      let isStable = false;

      if (lockMotion) {
        if (targetRotationRef.current) {
          const { x, y, z } = targetRotationRef.current;
          meshRef.current.rotation.set(x, y, z);
          targetRotationRef.current = null;
        }
        isStable = true;
      } else if (rolling) {
        meshRef.current.rotation.x += 0.2;
        meshRef.current.rotation.y += 0.25;
        meshRef.current.rotation.z += 0.15;
      } else if (targetRotationRef.current) {
        const { x, y, z } = targetRotationRef.current;
        const dx = x - meshRef.current.rotation.x;
        const dy = y - meshRef.current.rotation.y;
        const dz = z - meshRef.current.rotation.z;

        meshRef.current.rotation.x += dx * 0.12;
        meshRef.current.rotation.y += dy * 0.12;
        meshRef.current.rotation.z += dz * 0.12;

        if (Math.abs(dx) < 0.01 && Math.abs(dy) < 0.01 && Math.abs(dz) < 0.01) {
          meshRef.current.rotation.set(x, y, z);
          targetRotationRef.current = null;
          const onComplete = onRollCompleteRef.current;
          if (onComplete) onComplete();
          isStable = true;
        }
      } else if (!freeze) {
        meshRef.current.rotation.y += 0.008;
      } else {
        isStable = true;
      }

      if (rendererRef.current && sceneRef.current && cameraRef.current) {
        rendererRef.current.render(sceneRef.current, cameraRef.current);
        const isIdleRotating = !freeze && !lockMotion && !rolling && !targetRotationRef.current;
        if (rendererRef.current.domElement && meshRef.current && isStable && !isIdleRotating) {
          const { w, h } = viewportSizeRef.current;
          const { x, y } = getProjectedCenterOffsetPx(meshRef.current, cameraRef.current, w, h);
          const easedX = lerp(opticalOffsetRef.current.x, x, 0.12);
          const easedY = lerp(opticalOffsetRef.current.y, y, 0.12);
          opticalOffsetRef.current = { x: easedX, y: easedY };
          rendererRef.current.domElement.style.transform =
            `translate(calc(-50% + ${easedX.toFixed(2)}px), calc(-50% + ${easedY.toFixed(2)}px))`;
        }
      }

      animationFrameId = requestAnimationFrame(animate);
    };

    animate();

    return () => {
      if (animationFrameId !== null) {
        cancelAnimationFrame(animationFrameId);
      }
      if (rendererRef.current?.domElement) {
        rendererRef.current.domElement.style.transform = 'translate(-50%, -50%)';
      }
    };
    // Restart loop when isRolling changes so the new loop definitely sees current ref.
  }, [freeze, lockMotion, isRolling]);

  useEffect(() => {
    if (!isRolling && meshRef.current) {
      const nextRotation = getFaceRotation(value, numberNormalsRef.current)
      if (lockMotion) {
        meshRef.current.rotation.set(nextRotation.x, nextRotation.y, nextRotation.z)
        targetRotationRef.current = null
      } else {
        targetRotationRef.current = nextRotation
      }
    }
  }, [value, isRolling, sides, renderConfig, lockMotion])

  return (
    <div
      ref={containerRef}
      className={`dice-3d${isRolling ? ' dice-3d-rolling' : ''}`}
      style={{ width: '100%', height: '100%', position: 'relative', pointerEvents: 'none' }}
    />
  )
}
