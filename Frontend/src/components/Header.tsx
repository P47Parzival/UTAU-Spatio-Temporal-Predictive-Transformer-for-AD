// Header.tsx — Cream-Gold AEGIS Command Center Header
import { Activity, Cpu, Radio, Zap } from 'lucide-react';

export type SystemState = 'HEALTHY' | 'WARNING' | 'CRITICAL';

const stateColor = (s: SystemState) => s === 'CRITICAL' ? '#A83240' : s === 'WARNING' ? '#A0581A' : '#B8862A';
const stateLabel = (s: SystemState) => s === 'CRITICAL' ? 'CRITICAL' : s === 'WARNING' ? 'WARNING' : 'NOMINAL';

interface AegisHeaderProps {
  state: SystemState;
  isConnected: boolean;
  tabs: { label: string; value: string }[];
  activeDataset: string;
  isTransitioning: boolean;
  onChangeDataset: (ds: string) => void;
  isAnomalySourceTabEnabled: boolean;
  isRlPolicySuggestionsEnabled: boolean;
  activeFeatureTab: 'live' | 'anomaly-source';
  onFeatureTabChange: (tab: 'live' | 'anomaly-source') => void;
}

export function AegisHeader({
  state, isConnected, tabs, activeDataset, isTransitioning,
  onChangeDataset, isAnomalySourceTabEnabled, isRlPolicySuggestionsEnabled,
  activeFeatureTab, onFeatureTabChange,
}: AegisHeaderProps) {
  const color = stateColor(state);

  return (
    <header className="hud-header" style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 20px', gap: 16 }}>
      
      {/* ── Brand ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
        <div style={{ position: 'relative' }}>
          <Activity size={18} color="#D4A853" style={{ filter: 'drop-shadow(0 0 6px #D4A853)' }} />
          <div style={{ position: 'absolute', inset: -4, borderRadius: '50%', border: '1px solid rgba(212,168,83,0.3)', animation: 'spin-slow 8s linear infinite' }} />
        </div>
        <div>
          <div style={{ fontFamily: "'Cinzel', serif", fontSize: 13, fontWeight: 700, color: '#D4A853', letterSpacing: '0.25em', lineHeight: 1, textShadow: '0 0 12px rgba(212,168,83,0.5)' }}>
            AEGIS
          </div>
          <div style={{ fontFamily: "'Cinzel', serif", fontSize: 7, fontWeight: 400, color: 'rgba(245,230,200,0.5)', letterSpacing: '0.35em', lineHeight: 1, marginTop: 2 }}>
            IIoT COMMAND
          </div>
        </div>
      </div>

      {/* ── Dataset Tabs ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        {tabs.map(t => (
          <button
            key={t.value}
            className={`ds-tab${activeDataset === t.value ? ' active' : ''}`}
            disabled={isTransitioning}
            onClick={() => onChangeDataset(t.value)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Feature Tabs ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <button
          className={`ds-tab${activeFeatureTab === 'live' ? ' active' : ''}`}
          onClick={() => onFeatureTabChange('live')}
          style={{ display: 'flex', alignItems: 'center', gap: 5 }}
        >
          <Radio size={9} /> LIVE
        </button>
        {isAnomalySourceTabEnabled && (
          <button
            className={`ds-tab${activeFeatureTab === 'anomaly-source' ? ' active' : ''}`}
            onClick={() => onFeatureTabChange('anomaly-source')}
            style={{ display: 'flex', alignItems: 'center', gap: 5 }}
          >
            <Cpu size={9} /> SOURCE
          </button>
        )}
        {isRlPolicySuggestionsEnabled && (
          <button className="ds-tab" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <Zap size={9} /> RL POLICY
          </button>
        )}
      </div>

      {/* ── Status + Connection ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 12px', borderRadius: 20, border: `1px solid ${color}40`, background: `${color}10` }}>
          <span className="live-dot" style={{ background: color, boxShadow: `0 0 6px ${color}` }} />
          <span style={{ fontFamily: "'Cinzel', serif", fontSize: 8, fontWeight: 700, color, letterSpacing: '0.2em' }}>
            {stateLabel(state)}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '4px 10px', borderRadius: 20, border: '1px solid rgba(212,168,83,0.15)', background: 'rgba(212,168,83,0.05)' }}>
          <span style={{ width: 5, height: 5, borderRadius: '50%', background: isConnected ? '#D4A853' : '#6A5840', display: 'inline-block', animation: isConnected ? 'dot-pulse 1.6s infinite' : 'none' }} />
          <span style={{ fontFamily: "'Cinzel', serif", fontSize: 7, color: isConnected ? '#A89070' : '#6A5840', letterSpacing: '0.15em' }}>
            {isConnected ? 'STREAM' : 'OFFLINE'}
          </span>
        </div>
      </div>
    </header>
  );
}
