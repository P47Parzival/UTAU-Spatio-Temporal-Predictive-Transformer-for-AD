// Header.tsx — Dark Prestige UTAU Command Center Header
import { Activity, Cpu, Radio, Zap, MessageSquare, FileDown } from 'lucide-react';

export type SystemState = 'HEALTHY' | 'WARNING' | 'CRITICAL';

const stateColor = (s: SystemState) => s === 'CRITICAL' ? 'var(--crimson)' : s === 'WARNING' ? 'var(--copper)' : 'var(--gold)';
const stateLabel = (s: SystemState) => s === 'CRITICAL' ? 'CRITICAL' : s === 'WARNING' ? 'WARNING' : 'NOMINAL';

interface UtauHeaderProps {
  state: SystemState;
  isConnected: boolean;
  tabs: { label: string; value: string }[];
  activeDataset: string;
  isTransitioning: boolean;
  onChangeDataset: (ds: string) => void;
  isAnomalySourceTabEnabled: boolean;
  isDataSourceTabEnabled: boolean;
  isRlPolicySuggestionsEnabled?: boolean;
  activeFeatureTab: 'live' | 'anomaly-source' | 'data-source';
  onFeatureTabChange: (tab: 'live' | 'anomaly-source' | 'data-source') => void;
  onNavigateHome: () => void;
  onNavigateToChat: () => void;
  onGeneratePDF?: () => void;
}

export function UtauHeader({
  state, isConnected, tabs, activeDataset, isTransitioning,
  onChangeDataset, isAnomalySourceTabEnabled, isDataSourceTabEnabled, isRlPolicySuggestionsEnabled,
  activeFeatureTab, onFeatureTabChange, onNavigateHome, onNavigateToChat, onGeneratePDF
}: UtauHeaderProps) {
  const color = stateColor(state);

  const tabStyle = (isActive: boolean) => ({
    padding: '8px 16px', border: isActive ? '1px solid rgba(201,146,42,0.12)' : '1px solid transparent',
    background: isActive ? 'rgba(28,26,23,0.8)' : 'transparent',
    fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fontWeight: 500, letterSpacing: '0.15em',
    color: isActive ? '#F0EBE0' : '#A09D94', cursor: 'pointer', transition: 'all 0.2s',
  });

  return (
    <header style={{
      height: 64, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '0 48px', borderBottom: '1px solid var(--border)', background: 'rgba(8,8,7,0.92)',
      backdropFilter: 'blur(12px)', position: 'relative', zIndex: 100
    }}>

      {/* ── Brand ── */}
      <button onClick={onNavigateHome} style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0, background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', padding: 0 }}>
        <div style={{ width: 32, height: 32, border: '1.5px solid var(--gold)', transform: 'rotate(45deg)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div className="logo-icon-inner" style={{ width: 12, height: 12, background: 'var(--gold)' }} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <div style={{ fontFamily: "'Bebas Neue', sans-serif", fontSize: 22, letterSpacing: '0.2em', color: '#F0EBE0', lineHeight: 1 }}>
            UTAU<span style={{ color: 'var(--gold)' }}>-IIoT</span>
          </div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 8, fontWeight: 500, color: '#A09D94', letterSpacing: '0.35em', lineHeight: 1 }}>
            COMMAND CENTER
          </div>
        </div>
      </button>

      {/* ── Dataset Tabs ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {tabs.map(t => (
          <button
            key={t.value}
            style={tabStyle(activeDataset === t.value)}
            disabled={isTransitioning}
            onClick={() => onChangeDataset(t.value)}
            onMouseEnter={e => { if (activeDataset !== t.value) e.currentTarget.style.color = '#F0EBE0'; }}
            onMouseLeave={e => { if (activeDataset !== t.value) e.currentTarget.style.color = '#A09D94'; }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Feature Tabs ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <button
          style={{ ...tabStyle(activeFeatureTab === 'live'), display: 'flex', alignItems: 'center', gap: 8 }}
          onClick={() => onFeatureTabChange('live')}
        >
          <Radio size={12} color="var(--gold)" /> LIVE FEED
        </button>
        {isAnomalySourceTabEnabled && (
          <button
            style={{ ...tabStyle(activeFeatureTab === 'anomaly-source'), display: 'flex', alignItems: 'center', gap: 8 }}
            onClick={() => onFeatureTabChange('anomaly-source')}
          >
            <Cpu size={12} color="var(--crimson)" /> ANOMALY SOURCE
          </button>
        )}
        {isDataSourceTabEnabled && (
          <button
            style={{ ...tabStyle(activeFeatureTab === 'data-source'), display: 'flex', alignItems: 'center', gap: 8 }}
            onClick={() => onFeatureTabChange('data-source')}
          >
            <Activity size={12} color="var(--teal)" /> DATA SOURCES
          </button>
        )}
        {isRlPolicySuggestionsEnabled && (
          <button style={{ ...tabStyle(false), display: 'flex', alignItems: 'center', gap: 8 }}>
            <Zap size={12} color="var(--copper)" /> RL POLICY
          </button>
        )}
        <button
          style={{ ...tabStyle(false), display: 'flex', alignItems: 'center', gap: 8, borderLeft: '1px solid rgba(201,146,42,0.12)', paddingLeft: 24, marginLeft: 8 }}
          onClick={onNavigateToChat}
        >
          <MessageSquare size={12} color="#F0EBE0" /> AI COPILOT
        </button>
        {onGeneratePDF && (
          <button
            style={{ ...tabStyle(false), display: 'flex', alignItems: 'center', gap: 8, border: '1px solid rgba(201,146,42,0.4)', borderRadius: '4px', padding: '4px 12px', background: 'rgba(201,146,42,0.1)', marginLeft: 8 }}
            onClick={onGeneratePDF}
            title="Export High-Quality PDF Report"
          >
            <FileDown size={14} color="var(--gold-bright)" /> 
            <span style={{ color: 'var(--gold-bright)', fontWeight: 600 }}>EXPORT PDF</span>
          </button>
        )}
      </div>

      {/* ── Status + Connection ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 14px', border: `1px solid ${color}40`, background: `${color}10` }}>
          <span className="eyebrow-dot" style={{ width: 6, height: 6, borderRadius: '50%', background: color, boxShadow: `0 0 8px ${color}`, display: 'inline-block' }} />
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fontWeight: 600, color, letterSpacing: '0.2em' }}>
            {stateLabel(state)}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 14px', border: '1px solid rgba(201,146,42,0.12)', background: 'rgba(28,26,23,0.8)' }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: isConnected ? 'var(--gold-bright)' : '#A09D94', display: 'inline-block', animation: isConnected ? 'dot-pulse 1.6s infinite' : 'none' }} />
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: isConnected ? 'var(--gold-bright)' : '#A09D94', letterSpacing: '0.15em' }}>
            {isConnected ? 'STREAMING' : 'OFFLINE'}
          </span>
        </div>
      </div>
    </header>
  );
}
