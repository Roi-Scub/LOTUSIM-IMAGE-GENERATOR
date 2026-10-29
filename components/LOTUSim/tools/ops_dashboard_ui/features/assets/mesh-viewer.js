/* Local-only mesh inspection. Vendor source and MIT notice: /vendor/three/provenance.json.
 * This is not a Unity renderer, a physics simulator, or a license approval tool.
 */
import * as THREE from '/vendor/three/three.module.js';
import { OrbitControls } from '/vendor/three/addons/controls/OrbitControls.js';
import { OBJLoader } from '/vendor/three/addons/loaders/OBJLoader.js';
import { MTLLoader } from '/vendor/three/addons/loaders/MTLLoader.js';
import { STLLoader } from '/vendor/three/addons/loaders/STLLoader.js';
import { GLTFLoader } from '/vendor/three/addons/loaders/GLTFLoader.js';
import { ColladaLoader } from '/vendor/three/addons/loaders/ColladaLoader.js';

const MAX_PREVIEW_BYTES = 96 * 1024 * 1024;
const FILE_PREFIX = '/api/assets/files/';
const abortError = () => new DOMException('Aperçu remplacé ou fermé.', 'AbortError');

function localFile(value) {
  if (typeof value !== 'string' || !value || value.includes('\\'))
    throw new Error('Fichier 3D local invalide.');
  const url = new URL(value, window.location.origin);
  if (
    url.origin !== window.location.origin ||
    !url.pathname.startsWith(FILE_PREFIX) ||
    url.username ||
    url.password
  ) {
    throw new Error('La prévisualisation ne peut charger que les fichiers locaux de ce modèle.');
  }
  url.hash = '';
  return url.href;
}

function finiteVector(values, fallback) {
  return Array.isArray(values) && values.length >= 3 && values.slice(0, 3).every(Number.isFinite)
    ? values.slice(0, 3)
    : fallback;
}

function release(object) {
  if (!object) return;
  const geometries = new Set(),
    materials = new Set(),
    textures = new Set();
  object.traverse((child) => {
    if (child.geometry) geometries.add(child.geometry);
    for (const material of Array.isArray(child.material)
      ? child.material
      : child.material
        ? [child.material]
        : []) {
      materials.add(material);
      for (const value of Object.values(material)) if (value?.isTexture) textures.add(value);
    }
  });
  textures.forEach((texture) => texture.dispose());
  materials.forEach((material) => material.dispose());
  geometries.forEach((geometry) => geometry.dispose());
  object.removeFromParent();
}

