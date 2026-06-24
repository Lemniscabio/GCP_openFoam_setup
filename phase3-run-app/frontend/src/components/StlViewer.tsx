import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

const REGION_COLORS = [0xd8d9dc, 0xc7cbd0, 0xdedbd5, 0xc9d3d5, 0xd5d0ca, 0xe1e2e4];
const OUTER_REGIONS = new Set(["tankwall", "dishedbottom", "liquidsurface"]);

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
  const [isFs, setIsFs] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

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
    controls.dampingFactor = 0.12;       // smooth, settles quickly
    controls.rotateSpeed = 0.9;
    controls.zoomSpeed = 0.9;
    controls.panSpeed = 0.7;
    controls.screenSpacePanning = true;  // pan in the screen plane (intuitive)
    // NOTE: no zoomToCursor — it drifts the orbit target off the model centre, which makes
    // drag-rotate swing the whole model around instead of revolving it in place.
    controls.enabled = true;

    scene.add(new THREE.AmbientLight(0xffffff, 1.8));
    const keyLight = new THREE.DirectionalLight(0xffffff, 3.4);
    keyLight.position.set(4, 6, 8);
    scene.add(keyLight);

    const loader = new STLLoader();
    const meshes: THREE.Mesh[] = [];
    const edges: THREE.LineSegments[] = [];
    const model = new THREE.Group();
    model.rotation.x = -Math.PI / 2;
    scene.add(model);

    Object.entries(stls).forEach(([region, encoded], index) => {
      const geometry = loader.parse(decodeBase64(encoded));
      geometry.computeVertexNormals();
      const normalizedRegion = region.toLowerCase();
      const isOuter = OUTER_REGIONS.has(normalizedRegion);
      const isLiquidSurface = normalizedRegion === "liquidsurface";
      const isImpeller = normalizedRegion.includes("impeller");
      const material = isOuter
        ? new THREE.MeshStandardMaterial({
            color: isLiquidSurface ? 0x9fb4c4 : 0xdfe3e8,
            metalness: 0.08,
            roughness: 0.72,
            transparent: true,
            opacity: isLiquidSurface ? 0.18 : 0.14,
            depthWrite: false,
            side: THREE.DoubleSide,
          })
        : new THREE.MeshStandardMaterial({
            color: colorForRegion(region, index),
            metalness: isImpeller ? 0.28 : 0.08,
            roughness: 0.72,
            side: THREE.DoubleSide,
          });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.name = region;
      mesh.renderOrder = isOuter ? 1 : 0;

      if (isOuter) {
        const edge = new THREE.LineSegments(
          new THREE.EdgesGeometry(mesh.geometry, 30),
          new THREE.LineBasicMaterial({
            color: 0xffffff,
            transparent: true,
            opacity: 0.5,
          }),
        );
        edge.renderOrder = 1;
        edges.push(edge);
        mesh.add(edge);
      }

      meshes.push(mesh);
      model.add(mesh);
    });

    model.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(model);
    let fitCamera = () => {};

    if (!box.isEmpty()) {
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      model.position.sub(center);
      model.updateMatrixWorld(true);
      box.setFromObject(model);

      fitCamera = () => {
        const radius = 0.5 * size.length();
        const fitH = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2));
        const fitW = fitH / Math.min(1, camera.aspect);
        const distance = 1.25 * Math.max(fitH, fitW);
        camera.position.set(distance * 0.7, distance * 0.45, distance);
        camera.near = Math.max(distance / 1000, 0.001);
        camera.far = distance * 20;
        camera.updateProjectionMatrix();
        controls.target.set(0, 0, 0);
        controls.minDistance = Math.max(radius * 0.25, camera.near * 2);
        controls.maxDistance = distance * 8;
        controls.update();
      };

      const gridSize = Math.max(size.x, size.z, 1) * 1.8;
      const grid = new THREE.GridHelper(gridSize, 20, 0x4b525d, 0x30353d);
      grid.position.y = -size.y / 2;
      scene.add(grid);
    }

    const resize = () => {
      const width = container.clientWidth;
      const height = container.clientHeight;
      renderer.setSize(width, height, false);
      camera.aspect = width / Math.max(height, 1);
      camera.updateProjectionMatrix();
    };
    const resizeObserver = new ResizeObserver(() => {
      resize();
      fitCamera();
    });
    resizeObserver.observe(container);
    resize();
    fitCamera();

    const handleFullscreenChange = () => {
      setIsFs(document.fullscreenElement === container);
      resize();
      fitCamera();
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);

    let frame = 0;
    const render = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(render);
    };
    render();

    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
      resizeObserver.disconnect();
      controls.dispose();
      edges.forEach((edge) => {
        edge.geometry.dispose();
        const materials = Array.isArray(edge.material) ? edge.material : [edge.material];
        materials.forEach((material) => material.dispose());
      });
      meshes.forEach((mesh) => {
        mesh.geometry.dispose();
        const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        materials.forEach((material) => material.dispose());
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [stls]);

  const toggleFullscreen = () => {
    const container = containerRef.current;
    if (!container) return;

    if (document.fullscreenElement === container) {
      void document.exitFullscreen();
      return;
    }

    void container.requestFullscreen();
  };

  return (
    <div
      ref={containerRef}
      className="relative w-full overflow-hidden rounded-xl border border-white/10"
      style={{ height: isFs ? "100%" : 460, background: "#17191d" }}
      aria-label="Generated stirred-tank reactor geometry"
    >
      <div className="pointer-events-none absolute left-3 top-3 z-10">
        <div
          className="pointer-events-auto relative inline-block"
          onMouseEnter={() => setShowHelp(true)}
          onMouseLeave={() => setShowHelp(false)}
        >
          <span
            className="inline-flex h-7 w-7 cursor-help items-center justify-center rounded-full border border-white/30 bg-white/15 text-sm font-medium text-white backdrop-blur-sm"
            aria-label="3D controls help"
          >
            ?
          </span>
          {showHelp && (
            <div
              style={{
                position: "absolute", left: 0, top: 34, width: "max-content", maxWidth: 280,
                borderRadius: 8, border: "1px solid rgba(255,255,255,0.15)", background: "rgba(0,0,0,0.88)",
                padding: "8px 12px", fontSize: 12, lineHeight: 1.6, color: "#fff",
                boxShadow: "0 6px 20px rgba(0,0,0,0.4)", zIndex: 20,
              }}
            >
              <div><b>Rotate:</b> left-drag</div>
              <div><b>Zoom:</b> scroll — up = in, down = out</div>
              <div><b>Pan:</b> right-drag</div>
            </div>
          )}
        </div>
      </div>
      <div className="pointer-events-none absolute right-3 top-3 z-10">
        <button
          type="button"
          className="pointer-events-auto rounded-md border border-white/30 bg-white/15 px-3 py-1.5 text-xs font-medium text-white backdrop-blur-sm hover:bg-white/25"
          onClick={toggleFullscreen}
        >
          {isFs ? "Exit fullscreen" : "Fullscreen"}
        </button>
      </div>
    </div>
  );
}
