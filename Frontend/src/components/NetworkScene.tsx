/**
 * NetworkScene.tsx — Circular Carousel 3D Scene
 * Natural sunlight/environment rendering for physical models.
 */
import { useRef, useMemo, Suspense } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { useGLTF, Html, OrbitControls, Environment, ContactShadows } from '@react-three/drei';
import * as THREE from 'three';

const GOLD    = '#C9922A';
const COPPER  = '#B87333';
const CRIMSON = '#C0392B';
const CREAM   = '#080807'; // Represents deep black core

type SysState = 'HEALTHY' | 'WARNING' | 'CRITICAL';
function stateColor(s: SysState) {
  return s === 'CRITICAL' ? CRIMSON : s === 'WARNING' ? COPPER : GOLD;
}

function normalizeScene(scene: THREE.Group, size = 1.0) {
  const clone = scene.clone(true);
  // Ensure meshes can cast/receive shadows
  clone.traverse((obj) => {
    if ((obj as THREE.Mesh).isMesh) {
      obj.castShadow = true;
      obj.receiveShadow = true;
    }
  });

  const box = new THREE.Box3().setFromObject(clone);
  const dim = new THREE.Vector3();
  box.getSize(dim);
  const m = Math.max(dim.x, dim.y, dim.z);
  if (m > 0) clone.scale.setScalar(size / m);
  box.setFromObject(clone);
  const ctr = new THREE.Vector3();
  box.getCenter(ctr);
  clone.position.sub(ctr);
  return clone;
}

/* ── Wires connecting center to nodes ── */
function Wires({ nodePositions, color }: { nodePositions: THREE.Vector3[]; color: string }) {
  const lines = useMemo(() => {
    return nodePositions.map(pos => {
      const start = new THREE.Vector3(0, -1, 0); // Center hub point
      const end = pos.clone().add(new THREE.Vector3(0, -1, 0)); // Model base
      const mid = start.clone().lerp(end, 0.5).add(new THREE.Vector3(0, -0.5, 0));
      const curve = new THREE.QuadraticBezierCurve3(start, mid, end);
      return curve.getPoints(20);
    });
  }, [nodePositions]);

  return (
    <group>
      {lines.map((pts, i) => (
        <line key={i}>
          <bufferGeometry>
             <bufferAttribute attach="attributes-position" args={[new Float32Array(pts.flatMap((p: THREE.Vector3) => [p.x, p.y, p.z])), 3]} />
          </bufferGeometry>
          <lineBasicMaterial color={color} transparent opacity={0.5} toneMapped={false} />
        </line>
      ))}
    </group>
  );
}

/* ── Central Hub ── */
function GroundRing({ radius, color }: { radius: number; color: string }) {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.05, 0]} receiveShadow>
      {/* Outer path ring */}
      <ringGeometry args={[radius - 0.4, radius + 0.4, 64]} />
      <meshBasicMaterial color={color} transparent opacity={0.06} side={THREE.DoubleSide} toneMapped={false} />
      
      {/* Center dot */}
      <mesh position={[0, 0, 0]}>
         <circleGeometry args={[0.5, 32]} />
         <meshBasicMaterial color={color} transparent opacity={0.15} toneMapped={false} />
      </mesh>
    </mesh>
  );
}

/* ── Model node ── */
function ModelNode({ path, position, rotationY, color, isHot, label, liveVal }: any) {
  const { scene } = useGLTF(path);
  const ref = useRef<THREE.Group>(null!);
  
  const cloned = useMemo(() => {
    return normalizeScene(scene, 2.0); // Make models large and maintain original PBR materials
  }, [scene]);

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    if (ref.current) {
      ref.current.position.y = position.y + Math.sin(t * 1.5 + position.x) * 0.15;
    }
  });

  return (
    <group ref={ref} position={position} rotation={[0, rotationY, 0]}>
      <primitive object={cloned} />
      
      {/* Dynamic light directly above an anomalous node */}
      {isHot && (
        <pointLight position={[0, 1.5, 0]} intensity={4} distance={6} color={CRIMSON} />
      )}

      {/* Individual glowing ring under each model */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.0, 0]}>
        <ringGeometry args={[0.8, 1.0, 52]} />
        <meshBasicMaterial color={isHot ? CRIMSON : color} transparent opacity={isHot ? 0.6 : 0.25} side={THREE.DoubleSide} toneMapped={false} />
      </mesh>
      
      {/* Animated Red Halos if HOT */}
      {isHot && (
         <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
           <cylinderGeometry args={[1.5, 1.5, 3, 32, 1, true]} />
           <meshBasicMaterial color={CRIMSON} transparent opacity={0.1} side={THREE.DoubleSide} blending={THREE.AdditiveBlending} depthWrite={false} />
         </mesh>
      )}
      
      <Html position={[0, 1.8, 0]} center style={{ pointerEvents: 'none' }}>
        <div style={{
          background: 'rgba(255,250,238,0.85)', backdropFilter: 'blur(8px)',
          border: `1px solid ${isHot ? CRIMSON : 'rgba(201,146,42,0.3)'}`,
          padding: '4px 12px', borderRadius: 6, whiteSpace: 'nowrap', textAlign: 'center',
          boxShadow: '0 4px 12px rgba(140,100,30,0.15)',
        }}>
          <div style={{ fontFamily: "'Cinzel',serif", fontSize: 10, fontWeight: 700, color: isHot ? CRIMSON : GOLD, letterSpacing: '0.2em' }}>{label}</div>
          {liveVal !== undefined && (
            <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: CREAM, marginTop: 2, fontWeight: 600 }}>{liveVal.toFixed(3)}</div>
          )}
        </div>
      </Html>
    </group>
  );
}

