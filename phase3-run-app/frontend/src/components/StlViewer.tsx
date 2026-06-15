import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

const REGION_COLORS = [0xd8d9dc, 0xc7cbd0, 0xdedbd5, 0xc9d3d5, 0xd5d0ca, 0xe1e2e4];

function decodeBase64(value: string) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

function colorForRegion(region: string, index: number) {
  const normalized = region.toLowerCase();
  if (normalized.includes("impeller")) return 0xb9c8cb;
  if (normalized.includes("shaft")) return 0xc8c1b7;
  return REGION_COLORS[index % REGION_COLORS.length];
}

export function StlViewer({ stls }: { stls: Record<string, string> }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x17191d);

    const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 10000);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;

    scene.add(new THREE.AmbientLight(0xffffff, 1.8));
    const keyLight = new THREE.DirectionalLight(0xffffff, 3.4);
    keyLight.position.set(4, 6, 8);
    scene.add(keyLight);

    const loader = new STLLoader();
    const meshes: THREE.Mesh[] = [];
    const bounds = new THREE.Box3();

    Object.entries(stls).forEach(([region, encoded], index) => {
      const geometry = loader.parse(decodeBase64(encoded));
      geometry.computeVertexNormals();
      const material = new THREE.MeshStandardMaterial({
        color: colorForRegion(region, index),
        metalness: 0.08,
        roughness: 0.72,
        side: THREE.DoubleSide,
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.rotation.x = -Math.PI / 2;
      mesh.name = region;
      meshes.push(mesh);
      scene.add(mesh);
      bounds.expandByObject(mesh);
    });

    if (!bounds.isEmpty()) {
      const center = bounds.getCenter(new THREE.Vector3());
      const size = bounds.getSize(new THREE.Vector3());
      const maxDimension = Math.max(size.x, size.y, size.z);
      const distance = maxDimension / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)));
      camera.position.copy(center).add(new THREE.Vector3(distance * 0.85, distance * 0.65, distance * 1.15));
      camera.near = Math.max(distance / 1000, 0.001);
      camera.far = distance * 20;
      camera.updateProjectionMatrix();
      controls.target.copy(center);
      controls.update();

      const gridSize = Math.max(maxDimension * 1.8, 1);
      const grid = new THREE.GridHelper(gridSize, 20, 0x4b525d, 0x30353d);
      grid.position.y = bounds.min.y;
      scene.add(grid);
    }

    const resize = () => {
      const width = container.clientWidth;
      const height = container.clientHeight;
      renderer.setSize(width, height, false);
      camera.aspect = width / Math.max(height, 1);
      camera.updateProjectionMatrix();
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);
    resize();

    let frame = 0;
    const render = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(render);
    };
    render();

    return () => {
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      controls.dispose();
      meshes.forEach((mesh) => {
        mesh.geometry.dispose();
        const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        materials.forEach((material) => material.dispose());
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [stls]);

  return (
    <div
      ref={containerRef}
      className="w-full overflow-hidden rounded-xl border border-white/10"
      style={{ height: 460, background: "#17191d" }}
      aria-label="Generated stirred-tank reactor geometry"
    />
  );
}
