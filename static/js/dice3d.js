(function () {
    const instances = new WeakMap();

    function buildGeometry(sides) {
        switch (sides) {
            case 4:
                return new THREE.TetrahedronGeometry(0.9);
            case 6:
                return new THREE.BoxGeometry(1, 1, 1);
            case 8:
                return new THREE.OctahedronGeometry(0.9);
            case 10:
                return new THREE.CylinderGeometry(0.75, 0.75, 1, 10, 1);
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
