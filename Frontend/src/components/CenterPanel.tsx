// CenterPanel — Anomaly Score Chart + Sensor Residual Grid
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { Activity } from 'lucide-react';

const G  = 'var(--gold)'; const CU = 'var(--copper)'; const CR = 'var(--crimson)'; const VI = 'var(--teal)';
const TP = 'var(--text-primary)'; const TD = 'var(--text-dim)'; const GR = 'var(--teal)';
type SysState = 'HEALTHY' | 'WARNING' | 'CRITICAL';
function accent(s: SysState) { return s === 'CRITICAL' ? CR : s === 'WARNING' ? CU : G; }

function GoldTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: 'rgba(16,10,4,0.9)', backdropFilter: 'blur(8px)', border: '1px solid rgba(212,168,83,0.25)', borderRadius: 8, padding: '8px 14px' }}>
      <div style={{ fontFamily: "'Cinzel', serif", fontSize: 8, color: TD, marginBottom: 4, letterSpacing: '0.15em' }}>TICK {label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: p.stroke || G, fontWeight: 700 }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(6) : p.value}
        </div>
      ))}
    </div>
  );
}

export function HeroSection({ data, systemState, dimensions }: { data: any[]; systemState: SysState; dimensions: number }) {
  const color = accent(systemState);
  const liveLoss  = data.length ? data[data.length - 1].system_loss : 0;
  const threshold = data.length ? data[data.length - 1].threshold   : 0;

  return (
    <div className="panel" style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '14px 16px 8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Activity size={13} color={color} style={{ filter: `drop-shadow(0 0 5px ${color})` }} />
          <span className="section-label" style={{ color }}>FUSED ANOMALY SCORE</span>
          <span className="live-dot" style={{ background: color, boxShadow: `0 0 6px ${color}` }} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontFamily: "'Cinzel', serif", fontSize: 8, color: TD }}>{dimensions}D · WIN-50</span>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 14, fontWeight: 700, color, padding: '3px 10px', background: `${color}15`, border: `1px solid ${color}40`, borderRadius: 5, textShadow: `0 0 10px ${color}50` }}>
            {liveLoss.toFixed(6)}
          </div>
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 8, left: -22, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(212,168,83,0.08)" vertical={false} />
            <XAxis dataKey="tick" stroke={TD} tick={{ fill: TD, fontSize: 8, fontFamily: 'JetBrains Mono' }} />
            <YAxis stroke={TD} tick={{ fill: TD, fontSize: 8, fontFamily: 'JetBrains Mono' }} />
            <Tooltip content={<GoldTooltip />} />
            <ReferenceLine y={threshold} stroke={CR} strokeDasharray="5 3" strokeWidth={1.5} />
            <Line type="monotone" dataKey="system_loss" name="score" stroke={color} strokeWidth={2.5} dot={false} isAnimationActive={false} style={{ filter: `drop-shadow(0 0 5px ${color}80)` }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function ResidualSection({ data, dimensions, hotSensors }: { data: any[]; dimensions: number; hotSensors: Set<string>; isTransitioning?: boolean; activeDataset?: string }) {
  return (
    <div className="panel" style={{ padding: '10px 12px 6px', height: '100%', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
        <span className="section-label">SENSOR RESIDUALS — {dimensions} CHANNELS</span>
        <span style={{ fontFamily: "'Cinzel', serif", fontSize: 7, color: TD, letterSpacing: '0.2em' }}>ACTUAL vs FORECAST</span>
      </div>
      <div style={{
        flex: 1, overflowY: 'auto',
        display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))',
        gap: 6, alignContent: 'start', paddingRight: 4,
      }}>
        {Array.from({ length: dimensions }).map((_, i) => {
          const isHot = hotSensors.has(`s${i}`) || hotSensors.has(`s${i}_actual`);
          return (
            <div key={i} className="panel-recessed" style={{
              height: 80, padding: '6px 8px',
              border: `1px solid ${isHot ? 'var(--crimson)' : 'var(--border)'}`,
              background: isHot ? 'rgba(168,50,64,0.05)' : 'rgba(232, 220, 195, 0.40)',
              boxShadow: isHot ? `inset 0 0 10px rgba(168,50,64,0.1), 0 0 8px rgba(168,50,64,0.1)` : 'none',
              display: 'flex', flexDirection: 'column',
            }}>
              <div style={{ fontFamily: "'Cinzel', serif", fontSize: 7, color: isHot ? CR : TD, letterSpacing: '0.12em', marginBottom: 2 }}>
                S{String(i).padStart(2, '0')}
              </div>
              <div style={{ flex: 1 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data}>
                    <YAxis yAxisId="a" hide domain={['auto', 'auto']} />
                    <YAxis yAxisId="f" hide domain={['auto', 'auto']} />
                    <Line yAxisId="a" type="stepAfter" dataKey={(d: any) => d?.actual?.[i]}   stroke={isHot ? CR : G}  strokeWidth={1}   dot={false} isAnimationActive={false} />
                    <Line yAxisId="f" type="monotone"  dataKey={(d: any) => d?.forecast?.[i]} stroke={GR}             strokeWidth={1}   dot={false} isAnimationActive={false} strokeDasharray="2 2" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
