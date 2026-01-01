(function () {
    const instances = new WeakMap();

    function createDecahedronGeometry(radius) {
        const geometry = new THREE.BufferGeometry();
        const vertices = new Float32Array([
            0.6495190528, 0.5590169944, 0.2,
            0.6495190528, -0.5590169944, 0.2,
            0.2, 0.5590169944, 0.6495190528,
            0.2, -0.5590169944, 0.6495190528,
            -0.2, 0.5590169944, 0.6495190528,
            -0.2, -0.5590169944, 0.6495190528,
            -0.6495190528, 0.5590169944, 0.2,
            -0.6495190528, -0.5590169944, 0.2,
            0.2, 0.5590169944, -0.6495190528,
            0.2, -0.5590169944, -0.6495190528,
            -0.2, 0.5590169944, -0.6495190528,
            -0.2, -0.5590169944, -0.6495190528,
            0.6495190528, 0.5590169944, -0.2,
            0.6495190528, -0.5590169944, -0.2,
            -0.6495190528, 0.5590169944, -0.2,
            -0.6495190528, -0.5590169944, -0.2,
        ]);
        const indices = new Uint16Array([
            0, 1, 2, 1, 3, 2,
            2, 3, 4, 3, 5, 4,
            4, 5, 6, 5, 7, 6,
            6, 7, 0, 7, 1, 0,
            8, 9, 10, 9, 11, 10,
            10, 11, 12, 11, 13, 12,
            12, 13, 14, 13, 15, 14,
            14, 15, 8, 15, 9, 8,
            0, 2, 10, 2, 4, 10,
            2, 4, 8, 4, 6, 8,
            4, 6, 12, 6, 14, 12,
            6, 0, 12, 0, 10, 12,
            1, 3, 11, 3, 5, 11,
            3, 5, 13, 5, 7, 13,
            5, 7, 15, 7, 9, 15,
            7, 1, 15, 1, 11, 15,
        ]);
        geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
        geometry.setIndex(indices);
        geometry.computeVertexNormals();
        return geometry;
    }

    function buildGeometry(sides) {
        switch (sides) {
            case 4:
                return new THREE.TetrahedronGeometry(0.9);
            case 6:
                return new THREE.BoxGeometry(1, 1, 1);
            case 8:
                return new THREE.OctahedronGeometry(0.9);
            case 10:
                return createDecahedronGeometry(0.9);
            case 12:
                return new THREE.DodecahedronGeometry(0.95);
            case 20:
                return new THREE.IcosahedronGeometry(0.95);
            default:
                return new THREE.BoxGeometry(1, 1, 1);
        }
    }

    function createContainer(container, showValue) {
        container.innerHTML = '';
        container.classList.add('dice3d-container');

        const canvas = document.createElement('canvas');
        canvas.className = 'dice3d-canvas';
        container.appendChild(canvas);

        let label = null;
        if (showValue) {
            label = document.createElement('div');
            label.className = 'dice3d-label';
            container.appendChild(label);
        }

        return { canvas, label };
    }

    function create(container, sides, options = {}) {
        if (!container || !window.THREE) return null;

        const showValue = options.showValue !== false;
        const { canvas, label } = createContainer(container, showValue);
        const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
        camera.position.set(0, 0, 3.2);

        const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
        const keyLight = new THREE.DirectionalLight(0xffffff, 0.9);
        keyLight.position.set(3, 4, 6);
        scene.add(ambientLight, keyLight);

        const material = new THREE.MeshStandardMaterial({
            color: options.color || 0x4f46e5,
            roughness: 0.3,
            metalness: 0.15
        });
        const mesh = new THREE.Mesh(buildGeometry(sides), material);
        scene.add(mesh);

        const state = {
            container,
            renderer,
            scene,
            camera,
            mesh,
            label,
            sides,
            spinUntil: 0
        };

        function resize() {
            const width = container.clientWidth || 1;
            const height = container.clientHeight || 1;
            renderer.setSize(width, height, false);
            camera.aspect = width / height;
            camera.updateProjectionMatrix();
        }

        function animate(now) {
            if (state.spinUntil > now) {
                mesh.rotation.x += 0.14;
                mesh.rotation.y += 0.18;
            } else {
                mesh.rotation.x += 0.006;
                mesh.rotation.y += 0.008;
            }
            renderer.render(scene, camera);
            requestAnimationFrame(animate);
        }

        resize();
        window.addEventListener('resize', resize);
        requestAnimationFrame(animate);

        const instance = {
            setSides(nextSides) {
                if (!nextSides || nextSides === state.sides) return;
                state.sides = nextSides;
                state.mesh.geometry.dispose();
                state.mesh.geometry = buildGeometry(nextSides);
                state.spinUntil = performance.now() + 400;
            },
            setValue(value) {
                if (state.label) state.label.textContent = value;
            },
            rollTo(value) {
                if (state.label) state.label.textContent = value;
                state.spinUntil = performance.now() + 700;
            },
            resize
        };

        instances.set(container, instance);
        return instance;
    }

    function get(container) {
        return instances.get(container) || null;
    }

    function safeCreate(container, sides, options = {}) {
        try {
            return create(container, sides, options);
        } catch (err) {
            if (container) {
                container.textContent = `d${sides}`;
                container.classList.add('dice3d-fallback');
            }
            return null;
        }
    }

    window.Dice3D = { create: safeCreate, get };
})();