function primitiveScene(shapes) {
  if (!Array.isArray(shapes) || !shapes.length || shapes.length > 128)
    throw new Error('Géométrie simplifiée non disponible.');
  const group = new THREE.Group();
  for (const shape of shapes) {
    let geometry;
    if (
      shape.type === 'cylinder' &&
      Number.isFinite(shape.radius) &&
      shape.radius > 0 &&
      Number.isFinite(shape.length) &&
      shape.length > 0
    ) {
      geometry = new THREE.CylinderGeometry(shape.radius, shape.radius, shape.length, 48);
      geometry.rotateX(Math.PI / 2); // SDF cylinders have their axis along Z.
    } else if (shape.type === 'sphere' && Number.isFinite(shape.radius) && shape.radius > 0) {
      geometry = new THREE.SphereGeometry(shape.radius, 36, 24);
    } else if (shape.type === 'box') {
      const dimensions = finiteVector(shape.size, [1, 1, 1]);
      if (dimensions.some((value) => value <= 0)) continue;
      geometry = new THREE.BoxGeometry(...dimensions);
    } else continue;
    const rgba = Array.isArray(shape.color) ? shape.color : [0.77, 0.35, 0.12, 1];
    const rgb = finiteVector(rgba, [0.77, 0.35, 0.12]).map((value) =>
      THREE.MathUtils.clamp(value, 0, 1),
    );
    const alpha = Number.isFinite(rgba[3]) ? THREE.MathUtils.clamp(rgba[3], 0, 1) : 1;
    const material = new THREE.MeshStandardMaterial({
      color: new THREE.Color(...rgb),
      roughness: 0.53,
      metalness: 0.12,
      opacity: alpha,
      transparent: alpha < 1,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(...finiteVector(shape.position, [0, 0, 0]));
    mesh.rotation.set(...finiteVector(shape.rotation, [0, 0, 0]), 'ZYX');
    group.add(mesh);
  }
  if (!group.children.length) throw new Error('Aucune primitive 3D prise en charge.');
  return group;
}

export class MeshPreview {
  constructor(container) {
    if (!(container instanceof Element)) throw new Error('Zone de prévisualisation introuvable.');
    this.container = container;
    this.disposed = false;
    this.generation = 0;
    this.object = null;
    this.grid = null;
    this.abortController = null;
    this.manager = null;
    this.isWireframe = false;
    this.renderFrame = 0;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b1723);
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.01, 1e6);
    this.camera.position.set(6, 4, 7);
    try {
      // The small inspection canvas can be captured reliably by local QA and
      // accessibility tooling after rendering; it is not a dataset camera.
      this.renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: false,
        powerPreference: 'low-power',
        preserveDrawingBuffer: true,
      });
    } catch (_) {
      throw new Error(
        'WebGL est indisponible dans ce navigateur. Les fichiers et informations restent consultables.',
      );
    }
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.2;
    this.renderer.domElement.setAttribute(
      'aria-label',
      'Aperçu 3D interactif du modèle sélectionné',
    );
    this.renderer.domElement.tabIndex = 0;
    this.renderer.domElement.style.display = 'block';
    this.renderer.domElement.style.width = '100%';
    this.renderer.domElement.style.height = '100%';
    container.append(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = false; // Render only on changes, not continuously while idle.
    this.controls.screenSpacePanning = true;
    this.controls.minDistance = 0.03;
    this.controls.maxPolarAngle = Math.PI * 0.97;
    this.onControlChange = () => this.render();
    this.controls.addEventListener('change', this.onControlChange);
    this.scene.add(new THREE.HemisphereLight(0xdbefff, 0x304456, 2.3));
    const key = new THREE.DirectionalLight(0xffe5c2, 3.2);
    key.position.set(3, 7, 5);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0x83cfff, 1.3);
    fill.position.set(-5, 3, -4);
    this.scene.add(fill);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.onContextLost = (event) => {
      event.preventDefault();
      container.dispatchEvent(
        new CustomEvent('mesh-preview-error', {
          detail: 'Contexte graphique perdu ; recharge cet aperçu.',
        }),
      );
    };
    this.renderer.domElement.addEventListener('webglcontextlost', this.onContextLost);
    this.resize();
  }

  resize() {
    if (this.disposed) return;
    const width = Math.max(1, this.container.clientWidth);
    const height = Math.max(1, this.container.clientHeight);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
    this.render();
  }

  render() {
    if (this.disposed || this.renderFrame) return;
    this.renderFrame = requestAnimationFrame(() => {
      this.renderFrame = 0;
      if (!this.disposed) this.renderer.render(this.scene, this.camera);
    });
  }

  cancel() {
    this.generation++;
    this.abortController?.abort();
    this.manager?.abort();
    this.abortController = null;
    this.manager = null;
  }

  async load(preview) {
    if (this.disposed) throw abortError();
    this.cancel();
    const generation = this.generation;
    const controller = new AbortController();
    this.abortController = controller;
    release(this.object);
    this.object = null;
    release(this.grid);
    this.grid = null;
    this.render();
    const format = String(preview?.format || '').toLowerCase();
    if (!['obj', 'glb', 'gltf', 'stl', 'dae', 'sdf'].includes(format))
      throw new Error('Format de prévisualisation non pris en charge.');
    const allowed = new Set();
    const entry = format === 'sdf' ? null : localFile(preview.url);
    if (entry) allowed.add(entry);
    for (const value of Object.values(preview.files || {}))
      if (typeof value === 'string') allowed.add(localFile(value));
    const materialURL = preview.mtlUrl ? localFile(preview.mtlUrl) : null;
    if (materialURL) allowed.add(materialURL);
    const manager = new THREE.LoadingManager();
    this.manager = manager;
    const warnings = [];
    manager.onLoad = () => {
      // OBJ geometry is ready before asynchronous MTL textures finish. There
      // is no idle animation loop, so request another frame when they arrive.
      if (generation === this.generation && !this.disposed) this.render();
    };
    manager.onError = () => {
      if (warnings.length < 10)
        warnings.push('Une texture ou ressource secondaire n’a pas pu être chargée.');
    };
    manager.setURLModifier((value) => {
      // Embedded glTF buffers and images are data, never executable markup.
      if (
        /^data:(?:application\/octet-stream|application\/gltf-buffer|image\/(?:png|jpeg|webp));base64,/i.test(
          value,
        )
      )
        return value;
      if (value.startsWith('blob:') && new URL(value).origin === window.location.origin)
        return value;
      const url = localFile(new URL(value, entry || window.location.href).href);
      if (!allowed.has(url))
        throw new Error('Ressource externe ou non déclarée refusée par la prévisualisation.');
      return url;
    });
    const read = async (url, binary = false) => {
      const response = await fetch(url, { signal: controller.signal, credentials: 'same-origin' });
      if (!response.ok)
        throw new Error('Le fichier 3D local est indisponible (HTTP ' + response.status + ').');
      const length = Number(response.headers.get('Content-Length'));
      if (length > MAX_PREVIEW_BYTES)
        throw new Error('Ce fichier dépasse la limite de prévisualisation de 96 Mio.');
      const buffer = await response.arrayBuffer();
      if (buffer.byteLength > MAX_PREVIEW_BYTES)
        throw new Error('Ce fichier dépasse la limite de prévisualisation de 96 Mio.');
      if (generation !== this.generation || this.disposed) throw abortError();
      return binary ? buffer : new TextDecoder().decode(buffer);
    };
    let object = null;
    try {
      if (format === 'sdf') {
        object = primitiveScene(preview.shapes);
      } else if (format === 'obj') {
        const text = await read(entry);
        const loader = new OBJLoader(manager);
        if (materialURL) {
          const mtl = await read(materialURL);
          const materials = new MTLLoader(manager).parse(mtl, new URL('.', materialURL).href);
          materials.preload();
          loader.setMaterials(materials);
        }
        // Yield once so the visible loading indicator paints before parsing a large OBJ.
        await new Promise((resolve) => setTimeout(resolve, 0));
        if (generation !== this.generation || this.disposed) throw abortError();
        object = loader.parse(text);
      } else if (format === 'stl') {
        const geometry = new STLLoader(manager).parse(await read(entry, true));
        object = new THREE.Mesh(
          geometry,
          new THREE.MeshStandardMaterial({
            color: 0xacc3d1,
            roughness: 0.55,
            metalness: 0.2,
            vertexColors: geometry.hasColors === true,
          }),
        );
      } else if (format === 'dae') {
        object = new ColladaLoader(manager).parse(
          await read(entry),
          new URL('.', entry).href,
        ).scene;
      } else {
        const data = await read(entry, true);
        const gltf = await new GLTFLoader(manager).parseAsync(data, new URL('.', entry).href);
        object = gltf.scene;
      }
      if (generation !== this.generation || this.disposed) {
        release(object);
        throw abortError();
      }
      if (!object) throw new Error('Le fichier ne contient aucune scène 3D exploitable.');
      const wrapper = new THREE.Group();
      wrapper.add(object);
      // ColladaLoader already honors its <up_axis>; glTF is Y-up by specification.
      if (
        String(preview.upAxis).toUpperCase() === 'Z' &&
        format !== 'dae' &&
        !['gltf', 'glb'].includes(format)
      )
        wrapper.rotation.x = -Math.PI / 2;
      wrapper.updateMatrixWorld(true);
      const bounds = new THREE.Box3().setFromObject(wrapper);
      if (bounds.isEmpty()) {
        release(wrapper);
        throw new Error('Aucune géométrie visible dans ce fichier.');
      }
      const size = bounds.getSize(new THREE.Vector3());
      if (
        ![size.x, size.y, size.z].every(Number.isFinite) ||
        Math.max(size.x, size.y, size.z) < 1e-9
      ) {
        release(wrapper);
        throw new Error('Dimensions géométriques invalides ou nulles.');
      }
      const centre = bounds.getCenter(new THREE.Vector3());
      wrapper.position.sub(centre);
      wrapper.updateMatrixWorld(true);
      let vertices = 0,
        triangles = 0;
      wrapper.traverse((child) => {
        if (!child.isMesh || !child.geometry) return;
        vertices += child.geometry.attributes.position?.count || 0;
        triangles +=
          (child.geometry.index?.count || child.geometry.attributes.position?.count || 0) / 3;
        for (const material of Array.isArray(child.material) ? child.material : [child.material]) {
          if (material) {
            material.wireframe = this.isWireframe;
            material.needsUpdate = true;
          }
        }
      });
      if (!triangles) {
        release(wrapper);
        throw new Error('Le fichier ne contient pas de faces triangulées visibles.');
      }
      this.object = wrapper;
      this.scene.add(wrapper);
      const span = Math.max(size.x, size.y, size.z);
      this.grid = new THREE.GridHelper(span * 1.8, 20, 0x3b6374, 0x1e3948);
      this.grid.position.y = -size.y / 2 - span * 0.004;
      this.grid.material.transparent = true;
      this.grid.material.opacity = 0.55;
      this.scene.add(this.grid);
      this.fit(size);
      return {
        triangles: Math.round(triangles),
        vertices,
        bounds: { x: size.x, y: size.y, z: size.z },
        warnings,
      };
    } catch (error) {
      if (object && object.parent !== this.object) release(object);
      if (generation !== this.generation || controller.signal.aborted || this.disposed)
        throw abortError();
      throw error;
    }
  }

  fit(size) {
    const span = Math.max(size.x, size.y, size.z);
    const vertical = THREE.MathUtils.degToRad(this.camera.fov);
    const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * this.camera.aspect);
    const distance = (span / (2 * Math.tan(Math.min(vertical, horizontal) / 2))) * 1.55;
    this.camera.near = Math.max(span / 10000, 0.00001);
    this.camera.far = Math.max(distance * 40, span * 100);
    this.camera.updateProjectionMatrix();
    this.camera.position.set(1, 0.58, 1.15).normalize().multiplyScalar(distance);
    this.controls.target.set(0, 0, 0);
    this.controls.minDistance = Math.max(span * 0.015, 0.0001);
    this.controls.maxDistance = distance * 12;
    this.controls.update();
    this.controls.saveState();
    this.render();
  }

  reset() {
    if (!this.disposed) {
      this.controls.reset();
      this.render();
    }
  }

  wireframe(enabled) {
    this.isWireframe = Boolean(enabled);
    this.object?.traverse((child) => {
      for (const material of Array.isArray(child.material)
        ? child.material
        : child.material
          ? [child.material]
          : []) {
        material.wireframe = this.isWireframe;
        material.needsUpdate = true;
      }
    });
    this.render();
  }

  setWireframe(enabled) {
    this.wireframe(enabled);
  }

  dispose() {
    if (this.disposed) return;
    this.cancel();
    this.disposed = true;
    cancelAnimationFrame(this.renderFrame);
    this.renderFrame = 0;
    this.resizeObserver.disconnect();
    this.controls.removeEventListener('change', this.onControlChange);
    this.controls.dispose();
    this.renderer.domElement.removeEventListener('webglcontextlost', this.onContextLost);
    release(this.object);
    release(this.grid);
    this.scene.clear();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.renderer.domElement.remove();
  }
}