/* ── Full scene config ── */
const CarouselRadius = 4.5;
const NODES = [
  { key: 'server', path: '/src/assets/server_rack.glb',                        angle: 0 },
  { key: 'robot',  path: '/src/assets/industrial_robot.glb',                   angle: Math.PI / 2 },
  { key: 'pump',   path: '/src/assets/centrifugal_pump__bomba_centrifuga.glb', angle: Math.PI },
  { key: 'gear',   path: '/src/assets/gearbox_planetary.glb',                  angle: 3 * Math.PI / 2 },
];

function Scene({ systemState, hotSensors, latestData }: any) {
  const color = stateColor(systemState);
  
  const hotNodes = useMemo(() => {
    const h = new Set<string>();
    hotSensors.forEach((s: string) => {
      if (/^s[01]/.test(s)) h.add('server');
      if (/^s[23]/.test(s)) h.add('robot');
      if (/^s[45]/.test(s)) h.add('pump');
      if (/^s[67]/.test(s)) h.add('gear');
    });
    if (systemState === 'CRITICAL') h.add('server');
    return h;
  }, [hotSensors, systemState]);

  const liveVals: Record<string, number | undefined> = {
    server: latestData?.s0_actual, robot: latestData?.s2_actual,
    pump: latestData?.s4_actual,   gear: latestData?.s6_actual,
  };

  const carouselRef = useRef<THREE.Group>(null!);
  useFrame(({ clock }) => {
    if (carouselRef.current) {
      // Rotate the entire carousel slowly
      carouselRef.current.rotation.y = clock.getElapsedTime() * 0.12;
    }
  });

  const nodePositions = useMemo(() => NODES.map(n => new THREE.Vector3(
     Math.cos(n.angle) * CarouselRadius,
     0,
     Math.sin(n.angle) * CarouselRadius
  )), []);

  return (
    <>
      <color attach="background" args={['#EAE0C8']} />
      <fog attach="fog" args={['#EAE0C8', 25, 45]} />

      {/* Realistic lighting environment */}
      <ambientLight intensity={0.5} color="#FFF5E0" />
      <directionalLight position={[10, 15, 10]} intensity={1.5} color="#FFE0A0" castShadow shadow-mapSize={[1024, 1024]} />

      <OrbitControls enableZoom autoRotate={false} enablePan={false} maxPolarAngle={Math.PI / 2.2} />

      {/* Soft floor shadow to ground the objects */}
      <ContactShadows position={[0, -1.08, 0]} opacity={0.4} scale={18} blur={2.5} far={4} color="#5B4520" />

      {/* Rotating Carousel Group */}
      <group ref={carouselRef}>
        <GroundRing radius={CarouselRadius} color={color} />
        <Wires nodePositions={nodePositions} color={color} />
        
        <Suspense fallback={null}>
          {NODES.map((n, i) => (
            <ModelNode 
              key={n.key} 
              path={n.path} 
              position={nodePositions[i]}
              rotationY={-n.angle + Math.PI} 
              color={color} 
              isHot={hotNodes.has(n.key)} 
              label={n.key.toUpperCase()} 
              liveVal={liveVals[n.key]} 
            />
          ))}
        </Suspense>
      </group>
    </>
  );
}

export default function NetworkScene({ systemState, hotSensors, latestData }: {
  systemState: SysState; hotSensors: Set<string>; latestData: any;
}) {
  const color = stateColor(systemState);

  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 0 }}>
      {/* Light vignette */}
      <div style={{
        position: 'absolute', inset: 0, zIndex: 1, pointerEvents: 'none',
        background: 'radial-gradient(ellipse 80% 70% at 50% 45%, transparent 45%, rgba(244,237,216,0.55) 100%)',
      }} />
      <div style={{
        position: 'absolute', bottom: 0, left: 0, right: 0, height: '28%', zIndex: 1, pointerEvents: 'none',
        background: 'linear-gradient(to top, rgba(240,232,210,0.85) 0%, transparent 100%)',
      }} />

      {/* Render with true shadows */}
      <Canvas shadows camera={{ position: [0, 8, 14], fov: 40 }} gl={{ antialias: true, alpha: false, preserveDrawingBuffer: false }}>
        <Scene systemState={systemState} hotSensors={hotSensors} latestData={latestData} />
      </Canvas>

      {/* State badge */}
      <div style={{
        position: 'absolute', top: 18, left: '50%', transform: 'translateX(-50%)',
        fontFamily: "'Cinzel',serif", fontSize: 9, fontWeight: 700, letterSpacing: '0.35em',
        color, pointerEvents: 'none', zIndex: 2,
        animation: systemState === 'CRITICAL' ? 'golden-breathe 1s infinite' : 'none',
      }}>
        {systemState === 'CRITICAL' ? '✦ ANOMALY DETECTED ✦' : systemState === 'WARNING' ? '◈ THRESHOLD PROXIMITY ◈' : '◆ OPERATIONAL CIRCUIT NOMINAL ◆'}
      </div>
    </div>
  );
}
