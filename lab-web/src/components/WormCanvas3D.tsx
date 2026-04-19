import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { useLabStore } from "../state/store";
import { useAppSettings } from "../state/app-settings";

/** Match WormCanvas scale metaphor: ~1.2 mm body fits ~1 world unit across. */
const BODY_LENGTH_MM = 1.2;
const MM_TO_WORLD = 1 / BODY_LENGTH_MM;
/** Amplify out-of-plane motion (wire z is sub-mm). */
const Z_EXAGGERATION = 10;
const MAX_SEGMENTS = 32;

/** World +Y is up; floor is XZ at y=0. Map sim (x,y,z) mm → Three (x, y_up, z). */
function simMmToWorld(
  sx: number,
  sy: number,
  sz: number,
  cx: number,
  cy: number,
  cz: number,
  out: { x: number; y: number; z: number },
) {
  out.x = (sx - cx) * MM_TO_WORLD;
  out.y = (sz - cz) * MM_TO_WORLD * Z_EXAGGERATION;
  out.z = (sy - cy) * MM_TO_WORLD;
}

export function WormCanvas3D() {
  const rootRef = useRef<HTMLDivElement>(null);
  const canvasHostRef = useRef<HTMLDivElement>(null);
  const resetViewRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const canvasHost = canvasHostRef.current;
    if (!canvasHost) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0a0a0a);
    scene.fog = new THREE.Fog(0x0a0a0a, 5.5, 22);

    const camera = new THREE.PerspectiveCamera(48, 1, 0.02, 80);
    camera.up.set(0, 1, 0);

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: false,
      powerPreference: "high-performance",
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio ?? 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    canvasHost.appendChild(renderer.domElement);
    renderer.domElement.classList.add("block", "h-full", "w-full", "cursor-grab");
    renderer.domElement.addEventListener("mousedown", () => {
      renderer.domElement.classList.replace("cursor-grab", "cursor-grabbing");
    });
    renderer.domElement.addEventListener("mouseup", () => {
      renderer.domElement.classList.replace("cursor-grabbing", "cursor-grab");
    });

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.screenSpacePanning = false;
    controls.minDistance = 0.35;
    controls.maxDistance = 48;
    /** Keep the camera above the substrate plane (no upside-down worm shots). */
    controls.maxPolarAngle = Math.PI / 2 - 0.06;
    controls.minPolarAngle = 0.12;
    controls.rotateSpeed = 0.65;
    controls.zoomSpeed = 0.85;
    controls.panSpeed = 0.75;
    controls.mouseButtons = {
      LEFT: THREE.MOUSE.ROTATE,
      MIDDLE: THREE.MOUSE.DOLLY,
      RIGHT: THREE.MOUSE.PAN,
    };

    const hemi = new THREE.HemisphereLight(0x9db4c8, 0x080808, 0.85);
    hemi.position.set(0, 1, 0);
    scene.add(hemi);
    const key = new THREE.DirectionalLight(0xffffff, 0.55);
    key.position.set(2.2, 4.5, 1.4);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xb8c9e0, 0.22);
    fill.position.set(-2.5, 2.2, -2);
    scene.add(fill);

    const gridSize = 6;
    const gridDivs = 60;
    const grid = new THREE.GridHelper(
      gridSize,
      gridDivs,
      0x5a6a82,
      0x303844,
    );
    grid.position.y = 0;
    const gridMat = grid.material as THREE.LineBasicMaterial;
    gridMat.transparent = true;
    gridMat.opacity = 0.5;
    gridMat.depthWrite = false;
    scene.add(grid);

    const floorMat = new THREE.MeshStandardMaterial({
      color: 0x0f1218,
      metalness: 0.05,
      roughness: 0.92,
      transparent: true,
      opacity: 0.92,
    });
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(gridSize * 2, gridSize * 2),
      floorMat,
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.0015;
    floor.receiveShadow = false;
    scene.add(floor);

    const positions = new Float32Array(MAX_SEGMENTS * 3);
    const lineGeom = new THREE.BufferGeometry();
    lineGeom.setAttribute(
      "position",
      new THREE.BufferAttribute(positions, 3),
    );
    const lineMat = new THREE.LineBasicMaterial({
      color: 0x9eb7ff,
      transparent: true,
      opacity: 0.95,
    });
    const line = new THREE.Line(lineGeom, lineMat);
    lineGeom.setDrawRange(0, 0);
    line.renderOrder = 2;
    scene.add(line);

    const headGeom = new THREE.SphereGeometry(0.048, 24, 24);
    const headMat = new THREE.MeshStandardMaterial({
      color: 0x7fffbf,
      metalness: 0.18,
      roughness: 0.42,
      emissive: 0x0a1a12,
      emissiveIntensity: 0.35,
    });
    const head = new THREE.Mesh(headGeom, headMat);
    head.renderOrder = 3;
    scene.add(head);

    const tmp = { x: 0, y: 0, z: 0 };

    const resetView = () => {
      const dist = 2.35;
      const polar = THREE.MathUtils.degToRad(46);
      const azimuth = THREE.MathUtils.degToRad(38);
      const sinP = Math.sin(polar);
      const cosP = Math.cos(polar);
      camera.position.set(
        dist * sinP * Math.sin(azimuth),
        dist * cosP,
        dist * sinP * Math.cos(azimuth),
      );
      controls.target.set(0, 0.02, 0);
      camera.up.set(0, 1, 0);
      camera.updateProjectionMatrix();
      controls.update();
    };
    resetView();
    resetViewRef.current = resetView;

    let raf = 0;
    let lastGeomMs = 0;

    const resize = () => {
      const w = canvasHost.clientWidth;
      const h = Math.max(canvasHost.clientHeight, 1);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
    };

    const ro = new ResizeObserver(resize);
    ro.observe(canvasHost);
    resize();

    const tick = (timeMs: number) => {
      raf = requestAnimationFrame(tick);
      const cap = useAppSettings.getState().renderFpsCap;
      const minInterval = cap > 0 ? 1000 / cap : 0;
      const geomDue =
        minInterval <= 0 || timeMs - lastGeomMs >= minInterval - 0.5;

      if (geomDue) {
        lastGeomMs = timeMs;
        const latest = useLabStore.getState().latest;
        if (latest && latest.segments_mm.length >= 9) {
          const [cx, cy, cz] = latest.com_mm;
          const seg = latest.segments_mm;
          const n = Math.min(Math.floor(seg.length / 3), MAX_SEGMENTS);
          for (let i = 0; i < n; i++) {
            const o = i * 3;
            simMmToWorld(seg[o], seg[o + 1], seg[o + 2], cx, cy, cz, tmp);
            positions[o] = tmp.x;
            positions[o + 1] = tmp.y;
            positions[o + 2] = tmp.z;
          }
          const attr = lineGeom.getAttribute("position") as THREE.BufferAttribute;
          attr.needsUpdate = true;
          lineGeom.setDrawRange(0, n);
          head.position.set(positions[0], positions[1], positions[2]);
        }
      }

      controls.update();
      renderer.render(scene, camera);
    };

    raf = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf);
      resetViewRef.current = null;
      ro.disconnect();
      controls.dispose();
      lineGeom.dispose();
      lineMat.dispose();
      headGeom.dispose();
      headMat.dispose();
      floor.geometry.dispose();
      floorMat.dispose();
      grid.dispose();
      scene.fog = null;
      renderer.dispose();
      if (renderer.domElement.parentNode === canvasHost) {
        canvasHost.removeChild(renderer.domElement);
      }
    };
  }, []);

  useEffect(() => {
    rootRef.current?.focus({ preventScroll: true });
  }, []);

  return (
    <div
      ref={rootRef}
      className="relative h-full min-h-0 w-full outline-none focus-visible:ring-1 focus-visible:ring-accent/50 focus-visible:ring-offset-2 focus-visible:ring-offset-black"
      tabIndex={0}
      role="application"
      aria-label="Worm 3D view"
      onKeyDown={(e) => {
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        if (e.code === "KeyR" || e.code === "Home") {
          e.preventDefault();
          resetViewRef.current?.();
        }
      }}
    >
      <div ref={canvasHostRef} className="absolute inset-0 min-h-0" />

      <div className="pointer-events-none absolute inset-x-0 top-0 flex justify-center pt-2">
        <div className="max-w-[min(100%,420px)] rounded-md border border-zinc-800/90 bg-zinc-950/75 px-3 py-2 shadow-lg ring-1 ring-black/35 backdrop-blur-sm">
          <div className="text-center text-[10px] font-semibold tracking-wider text-zinc-400 uppercase">
            Scene · Y up · floor XZ
          </div>
          <p className="mt-1 text-center text-[10px] leading-snug text-zinc-500">
            Worm lies in the dish plane (X/Z); vertical is biological{" "}
            <span className="font-mono text-zinc-400">Z</span> × {Z_EXAGGERATION}.
          </p>
        </div>
      </div>

      <div className="pointer-events-none absolute bottom-3 left-3 max-w-[220px] rounded-lg border border-zinc-800/90 bg-zinc-950/85 p-2.5 shadow-lg ring-1 ring-black/40 backdrop-blur-sm">
        <div className="mb-1.5 text-[10px] font-semibold tracking-wider text-zinc-400 uppercase">
          Controls
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-[11px] leading-tight text-zinc-300">
          <dt className="font-mono text-zinc-500">Rotate</dt>
          <dd>Left-drag</dd>
          <dt className="font-mono text-zinc-500">Pan</dt>
          <dd>Right-drag · Shift+left</dd>
          <dt className="font-mono text-zinc-500">Zoom</dt>
          <dd>Scroll · pinch</dd>
          <dt className="font-mono text-zinc-500">Reset</dt>
          <dd>
            <kbd className="rounded border border-zinc-700 bg-zinc-900 px-1 font-mono text-[10px] text-zinc-200">
              R
            </kbd>{" "}
            ·{" "}
            <kbd className="rounded border border-zinc-700 bg-zinc-900 px-1 font-mono text-[10px] text-zinc-200">
              Home
            </kbd>
          </dd>
        </dl>
      </div>

      <button
        type="button"
        className="pointer-events-auto absolute right-3 bottom-3 rounded-md border border-zinc-700 bg-zinc-900/90 px-2.5 py-1.5 text-[11px] font-medium text-zinc-200 shadow-md backdrop-blur-sm hover:bg-zinc-800 hover:text-white focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        onClick={() => resetViewRef.current?.()}
      >
        Reset view
      </button>
    </div>
  );
}
