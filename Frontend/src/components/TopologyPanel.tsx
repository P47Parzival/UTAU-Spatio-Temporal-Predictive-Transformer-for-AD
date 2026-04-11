// TopologyPanel — Left HUD: Single 3D Model + Fusion Decomposition + Investigation Path
import { Shield, Box } from 'lucide-react';
import { useRef, useMemo, Suspense } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { useGLTF, Environment, ContactShadows, OrbitControls } from '@react-three/drei';
import * as THREE from 'three';

const G = 'var(--gold)'; const CU = 'var(--copper)'; const VI = 'var(--teal)'; const CR = 'var(--crimson)';
const TP = 'var(--text-primary)'; const TS = 'var(--text-secondary)'; const TD = 'var(--text-dim)';

type SysState = 'HEALTHY' | 'WARNING' | 'CRITICAL';
function accent(s: SysState) { return s === 'CRITICAL' ? CR : s === 'WARNING' ? CU : G; }

function SingleAsset({ dataset, systemState }: { dataset: string; systemState: SysState }) {
  const datasetKey = dataset.toUpperCase();
  const baseRotationX = datasetKey === 'ESP32' ? -Math.PI / 2 : 0;
  const baseRotationY = datasetKey === 'ESP32' ? Math.PI : 0;
  const path = {
    SMD: '/src/assets/server_rack.glb',
    MSL: '/src/assets/industrial_robot.glb',
    SMAP: '/src/assets/centrifugal_pump__bomba_centrifuga.glb',
    ESP32: '/src/assets/esp32.glb',
    SYNTHETIC: '/src/assets/data_center_rack.glb',
  }[datasetKey] || '/src/assets/server_rack.glb';

  const { scene } = useGLTF(path);
  const ref = useRef<THREE.Group>(null!);
  
  const cloned = useMemo(() => {
    const clone = scene.clone(true);
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
    if (m > 0) clone.scale.setScalar(2.2 / m);
    box.setFromObject(clone);
    const ctr = new THREE.Vector3();
    box.getCenter(ctr);
    clone.position.sub(ctr);
    return clone;
  }, [scene]);

  useFrame(({ clock }) => {
    if (ref.current) {
      ref.current.rotation.x = baseRotationX;
      ref.current.rotation.y = baseRotationY + clock.getElapsedTime() * 0.4;
    }
  });

  return (
    <group position={[0, -0.6, 0]}>
      <group ref={ref}>
        <primitive object={cloned} />
      </group>
      {systemState === 'CRITICAL' && <pointLight position={[0, 1.5, 0]} intensity={4} distance={6} color={CR} />}
      <ContactShadows position={[0, -1.0, 0]} opacity={0.6} scale={10} blur={2.0} far={4} color="#5B4520" />
    </group>
  );
}

function AssetViewer({ dataset, systemState }: { dataset: string; systemState: SysState }) {
  return (
    <div style={{ height: 260, position: 'relative', background: 'rgba(232, 220, 195, 0.45)', borderRadius: 8, border: '1px solid rgba(184, 134, 42, 0.15)', marginBottom: 16, overflow: 'hidden' }}>
      <div style={{ position: 'absolute', top: 8, left: 10, zIndex: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
        <Box size={10} color={TD} />
        <span className="section-label" style={{ color: TD }}>DIGITAL TWIN: {dataset}</span>
      </div>
      <Canvas shadows camera={{ position: [0, 1.4, 4.5], fov: 42 }} gl={{ antialias: true, alpha: true, toneMappingExposure: 1.2 }}>
        <ambientLight intensity={0.95} color="#FFF5E0" />
        <hemisphereLight intensity={0.55} color="#FFF1D2" groundColor="#8B6B36" />
        <directionalLight position={[4, 6, 4]} intensity={2.4} color="#FFE0A0" castShadow shadow-mapSize={[1024, 1024]} />
        <pointLight position={[-3, 2.5, 2]} intensity={0.9} color="#FFD6A3" distance={8} />
        <Environment preset="warehouse" intensity={0.6} />
        <OrbitControls enableZoom={false} enablePan={false} maxPolarAngle={Math.PI / 1.8} autoRotate={false} />
        <Suspense fallback={null}>
          <SingleAsset dataset={dataset} systemState={systemState} />
        </Suspense>
      </Canvas>
    </div>
  );
}

interface TopologyPanelProps {
  activeDataset: string;
  scoreComponents: { recon: number; forecast: number; corr: number } | null;
  alertExplanation: any | null;
  systemState: SysState;
}

export default function TopologyPanel({ activeDataset, scoreComponents, alertExplanation, systemState }: TopologyPanelProps) {
  const color = accent(systemState);

  return (
    <div className="panel" style={{ display: 'flex', flexDirection: 'column', gap: 0, padding: 16, height: '100%', overflow: 'hidden' }}>
      
      {/* 3D Asset Viewer Window */}
      <AssetViewer dataset={activeDataset} systemState={systemState} />

      {/* Panel header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingBottom: 10, borderBottom: '1px solid var(--border)', marginBottom: 14 }}>
        <Shield size={12} color={color} style={{ filter: `drop-shadow(0 0 5px ${color})` }} />
        <span className="section-label" style={{ color }}>FUSION DECOMPOSITION</span>
      </div>

      {/* Bars */}
      {scoreComponents && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginBottom: 14 }}>
          {([
            { key: 'Reconstruction', val: scoreComponents.recon,    c: G,  wt: 55 },
            { key: 'Forecast',       val: scoreComponents.forecast, c: CU, wt: 30 },
            { key: 'Correlation',    val: scoreComponents.corr,     c: VI, wt: 15 },
          ] as const).map(({ key, val, c: bc, wt }) => {
            const pct = Math.min(wt + val * 800, 100);
            return (
              <div key={key}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                  <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 12, color: TS, fontStyle: 'italic', fontWeight: 600 }}>{key}</span>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fontWeight: 700, color: bc }}>{val.toFixed(5)}</span>
                </div>
                <div style={{ height: 4, background: 'rgba(232, 220, 195, 0.8)', borderRadius: 99, overflow: 'hidden', position: 'relative' }}>
                  <div style={{ height: '100%', width: `${pct}%`, background: `linear-gradient(90deg, ${bc}80, ${bc})`, borderRadius: 99, transition: 'width 0.5s ease' }} />
                </div>
                <div style={{ textAlign: 'right', fontFamily: "'JetBrains Mono', monospace", fontSize: 8, color: TD, marginTop: 2 }}>WEIGHT: {wt}%</div>
              </div>
            );
          })}
        </div>
      )}

      {/* Divider */}
      {alertExplanation && <div style={{ height: 1, background: 'var(--border)', marginBottom: 12 }} />}

      {/* Investigation hints */}
      {alertExplanation?.investigation_hints?.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, overflowY: 'auto', flex: 1, paddingRight: 4 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
            <span className="section-label">Investigation Path</span>
          </div>
          {alertExplanation.investigation_hints.map((hint: string, i: number) => (
            <div key={i} style={{
              padding: '8px 12px', borderRadius: 6, borderLeft: `3px solid ${G}`,
              background: 'var(--border-dim)', animation: `fade-up 0.3s ease ${i * 0.07}s both`,
            }}>
              <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 13, color: TS, lineHeight: 1.5, fontWeight: 500 }}>
                <span style={{ color: G, marginRight: 6 }}>›</span>{hint}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
