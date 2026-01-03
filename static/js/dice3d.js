// dice3d.js - Three.js dice with numbers on ALL faces, backward compatible
(function () {
  'use strict';

  var THREE = window.THREE;
  if (!THREE) {
    console.error('[Dice3D] THREE.js not found on window');
    return;
  }

  var instances = [];

  // ============================================================================
  // TEXTURE & MATERIAL CREATION
  // ============================================================================

  function createNumberTexture(number) {
    var canvas = document.createElement('canvas');
    var size = 256;
    canvas.width = size;
    canvas.height = size;
    var ctx = canvas.getContext('2d');

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, size, size);

    ctx.strokeStyle = '#dddddd';
    ctx.lineWidth = 3;
    ctx.strokeRect(0, 0, size, size);

    if (number >= 1 && number <= 6) {
      drawPips(ctx, number, size);
    }

    var texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;
    return texture;
  }

  function drawPips(ctx, number, size) {
    var pipRadius = size * 0.08;
    var offset = size * 0.25;
    var center = size / 2;

    ctx.fillStyle = '#000000';

    var positions = {
      1: [[center, center]],
      2: [[offset, offset], [size - offset, size - offset]],
      3: [[offset, offset], [center, center], [size - offset, size - offset]],
      4: [[offset, offset], [size - offset, offset], [offset, size - offset], [size - offset, size - offset]],
      5: [[offset, offset], [size - offset, offset], [center, center], [offset, size - offset], [size - offset, size - offset]],
      6: [[offset, offset], [size - offset, offset], [offset, center], [size - offset, center], [offset, size - offset], [size - offset, size - offset]]
    };

    var pips = positions[number] || [];
    for (var i = 0; i < pips.length; i++) {
      ctx.beginPath();
      ctx.arc(pips[i][0], pips[i][1], pipRadius, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function createTextureAtlas(maxNumber) {
    var canvas = document.createElement('canvas');
    var tileSize = 256;
    var cols = Math.ceil(Math.sqrt(maxNumber));
    var rows = Math.ceil(maxNumber / cols);

    canvas.width = tileSize * cols;
    canvas.height = tileSize * rows;
    var ctx = canvas.getContext('2d');

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    for (var i = 1; i <= maxNumber; i++) {
      var col = (i - 1) % cols;
      var row = Math.floor((i - 1) / cols);
      var x = col * tileSize;
      var y = row * tileSize;

      ctx.fillStyle = '#ffffff';
      ctx.fillRect(x, y, tileSize, tileSize);

      ctx.strokeStyle = '#dddddd';
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, tileSize, tileSize);

      ctx.fillStyle = '#000000';
      ctx.font = 'bold ' + (tileSize * 0.6) + 'px Arial';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(i.toString(), x + tileSize / 2, y + tileSize / 2);
    }

    var texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;
    return { texture: texture, cols: cols, rows: rows };
  }

  function getUVForNumber(number, cols, rows) {
    var col = (number - 1) % cols;
    var row = Math.floor((number - 1) / cols);
    return {
      u0: col / cols,
      v0: row / rows,
      u1: (col + 1) / cols,
      v1: (row + 1) / rows
    };
  }

  // ============================================================================
  // CUSTOM GEOMETRY FUNCTIONS
  // ============================================================================

  function createD4Geometry(atlasInfo) {
    var cols = atlasInfo.cols, rows = atlasInfo.rows;
    var a = 1.0;
    var vertices = new Float32Array([
      0, a, 0, -a, -a, a, a, -a, a,
      0, a, 0, a, -a, a, a, -a, -a,
      0, a, 0, a, -a, -a, -a, -a, -a,
      0, a, 0, -a, -a, -a, -a, -a, a
    ]);
    var indices = new Uint16Array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
    var uvs = new Float32Array(12 * 2);
    
    for (var face = 0; face < 4; face++) {
      var uv = getUVForNumber(face + 1, cols, rows);
      var offset = face * 6;
      uvs[offset + 0] = (uv.u0 + uv.u1) / 2; uvs[offset + 1] = uv.v0;
      uvs[offset + 2] = uv.u0; uvs[offset + 3] = uv.v1;
      uvs[offset + 4] = uv.u1; uvs[offset + 5] = uv.v1;
    }

    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    geometry.computeVertexNormals();
    return geometry;
  }

  function createD6Geometry(atlasInfo) {
    var cols = atlasInfo.cols, rows = atlasInfo.rows;
    var s = 1;
    var vertices = new Float32Array([
      -s, -s, s, s, -s, s, s, s, s, -s, s, s,
      -s, -s, -s, -s, s, -s, s, s, -s, s, -s, -s,
      -s, s, -s, -s, s, s, s, s, s, s, s, -s,
      -s, -s, -s, s, -s, -s, s, -s, s, -s, -s, s,
      s, -s, -s, s, s, -s, s, s, s, s, -s, s,
      -s, -s, -s, -s, -s, s, -s, s, s, -s, s, -s
    ]);
    var indices = new Uint16Array([
      0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7, 8, 9, 10, 8, 10, 11,
      12, 13, 14, 12, 14, 15, 16, 17, 18, 16, 18, 19, 20, 21, 22, 20, 22, 23
    ]);
    var faceNumbers = [1, 6, 2, 5, 3, 4];
    var uvs = new Float32Array(24 * 2);

    for (var face = 0; face < 6; face++) {
      var uv = getUVForNumber(faceNumbers[face], cols, rows);
      var offset = face * 8;
      uvs[offset + 0] = uv.u0; uvs[offset + 1] = uv.v1;
      uvs[offset + 2] = uv.u1; uvs[offset + 3] = uv.v1;
      uvs[offset + 4] = uv.u1; uvs[offset + 5] = uv.v0;
      uvs[offset + 6] = uv.u0; uvs[offset + 7] = uv.v0;
    }

    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    geometry.computeVertexNormals();
    return geometry;
  }

  function createD8Geometry(atlasInfo) {
    var cols = atlasInfo.cols, rows = atlasInfo.rows;
    var a = 1 / Math.sqrt(2);
    var vertices = new Float32Array([
      0, a, 0, -a, 0, 0, 0, 0, a, 0, a, 0, 0, 0, a, a, 0, 0,
      0, a, 0, a, 0, 0, 0, 0, -a, 0, a, 0, 0, 0, -a, -a, 0, 0,
      0, -a, 0, 0, 0, a, -a, 0, 0, 0, -a, 0, a, 0, 0, 0, 0, a,
      0, -a, 0, 0, 0, -a, a, 0, 0, 0, -a, 0, -a, 0, 0, 0, 0, -a
    ]);
    var indices = new Uint16Array([
      0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
      12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23
    ]);
    var uvs = new Float32Array(24 * 2);
    
    for (var face = 0; face < 8; face++) {
      var uv = getUVForNumber(face + 1, cols, rows);
      var offset = face * 6;
      uvs[offset + 0] = (uv.u0 + uv.u1) / 2; uvs[offset + 1] = uv.v0;
      uvs[offset + 2] = uv.u0; uvs[offset + 3] = uv.v1;
      uvs[offset + 4] = uv.u1; uvs[offset + 5] = uv.v1;
    }

    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    geometry.computeVertexNormals();
    return geometry;
  }

  function createD10Geometry(atlasInfo) {
    var cols = atlasInfo.cols, rows = atlasInfo.rows;
    var h = 1.2, r = 0.7;
    var vertices = [], uvs = [], indices = [];
    var top = [0, h / 2, 0], bottom = [0, -h / 2, 0];
    var middle = [];
    
    for (var i = 0; i < 10; i++) {
      var angle = (i * Math.PI * 2) / 10;
      middle.push([Math.cos(angle) * r, 0, Math.sin(angle) * r]);
    }

    for (var i = 0; i < 5; i++) {
      var uv = getUVForNumber(i + 1, cols, rows);
      var startIdx = vertices.length / 3;
      vertices.push(top[0], top[1], top[2], middle[i * 2][0], middle[i * 2][1], middle[i * 2][2],
        middle[(i * 2 + 1) % 10][0], middle[(i * 2 + 1) % 10][1], middle[(i * 2 + 1) % 10][2]);
      uvs.push((uv.u0 + uv.u1) / 2, uv.v0, uv.u0, uv.v1, uv.u1, uv.v1);
      indices.push(startIdx, startIdx + 1, startIdx + 2);
    }

    for (var i = 0; i < 5; i++) {
      var uv = getUVForNumber(i + 6, cols, rows);
      var startIdx = vertices.length / 3;
      vertices.push(bottom[0], bottom[1], bottom[2], middle[(i * 2 + 1) % 10][0], middle[(i * 2 + 1) % 10][1],
        middle[(i * 2 + 1) % 10][2], middle[i * 2][0], middle[i * 2][1], middle[i * 2][2]);
      uvs.push((uv.u0 + uv.u1) / 2, uv.v0, uv.u0, uv.v1, uv.u1, uv.v1);
      indices.push(startIdx, startIdx + 1, startIdx + 2);
    }

    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(vertices), 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
    geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(indices), 1));
    geometry.computeVertexNormals();
    return geometry;
  }

  function createD12Geometry(atlasInfo) {
    var cols = atlasInfo.cols, rows = atlasInfo.rows;
    var phi = (1 + Math.sqrt(5)) / 2, a = 1 / Math.sqrt(3), b = a / phi, c = a * phi;
    var v = [
      [-a, -a, -a], [-a, -a, a], [-a, a, -a], [-a, a, a], [a, -a, -a], [a, -a, a], [a, a, -a], [a, a, a],
      [0, -b, -c], [0, -b, c], [0, b, -c], [0, b, c], [-b, -c, 0], [-b, c, 0], [b, -c, 0], [b, c, 0],
      [-c, 0, -b], [-c, 0, b], [c, 0, -b], [c, 0, b]
    ];
    var faces = [
      [0, 8, 4, 14, 12], [0, 12, 17, 1, 9], [0, 9, 5, 19, 14], [4, 8, 10, 6, 18],
      [4, 18, 19, 5, 14], [1, 17, 16, 2, 3], [1, 3, 11, 9, 5], [2, 16, 17, 12, 13],
      [2, 13, 15, 6, 10], [3, 2, 10, 8, 0], [7, 11, 3, 13, 15], [7, 15, 6, 18, 19]
    ];
    var vertices = [], uvs = [], indices = [];

    for (var faceIdx = 0; faceIdx < faces.length; faceIdx++) {
      var face = faces[faceIdx];
      var uv = getUVForNumber(faceIdx + 1, cols, rows);
      var startIdx = vertices.length / 3;
      var center = [0, 0, 0];
      
      for (var j = 0; j < face.length; j++) {
        center[0] += v[face[j]][0];
        center[1] += v[face[j]][1];
        center[2] += v[face[j]][2];
      }
      center[0] /= 5; center[1] /= 5; center[2] /= 5;

      vertices.push(center[0], center[1], center[2]);
      uvs.push((uv.u0 + uv.u1) / 2, (uv.v0 + uv.v1) / 2);

      for (var j = 0; j < face.length; j++) {
        vertices.push(v[face[j]][0], v[face[j]][1], v[face[j]][2]);
        uvs.push(uv.u0 + (uv.u1 - uv.u0) * Math.random(), uv.v0 + (uv.v1 - uv.v0) * Math.random());
      }

      for (var j = 0; j < 5; j++) {
        indices.push(startIdx, startIdx + 1 + j, startIdx + 1 + ((j + 1) % 5));
      }
    }

    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(vertices), 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
    geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(indices), 1));
    geometry.computeVertexNormals();
    return geometry;
  }

  function createD20Geometry(atlasInfo) {
    var cols = atlasInfo.cols, rows = atlasInfo.rows;
    var t = (1 + Math.sqrt(5)) / 2;
    var vBase = [
      [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
      [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]
    ];
    var faces = [
      [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2],
      [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
      [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]
    ];
    var vertices = [], uvs = [], indices = [];

    for (var faceIdx = 0; faceIdx < faces.length; faceIdx++) {
      var face = faces[faceIdx];
      var uv = getUVForNumber(faceIdx + 1, cols, rows);
      var startIdx = vertices.length / 3;

      for (var j = 0; j < face.length; j++) {
        vertices.push(vBase[face[j]][0], vBase[face[j]][1], vBase[face[j]][2]);
        if (j === 0) uvs.push((uv.u0 + uv.u1) / 2, uv.v0);
        else if (j === 1) uvs.push(uv.u0, uv.v1);
        else uvs.push(uv.u1, uv.v1);
      }
      indices.push(startIdx, startIdx + 1, startIdx + 2);
    }

    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(vertices), 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
    geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(indices), 1));
    geometry.computeVertexNormals();
    return geometry;
  }

  function buildGeometry(sides, atlasInfo) {
    switch (sides) {
      case 4: return createD4Geometry(atlasInfo);
      case 6: return createD6Geometry(atlasInfo);
      case 8: return createD8Geometry(atlasInfo);
      case 10: return createD10Geometry(atlasInfo);
      case 12: return createD12Geometry(atlasInfo);
      case 20: return createD20Geometry(atlasInfo);
      default: return createD6Geometry(atlasInfo);
    }
  }

  // ============================================================================
  // DIE CLASS
  // ============================================================================

  function Die(container, sides, opts) {
    this.container = container;
    this.sides = sides || 6;
    this.color = (opts && opts.color !== undefined) ? opts.color : 0x4f46e5;
    this.showValue = (opts && opts.showValue !== undefined) ? opts.showValue : true;
    this.currentValue = 1;
    this.isRolling = false;
    this.targetRotation = null;
    this.init();
  }

  Die.prototype.init = function () {
    var w = this.container.clientWidth || 200;
    var h = this.container.clientHeight || 200;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 1000);
    this.camera.position.set(0, 0, 4);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setSize(w, h);
    this.renderer.setClearColor(0x000000, 0);
    this.container.appendChild(this.renderer.domElement);

    var ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    this.scene.add(ambientLight);

    var directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(3, 5, 3);
    this.scene.add(directionalLight);

    this.buildMesh();

    if (this.showValue) {
      this.label = document.createElement('div');
      this.label.style.cssText = 'position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);' +
        'font-size:3rem;font-weight:900;color:#fff;text-shadow:0 0 20px rgba(79,70,229,0.8);pointer-events:none;z-index:10';
      this.label.textContent = this.currentValue;
      this.container.style.position = 'relative';
      this.container.appendChild(this.label);
    }

    this.animate();
  };

  Die.prototype.buildMesh = function () {
    if (this.mesh) {
      this.scene.remove(this.mesh);
      if (this.mesh.geometry) this.mesh.geometry.dispose();
      if (this.mesh.material) {
        if (this.mesh.material.map) this.mesh.material.map.dispose();
        this.mesh.material.dispose();
      }
    }

    var atlasInfo = createTextureAtlas(this.sides);
    var geometry = buildGeometry(this.sides, atlasInfo);
    var material = new THREE.MeshStandardMaterial({
      map: atlasInfo.texture,
      color: this.color,
      metalness: 0.1,
      roughness: 0.5
    });

    this.mesh = new THREE.Mesh(geometry, material);
    this.mesh.castShadow = true;
    this.scene.add(this.mesh);
  };

  Die.prototype.animate = function () {
    var self = this;
    requestAnimationFrame(function () { self.animate(); });

    if (self.isRolling) {
      self.mesh.rotation.x += 0.2;
      self.mesh.rotation.y += 0.2;
      self.mesh.rotation.z += 0.1;
    } else if (self.targetRotation) {
      var dx = self.targetRotation.x - self.mesh.rotation.x;
      var dy = self.targetRotation.y - self.mesh.rotation.y;
      var dz = self.targetRotation.z - self.mesh.rotation.z;

      self.mesh.rotation.x += dx * 0.1;
      self.mesh.rotation.y += dy * 0.1;
      self.mesh.rotation.z += dz * 0.1;

      if (Math.abs(dx) < 0.01 && Math.abs(dy) < 0.01 && Math.abs(dz) < 0.01) {
        self.mesh.rotation.set(self.targetRotation.x, self.targetRotation.y, self.targetRotation.z);
        self.targetRotation = null;
      }
    } else {
      self.mesh.rotation.y += 0.005;
    }

    self.renderer.render(self.scene, self.camera);
  };

  Die.prototype.setValue = function (value) {
    this.currentValue = value;
    if (this.label) this.label.textContent = value;
  };

  Die.prototype.setSides = function (nextSides) {
    var self = this;
    this.isRolling = true;
    setTimeout(function () {
      self.sides = nextSides;
      self.buildMesh();
      self.isRolling = false;
      self.setValue(1);
    }, 600);
  };

  Die.prototype.rollTo = function (value) {
    var self = this;
    this.isRolling = true;
    this.currentValue = value;
    setTimeout(function () {
      self.isRolling = false;
      self.setValue(value);
      self.targetRotation = self.getFaceRotation(self.sides, value);
    }, 1500);
  };

  Die.prototype.getFaceRotation = function (sides, value) {
    if (sides === 6) {
      var rotations = {
        1: { x: 0, y: 0, z: 0 }, 2: { x: 0, y: 0, z: Math.PI / 2 },
        3: { x: 0, y: 0, z: Math.PI }, 4: { x: 0, y: 0, z: -Math.PI / 2 },
        5: { x: Math.PI / 2, y: 0, z: 0 }, 6: { x: -Math.PI / 2, y: 0, z: 0 }
      };
      return rotations[value] || { x: 0, y: 0, z: 0 };
    }
    return { x: Math.random() * Math.PI * 2, y: Math.random() * Math.PI * 2, z: Math.random() * Math.PI * 2 };
  };

  Die.prototype.destroy = function () {
    if (this.renderer && this.renderer.domElement && this.renderer.domElement.parentNode) {
      this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
    }
    if (this.label && this.label.parentNode) {
      this.label.parentNode.removeChild(this.label);
    }
    if (this.mesh) {
      this.scene.remove(this.mesh);
      if (this.mesh.geometry) this.mesh.geometry.dispose();
      if (this.mesh.material) {
        if (this.mesh.material.map) this.mesh.material.map.dispose();
        this.mesh.material.dispose();
      }
    }
  };

  // ============================================================================
  // PUBLIC API
  // ============================================================================

  function safeCreate(container, sides, opts) {
    try {
      var die = new Die(container, sides, opts);
      instances.push(die);
      return die;
    } catch (err) {
      console.error('[Dice3D] Error creating die:', err);
      return null;
    }
  }

  function get(index) {
    return instances[index] || null;
  }

  window.Dice3D = {
    create: safeCreate,
    get: get
  };

  console.log('[Dice3D] Loaded successfully');
})();
