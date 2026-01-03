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

      ctx.strokeStyle = '#cccccc';
      ctx.lineWidth = 4;
      ctx.strokeRect(x + 2, y + 2, tileSize - 4, tileSize - 4);

      ctx.fillStyle = '#1a1a2e';
      ctx.font = 'bold ' + (tileSize * 0.55) + 'px Arial';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      
      var text = i.toString();
      if (i === 6 || i === 9) text += '.';
      ctx.fillText(text, x + tileSize / 2, y + tileSize / 2);
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
      v0: 1 - (row + 1) / rows,
      u1: (col + 1) / cols,
      v1: 1 - row / rows
    };
  }

  // ============================================================================
  // GEOMETRY HELPERS
  // ============================================================================

  function normalize(v) {
    var len = Math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2]);
    return [v[0]/len, v[1]/len, v[2]/len];
  }

  function addTriangle(verts, uvs, inds, v0, v1, v2, uv0, uv1, uv2) {
    var idx = verts.length / 3;
    verts.push(v0[0], v0[1], v0[2]);
    verts.push(v1[0], v1[1], v1[2]);
    verts.push(v2[0], v2[1], v2[2]);
    uvs.push(uv0[0], uv0[1]);
    uvs.push(uv1[0], uv1[1]);
    uvs.push(uv2[0], uv2[1]);
    inds.push(idx, idx+1, idx+2);
  }

  // ============================================================================
  // D4 - Tetrahedron
  // ============================================================================

  function createD4Geometry(atlasInfo) {
    var cols = atlasInfo.cols, rows = atlasInfo.rows;
    var verts = [], uvs = [], inds = [];
    
    var a = 1.0;
    var h = a * Math.sqrt(2/3);
    var r = a / Math.sqrt(3);
    
    var v = [
      [0, h, 0],
      [-a/2, -h/3, r],
      [a/2, -h/3, r],
      [0, -h/3, -r * 2]
    ];

    var faces = [
      [0, 1, 2, 1],
      [0, 2, 3, 2],
      [0, 3, 1, 3],
      [1, 3, 2, 4]
    ];

    for (var i = 0; i < faces.length; i++) {
      var f = faces[i];
      var uv = getUVForNumber(f[3], cols, rows);
      var cx = (uv.u0 + uv.u1) / 2;
      var cy = (uv.v0 + uv.v1) / 2;
      var rx = (uv.u1 - uv.u0) * 0.4;
      var ry = (uv.v1 - uv.v0) * 0.4;
      
      addTriangle(verts, uvs, inds,
        v[f[0]], v[f[1]], v[f[2]],
        [cx, cy + ry],
        [cx - rx, cy - ry],
        [cx + rx, cy - ry]
      );
    }

    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(verts), 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
    geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(inds), 1));
    geometry.computeVertexNormals();
    return geometry;
  }

  // ============================================================================
  // D6 - Cube
  // ============================================================================

  function createD6Geometry(atlasInfo) {
    var cols = atlasInfo.cols, rows = atlasInfo.rows;
    var verts = [], uvs = [], inds = [];
    var s = 0.9;

    var corners = [
      [-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s],
      [-s, -s, s], [s, -s, s], [s, s, s], [-s, s, s]
    ];

    var faces = [
      [4, 5, 6, 7, 1],
      [1, 0, 3, 2, 6],
      [5, 1, 2, 6, 3],
      [0, 4, 7, 3, 4],
      [7, 6, 2, 3, 2],
      [0, 1, 5, 4, 5]
    ];

    for (var i = 0; i < faces.length; i++) {
      var f = faces[i];
      var uv = getUVForNumber(f[4], cols, rows);
      var idx = verts.length / 3;
      
      verts.push(corners[f[0]][0], corners[f[0]][1], corners[f[0]][2]);
      verts.push(corners[f[1]][0], corners[f[1]][1], corners[f[1]][2]);
      verts.push(corners[f[2]][0], corners[f[2]][1], corners[f[2]][2]);
      verts.push(corners[f[3]][0], corners[f[3]][1], corners[f[3]][2]);
      
      uvs.push(uv.u0, uv.v0);
      uvs.push(uv.u1, uv.v0);
      uvs.push(uv.u1, uv.v1);
      uvs.push(uv.u0, uv.v1);
      
      inds.push(idx, idx+1, idx+2, idx, idx+2, idx+3);
    }

    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(verts), 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
    geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(inds), 1));
    geometry.computeVertexNormals();
    return geometry;
  }

  // ============================================================================
  // D8 - Octahedron
  // ============================================================================

  function createD8Geometry(atlasInfo) {
    var cols = atlasInfo.cols, rows = atlasInfo.rows;
    var verts = [], uvs = [], inds = [];
    var a = 1.0;

    var v = [
      [0, a, 0], [0, -a, 0],
      [a, 0, 0], [-a, 0, 0],
      [0, 0, a], [0, 0, -a]
    ];

    var faces = [
      [0, 4, 2, 1], [0, 2, 5, 2],
      [0, 5, 3, 3], [0, 3, 4, 4],
      [1, 2, 4, 5], [1, 5, 2, 6],
      [1, 3, 5, 7], [1, 4, 3, 8]
    ];

    for (var i = 0; i < faces.length; i++) {
      var f = faces[i];
      var uv = getUVForNumber(f[3], cols, rows);
      var cx = (uv.u0 + uv.u1) / 2;
      var cy = (uv.v0 + uv.v1) / 2;
      var rx = (uv.u1 - uv.u0) * 0.4;
      var ry = (uv.v1 - uv.v0) * 0.4;
      
      addTriangle(verts, uvs, inds,
        v[f[0]], v[f[1]], v[f[2]],
        [cx, cy + ry],
        [cx - rx, cy - ry],
        [cx + rx, cy - ry]
      );
    }

    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(verts), 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
    geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(inds), 1));
    geometry.computeVertexNormals();
    return geometry;
  }

  // ============================================================================
  // D10 - Pentagonal Trapezohedron (proper geometry)
  // ============================================================================

  function createD10Geometry(atlasInfo) {
    var cols = atlasInfo.cols, rows = atlasInfo.rows;
    var verts = [], uvs = [], inds = [];
    
    var n = 5;
    var h = 0.6;
    var r = 1.0;
    var twist = Math.PI / n;

    var top = [0, h * 1.5, 0];
    var bottom = [0, -h * 1.5, 0];
    
    var topRing = [];
    var bottomRing = [];
    
    for (var i = 0; i < n; i++) {
      var angle = (i * 2 * Math.PI) / n;
      topRing.push([Math.cos(angle) * r, h * 0.5, Math.sin(angle) * r]);
      bottomRing.push([Math.cos(angle + twist) * r, -h * 0.5, Math.sin(angle + twist) * r]);
    }

    for (var i = 0; i < n; i++) {
      var next = (i + 1) % n;
      
      var uv = getUVForNumber(i * 2 + 1, cols, rows);
      var cx = (uv.u0 + uv.u1) / 2;
      var cy = (uv.v0 + uv.v1) / 2;
      var rx = (uv.u1 - uv.u0) * 0.35;
      var ry = (uv.v1 - uv.v0) * 0.35;
      
      var idx = verts.length / 3;
      verts.push(top[0], top[1], top[2]);
      verts.push(topRing[next][0], topRing[next][1], topRing[next][2]);
      verts.push(topRing[i][0], topRing[i][1], topRing[i][2]);
      verts.push(bottomRing[i][0], bottomRing[i][1], bottomRing[i][2]);
      
      uvs.push(cx, cy + ry * 1.2);
      uvs.push(cx + rx, cy + ry * 0.3);
      uvs.push(cx - rx, cy + ry * 0.3);
      uvs.push(cx, cy - ry * 1.2);
      
      inds.push(idx, idx+1, idx+2, idx+1, idx+3, idx+2);
    }

    for (var i = 0; i < n; i++) {
      var next = (i + 1) % n;
      
      var uv = getUVForNumber(i * 2 + 2, cols, rows);
      var cx = (uv.u0 + uv.u1) / 2;
      var cy = (uv.v0 + uv.v1) / 2;
      var rx = (uv.u1 - uv.u0) * 0.35;
      var ry = (uv.v1 - uv.v0) * 0.35;
      
      var idx = verts.length / 3;
      verts.push(bottom[0], bottom[1], bottom[2]);
      verts.push(bottomRing[i][0], bottomRing[i][1], bottomRing[i][2]);
      verts.push(bottomRing[next][0], bottomRing[next][1], bottomRing[next][2]);
      verts.push(topRing[next][0], topRing[next][1], topRing[next][2]);
      
      uvs.push(cx, cy - ry * 1.2);
      uvs.push(cx - rx, cy - ry * 0.3);
      uvs.push(cx + rx, cy - ry * 0.3);
      uvs.push(cx, cy + ry * 1.2);
      
      inds.push(idx, idx+1, idx+2, idx+1, idx+3, idx+2);
    }

    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(verts), 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
    geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(inds), 1));
    geometry.computeVertexNormals();
    return geometry;
  }

  // ============================================================================
  // D12 - Dodecahedron (proper geometry)
  // ============================================================================

  function createD12Geometry(atlasInfo) {
    var cols = atlasInfo.cols, rows = atlasInfo.rows;
    var verts = [], uvs = [], inds = [];
    
    var phi = (1 + Math.sqrt(5)) / 2;
    var a = 1 / Math.sqrt(3);
    var b = a / phi;
    var c = a * phi;

    var v = [
      [a, a, a], [a, a, -a], [a, -a, a], [a, -a, -a],
      [-a, a, a], [-a, a, -a], [-a, -a, a], [-a, -a, -a],
      [0, b, c], [0, b, -c], [0, -b, c], [0, -b, -c],
      [b, c, 0], [b, -c, 0], [-b, c, 0], [-b, -c, 0],
      [c, 0, b], [c, 0, -b], [-c, 0, b], [-c, 0, -b]
    ];

    var faces = [
      [0, 8, 4, 14, 12, 1], [0, 16, 2, 10, 8, 2],
      [0, 12, 1, 17, 16, 3], [8, 10, 6, 18, 4, 4],
      [2, 16, 17, 3, 13, 5], [1, 12, 14, 5, 9, 6],
      [4, 18, 19, 5, 14, 7], [1, 9, 11, 3, 17, 8],
      [2, 13, 15, 6, 10, 9], [6, 15, 7, 19, 18, 10],
      [3, 11, 7, 15, 13, 11], [5, 19, 7, 11, 9, 12]
    ];

    for (var fi = 0; fi < faces.length; fi++) {
      var f = faces[fi];
      var uv = getUVForNumber(f[5], cols, rows);
      var cx = (uv.u0 + uv.u1) / 2;
      var cy = (uv.v0 + uv.v1) / 2;
      var rx = (uv.u1 - uv.u0) * 0.42;
      var ry = (uv.v1 - uv.v0) * 0.42;

      var center = [0, 0, 0];
      for (var j = 0; j < 5; j++) {
        center[0] += v[f[j]][0];
        center[1] += v[f[j]][1];
        center[2] += v[f[j]][2];
      }
      center[0] /= 5; center[1] /= 5; center[2] /= 5;

      var baseIdx = verts.length / 3;
      
      for (var j = 0; j < 5; j++) {
        verts.push(v[f[j]][0], v[f[j]][1], v[f[j]][2]);
        var angle = (j * 2 * Math.PI / 5) - Math.PI / 2;
        uvs.push(cx + Math.cos(angle) * rx, cy + Math.sin(angle) * ry);
      }
      
      verts.push(center[0], center[1], center[2]);
      uvs.push(cx, cy);
      var centerIdx = baseIdx + 5;

      for (var j = 0; j < 5; j++) {
        var next = (j + 1) % 5;
        inds.push(centerIdx, baseIdx + j, baseIdx + next);
      }
    }

    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(verts), 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
    geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(inds), 1));
    geometry.computeVertexNormals();
    return geometry;
  }

  // ============================================================================
  // D20 - Icosahedron
  // ============================================================================

  function createD20Geometry(atlasInfo) {
    var cols = atlasInfo.cols, rows = atlasInfo.rows;
    var verts = [], uvs = [], inds = [];
    
    var t = (1 + Math.sqrt(5)) / 2;
    var s = 1.0;

    var v = [
      normalize([-s, t*s, 0]), normalize([s, t*s, 0]),
      normalize([-s, -t*s, 0]), normalize([s, -t*s, 0]),
      normalize([0, -s, t*s]), normalize([0, s, t*s]),
      normalize([0, -s, -t*s]), normalize([0, s, -t*s]),
      normalize([t*s, 0, -s]), normalize([t*s, 0, s]),
      normalize([-t*s, 0, -s]), normalize([-t*s, 0, s])
    ];

    var faces = [
      [0, 11, 5, 1], [0, 5, 1, 2], [0, 1, 7, 3], [0, 7, 10, 4], [0, 10, 11, 5],
      [1, 5, 9, 6], [5, 11, 4, 7], [11, 10, 2, 8], [10, 7, 6, 9], [7, 1, 8, 10],
      [3, 9, 4, 11], [3, 4, 2, 12], [3, 2, 6, 13], [3, 6, 8, 14], [3, 8, 9, 15],
      [4, 9, 5, 16], [2, 4, 11, 17], [6, 2, 10, 18], [8, 6, 7, 19], [9, 8, 1, 20]
    ];

    for (var i = 0; i < faces.length; i++) {
      var f = faces[i];
      var uv = getUVForNumber(f[3], cols, rows);
      var cx = (uv.u0 + uv.u1) / 2;
      var cy = (uv.v0 + uv.v1) / 2;
      var rx = (uv.u1 - uv.u0) * 0.4;
      var ry = (uv.v1 - uv.v0) * 0.4;
      
      addTriangle(verts, uvs, inds,
        v[f[0]], v[f[1]], v[f[2]],
        [cx, cy + ry],
        [cx - rx, cy - ry],
        [cx + rx, cy - ry]
      );
    }

    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(verts), 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(uvs), 2));
    geometry.setIndex(new THREE.BufferAttribute(new Uint16Array(inds), 1));
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
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(0x000000, 0);
    this.container.appendChild(this.renderer.domElement);

    var ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
    this.scene.add(ambientLight);

    var directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(5, 5, 5);
    this.scene.add(directionalLight);

    var fillLight = new THREE.DirectionalLight(0xffffff, 0.3);
    fillLight.position.set(-3, -3, 3);
    this.scene.add(fillLight);

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
      metalness: 0.15,
      roughness: 0.4
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
      self.mesh.rotation.y += 0.25;
      self.mesh.rotation.z += 0.15;
    } else if (self.targetRotation) {
      var dx = self.targetRotation.x - self.mesh.rotation.x;
      var dy = self.targetRotation.y - self.mesh.rotation.y;
      var dz = self.targetRotation.z - self.mesh.rotation.z;

      self.mesh.rotation.x += dx * 0.12;
      self.mesh.rotation.y += dy * 0.12;
      self.mesh.rotation.z += dz * 0.12;

      if (Math.abs(dx) < 0.01 && Math.abs(dy) < 0.01 && Math.abs(dz) < 0.01) {
        self.mesh.rotation.set(self.targetRotation.x, self.targetRotation.y, self.targetRotation.z);
        self.targetRotation = null;
      }
    } else {
      self.mesh.rotation.y += 0.008;
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
        1: { x: 0, y: 0, z: 0 },
        2: { x: 0, y: -Math.PI/2, z: 0 },
        3: { x: Math.PI/2, y: 0, z: 0 },
        4: { x: -Math.PI/2, y: 0, z: 0 },
        5: { x: 0, y: Math.PI/2, z: 0 },
        6: { x: Math.PI, y: 0, z: 0 }
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
