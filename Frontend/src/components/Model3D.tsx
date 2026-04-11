// Model3D — Generic GLB viewer with reactive glow, rotation, and ring shadow
import { useRef, useMemo, useEffect } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { useGLTF, ContactShadows } from '@react-three/drei';
import * as THREE from 'three';

function applyEmissive(scene: THREE.Group, glowColor: string, intensity: number) {
  scene.traverse((child) => {
    if ((child as THREE.Mesh).isMesh) {
      const mesh = child as THREE.Mesh;
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      mats.forEach((mat) => {
        if ((mat as THREE.MeshStandardMaterial).isMeshStandardMaterial) {
          const m = mat as THREE.MeshStandardMaterial;
          m.emissive = new THREE.Color(glowColor);
          m.emissiveIntensity = Math.min(intensity, 2);
        }
      });
    }
  });
}

function Scene({
  modelPath, rotationSpeed, floatIntensity,
  glowColor, emissiveIntensity, ringColor, ringOpacity,
}: {
  modelPath: string;
  rotationSpeed: number;
  floatIntensity: number;
  glowColor: string;
  emissiveIntensity: number;
  ringColor: string;
  ringOpacity: number;
}) {
  const { scene } = useGLTF(modelPath);
  const groupRef = useRef<THREE.Group>(null!);
  const ringRef  = useRef<THREE.Mesh>(null!);

  const cloned = useMemo(() => {
    const s = scene.clone(true);
    applyEmissive(s, glowColor, emissiveIntensity);
    // Auto-normalize scale
    const box = new THREE.Box3().setFromObject(s);
    const size = new THREE.Vector3();
    box.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z);
    if (maxDim > 0) s.scale.setScalar(1.6 / maxDim);
    return s;
  }, [scene, glowColor, emissiveIntensity]);

  useEffect(() => {
    return () => {
      cloned.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (!mesh.isMesh) return;
        mesh.geometry?.dispose();
        if (Array.isArray(mesh.material)) {
          mesh.material.forEach((mat) => mat.dispose());
        } else {
          mesh.material?.dispose();
        }
      });
    };
  }, [cloned]);

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    if (groupRef.current) {
      groupRef.current.rotation.y += rotationSpeed;
      groupRef.current.position.y = Math.sin(t * 1.8) * 0.04 * floatIntensity;
    }
    if (ringRef.current) {
      const pulse = 1 + Math.sin(t * 3) * 0.06 * floatIntensity;
      ringRef.current.scale.setScalar(pulse);
      const m = ringRef.current.material as THREE.MeshBasicMaterial;
      m.opacity = ringOpacity * (0.8 + Math.cos(t * 4) * 0.2);
    }
  });

  return (
    <group>
      <group ref={groupRef}>
        <primitive object={cloned} />
      </group>
      <mesh ref={ringRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.85, 0]}>
        <ringGeometry args={[1.8, 2.1, 64]} />
        <meshBasicMaterial color={ringColor} transparent opacity={ringOpacity} side={THREE.DoubleSide} />
      </mesh>
      <ContactShadows
        position={[0, -0.9, 0]}
        opacity={ringOpacity * 2.5}
        scale={8}
        blur={2}
        color={ringColor}
      />
    </group>
  );
}

export default function Model3D({
  modelPath,
  height = 200,
  rotationSpeed = 0.005,
  floatIntensity = 0.4,
  glowColor = '#00d4ff',
  emissiveIntensity = 0,
  ringColor = '#00d4ff',
  ringOpacity = 0.12,
  cameraZ = 4.5,
}: {
  modelPath: string;
  height?: number | undefined;
  rotationSpeed?: number;
  floatIntensity?: number;
  glowColor?: string;
  emissiveIntensity?: number;
  ringColor?: string;
  ringOpacity?: number;
  cameraZ?: number;
}) {
  const style: React.CSSProperties = height !== undefined
    ? { width: '100%', height }
    : { width: '100%', flex: 1, minHeight: 0 };

  return (
    <div style={style}>
      <Canvas
        dpr={[1, 1.5]}
        camera={{ position: [0, 1, cameraZ], fov: 42 }}
        gl={{ antialias: true, alpha: true, preserveDrawingBuffer: false }}
        style={{ background: 'transparent' }}
      >
        <ambientLight intensity={1.0} />
        <directionalLight position={[5, 10, 5]} intensity={1.2} />
        <pointLight position={[0, 2, 0]} color={glowColor} intensity={emissiveIntensity * 3} distance={8} />
        <Scene
          modelPath={modelPath}
          rotationSpeed={rotationSpeed}
          floatIntensity={floatIntensity}
          glowColor={glowColor}
          emissiveIntensity={emissiveIntensity}
          ringColor={ringColor}
          ringOpacity={ringOpacity}
        />
      </Canvas>
    </div>
  );
}
