import * as THREE from 'three'
import type { DiceRenderGlobalConfig } from './diceTypes'

export type TextureTileUv = { u0: number; v0: number; u1: number; v1: number }

export type DiceTextureAtlas = {
  texture: THREE.CanvasTexture;
  cols: number;
  rows: number;
  uvInset: number;
  triangleUvRadius: number;
  d12UvRadius: number;
  d10UvPadding: number;
  d10AutoCenter: boolean;
  d10TopOffsetX: number;
  d10TopOffsetY: number;
  d10BottomOffsetX: number;
  d10BottomOffsetY: number;
}

export function createTextureAtlas(maxNumber: number, renderConfig: DiceRenderGlobalConfig): DiceTextureAtlas {
  const {
    tileSize,
    uvInset,
    fontScale,
    textOffsetX,
    textOffsetY,
    borderWidth,
    textColor,
    borderColor,
    backgroundColor,
    fontFamily,
    fontWeight,
    triangleUvRadius,
    d12UvRadius,
    d10UvPadding,
    d10AutoCenter,
    d10TopOffsetX,
    d10TopOffsetY,
    d10BottomOffsetX,
    d10BottomOffsetY,
  } = renderConfig;

  const canvas = document.createElement('canvas')
  const cols = Math.ceil(Math.sqrt(maxNumber))
  const rows = Math.ceil(maxNumber / cols)

  canvas.width = tileSize * cols;
  canvas.height = tileSize * rows;
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    throw new Error('Unable to create 2D canvas context for dice texture atlas')
  }

  ctx.fillStyle = backgroundColor;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  for (let i = 1; i <= maxNumber; i++) {
    const col = (i - 1) % cols;
    const row = Math.floor((i - 1) / cols);
    const x = col * tileSize;
    const y = row * tileSize;

    ctx.fillStyle = backgroundColor;
    ctx.fillRect(x, y, tileSize, tileSize);

    ctx.strokeStyle = borderColor;
    ctx.lineWidth = borderWidth;
    ctx.strokeRect(
      x + borderWidth / 2,
      y + borderWidth / 2,
      tileSize - borderWidth,
      tileSize - borderWidth,
    );

    ctx.fillStyle = textColor;
    ctx.font = `${fontWeight} ${tileSize * fontScale}px ${fontFamily}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    const text = i.toString();
    ctx.fillText(
      text,
      x + tileSize * (0.5 + textOffsetX),
      y + tileSize * (0.5 + textOffsetY),
    );
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.generateMipmaps = false;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.needsUpdate = true;
  return {
    texture,
    cols,
    rows,
    uvInset,
    triangleUvRadius,
    d12UvRadius,
    d10UvPadding,
    d10AutoCenter,
    d10TopOffsetX,
    d10TopOffsetY,
    d10BottomOffsetX,
    d10BottomOffsetY,
  };
}

export function getUVForNumber(number: number, cols: number, rows: number, uvInset = 0): TextureTileUv {
  const col = (number - 1) % cols;
  const row = Math.floor((number - 1) / cols);
  const tileU = 1 / cols;
  const tileV = 1 / rows;
  const insetU = tileU * uvInset;
  const insetV = tileV * uvInset;
  return {
    u0: col / cols + insetU,
    v0: 1 - (row + 1) / rows + insetV,
    u1: (col + 1) / cols - insetU,
    v1: 1 - row / rows - insetV
  };
}