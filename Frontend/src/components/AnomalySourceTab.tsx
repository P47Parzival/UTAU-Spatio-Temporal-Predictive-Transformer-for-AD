import { useEffect, useMemo, useState } from 'react';
import { RefreshCw, Activity, Layers, ActivitySquare, Database } from 'lucide-react';

type ScoreComponents = { recon: number; forecast: number; corr: number; };

type AlertExplanation = {
  severity_score: number; severity_level: 'info' | 'warning' | 'critical';
  confidence: number; anomaly_type: string; duration_steps: number;
  top_contributors: Array<{ sensor: string; contribution_pct: number; }>;
  investigation_hints: string[];
};

type AnomalySourcePayload = {
  breakdown: { contribution_pct: { recon: number; forecast: number; corr: number; }; z_scores: { recon: number; forecast: number; corr: number; }; };
  correlation_change: {
    ready: boolean; fro_norm: number;
    top_pair_changes: Array<{ sensor_a: string; sensor_b: string; prev_corr: number; curr_corr: number; delta: number; abs_delta: number; }>;
  };
};

type AnomalyRecord = {
  id: number; created_at_ms: number; dataset: string; tick: number; system_loss: number;
  threshold: number; severity_score: number; severity_level: string; confidence: number;
  anomaly_type: string; duration_steps: number; top_sensor: string;
  top_contributors: Array<{ sensor: string; contribution_pct: number; }>;
  investigation_hints: string[]; score_components: ScoreComponents;
  anomaly_source?: AnomalySourcePayload | null;
};

type Props = {
  activeDataset: string; alertExplanation: AlertExplanation | null;
  anomalySource: AnomalySourcePayload | null; scoreComponents: ScoreComponents | null; isConnected: boolean;
};

const API_BASE = 'http://127.0.0.1:8000';

const C = {
  cyan: '#B8862A', amber: '#A0581A', red: '#A83240', violet: '#7c3aed',
  textPrimary: '#2C1E0A', textSec: '#6B4F2A', textDim: '#9A7E58', border: 'rgba(184,134,42,0.25)',
};

const severityColor = (level: string) => {
  if (level === 'critical') return C.red;
  if (level === 'warning') return C.amber;
  return C.cyan;
};

export default function AnomalySourceTab({
  activeDataset, alertExplanation, anomalySource, scoreComponents, isConnected,
}: Props) {
  const [items, setItems] = useState<AnomalyRecord[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedItem, setSelectedItem] = useState<AnomalyRecord | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [error, setError] = useState('');

  const loadAnomalies = async () => {
    setIsLoading(true); setError('');
    try {
      const response = await fetch(`${API_BASE}/anomalies?dataset=${encodeURIComponent(activeDataset)}&limit=120`);
      if (!response.ok) throw new Error(`failed to load anomalies: ${response.status}`);
      const payload = await response.json();
      const list = (payload.items ?? []) as AnomalyRecord[];
      setItems(list);
      if (list.length > 0 && (selectedId === null || !list.some((x) => x.id === selectedId))) {
        setSelectedId(list[0].id);
      }
      if (list.length === 0) { setSelectedId(null); setSelectedItem(null); }
    } catch (err) { setError(err instanceof Error ? err.message : 'failed to load anomaly list'); } 
    finally { setIsLoading(false); }
  };

  useEffect(() => { setSelectedId(null); setSelectedItem(null); void loadAnomalies(); }, [activeDataset]);

  useEffect(() => {
    if (selectedId === null) return;
    const fetchDetail = async () => {
      setIsDetailLoading(true);
      try {
        const response = await fetch(`${API_BASE}/anomalies/${selectedId}`);
        if (!response.ok) throw new Error(`failed to load anomaly detail: ${response.status}`);
        const detail = (await response.json()) as AnomalyRecord;
        setSelectedItem(detail);
      } catch (err) { setError(err instanceof Error ? err.message : 'failed to load anomaly detail'); } 
      finally { setIsDetailLoading(false); }
    };
    void fetchDetail();
  }, [selectedId]);

  const sourceView = useMemo(() => {
    if (selectedItem?.anomaly_source) return selectedItem.anomaly_source;
    return anomalySource;
  }, [selectedItem, anomalySource]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      
      {/* Top 3 Metric Cards */}
      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
        
        {/* Live Source Snapshot */}
        <div className="panel" style={{ padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
            <Activity size={12} color={C.cyan} />
            <span className="section-label" style={{ color: C.cyan }}>LIVE SNAPSHOT</span>
          </div>
          {!alertExplanation ? (
            <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: C.textDim }}>// awaiting anomalous event...</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{
                display: 'inline-block', alignSelf: 'flex-start', padding: '2px 8px', borderRadius: 4, fontFamily: 'JetBrains Mono', fontSize: 10, fontWeight: 700,
                color: severityColor(alertExplanation.severity_level), border: `1px solid ${severityColor(alertExplanation.severity_level)}40`, background: `${severityColor(alertExplanation.severity_level)}15`
              }}>
                {alertExplanation.severity_level.toUpperCase()} | SCORE: {alertExplanation.severity_score}
              </div>
              <div style={{ fontFamily: 'Inter', fontSize: 12, color: C.textSec }}>Type: <span style={{ color: C.textPrimary, fontWeight: 600 }}>{alertExplanation.anomaly_type.replace('_', ' ')}</span></div>
              <div style={{ fontFamily: 'Inter', fontSize: 12, color: C.textSec }}>Confidence: <span style={{ color: C.textPrimary, fontWeight: 600 }}>{(alertExplanation.confidence * 100).toFixed(1)}%</span></div>
              {scoreComponents && (
                <div style={{ marginTop: 8, padding: 8, background: 'rgba(232,220,195,0.6)', border: `1px solid ${C.border}`, borderRadius: 6, fontFamily: 'JetBrains Mono', fontSize: 10, color: C.textSec, lineHeight: 1.5 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Recon</span><span style={{color: C.cyan}}>{scoreComponents.recon.toFixed(6)}</span></div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Forecast</span><span style={{color: C.violet}}>{scoreComponents.forecast.toFixed(6)}</span></div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Corr</span><span style={{color: C.amber}}>{scoreComponents.corr.toFixed(6)}</span></div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Source Breakdown */}
        <div className="panel" style={{ padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
            <Layers size={12} color={C.violet} />
            <span className="section-label" style={{ color: C.violet }}>SOURCE BREAKDOWN</span>
          </div>
          {!sourceView ? (
             <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: C.textDim }}>// waiting for source frames...</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {([
                { k: 'RECON', v: sourceView.breakdown.contribution_pct.recon, color: C.cyan },
                { k: 'FORECAST', v: sourceView.breakdown.contribution_pct.forecast, color: C.violet },
                { k: 'CORR', v: sourceView.breakdown.contribution_pct.corr, color: C.amber }
              ]).map(c => (
                <div key={c.k}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'JetBrains Mono', fontSize: 10, marginBottom: 4 }}>
                    <span style={{ color: C.textSec }}>{c.k} Pct:</span><span style={{ color: c.color, fontWeight: 700 }}>{c.v.toFixed(1)}%</span>
                  </div>
                  <div style={{ height: 3, background: 'rgba(232,220,195,0.8)', borderRadius: 99 }}><div style={{ width: `${c.v}%`, height: '100%', background: c.color, borderRadius: 99 }}/></div>
                </div>
              ))}
              <div style={{ marginTop: 8, padding: 8, background: 'rgba(232,220,195,0.5)', border: `1px solid ${C.border}`, borderRadius: 6, fontFamily: 'JetBrains Mono', fontSize: 10, color: C.textDim }}>
                Z-SCORES: R {sourceView.breakdown.z_scores.recon.toFixed(3)} | F {sourceView.breakdown.z_scores.forecast.toFixed(3)} | C {sourceView.breakdown.z_scores.corr.toFixed(3)}
              </div>
            </div>
          )}
        </div>

        {/* Correlation Shift */}
        <div className="panel" style={{ padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
             <ActivitySquare size={12} color={C.amber} />
             <span className="section-label" style={{ color: C.amber }}>CORRELATION SHIFT</span>
          </div>
          {!sourceView?.correlation_change.ready ? (
             <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: C.textDim }}>// no stable snapshot yet</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, height: '100%' }}>
              <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: C.textSec }}>Frobenius Norm: <span style={{ color: C.amber }}>{sourceView.correlation_change.fro_norm.toFixed(6)}</span></div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, overflowY: 'auto' }}>
                {sourceView.correlation_change.top_pair_changes.slice(0, 5).map((pair) => (
                  <div key={`${pair.sensor_a}-${pair.sensor_b}`} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 8px', background: 'rgba(232,220,195,0.5)', border: `1px solid ${C.border}`, borderRadius: 4, fontFamily: 'JetBrains Mono', fontSize: 9 }}>
                    <span style={{ color: C.textSec }}>{pair.sensor_a} ↔ {pair.sensor_b}</span>
                    <span style={{ color: C.red }}>Δ {pair.delta.toFixed(4)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Historical List + Detail */}
      <section className="panel" style={{ padding: 16, display: 'flex', flexDirection: 'column', flex: 1, minHeight: 400 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Database size={12} color={C.textPrimary} />
            <span className="section-label" style={{ color: C.textPrimary }}>HISTORICAL ANOMALY SOURCE EVENTS ({activeDataset})</span>
          </div>
          <button onClick={() => void loadAnomalies()} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', background: 'rgba(255,255,255,0.05)', border: `1px solid ${C.border}`, borderRadius: 6, color: C.textPrimary, fontFamily: 'JetBrains Mono', fontSize: 10, cursor: 'pointer' }}>
            <RefreshCw size={11} className={isLoading ? 'animate-spin' : ''} /> REFRESH
          </button>
        </div>

        {!isConnected && <p style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: C.amber, marginBottom: 8 }}># Backend disconnected. History may be stale.</p>}
        {error && <p style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: C.red, marginBottom: 8 }}>{error}</p>}

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(250px, 1fr) minmax(250px, 1fr)', gap: 16, flex: 1, minHeight: 0 }}>
          
          {/* List */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, overflowY: 'auto', paddingRight: 4 }}>
            {items.length === 0 && !isLoading ? (
               <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: C.textDim, padding: 16 }}>// no anomalies recorded for {activeDataset}</p>
            ) : items.map((item) => {
              const isActive = selectedId === item.id;
              const sColor = severityColor(item.severity_level);
              return (
                <button key={item.id} onClick={() => setSelectedId(item.id)} style={{
                  display: 'flex', flexDirection: 'column', padding: '10px 12px', background: isActive ? 'rgba(184,134,42,0.15)' : 'rgba(232,220,195,0.4)',
                  border: `1px solid ${isActive ? C.cyan : C.border}`, borderRadius: 6, cursor: 'pointer', textAlign: 'left', transition: 'all 0.2s',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'JetBrains Mono', fontSize: 10, marginBottom: 4, width: '100%' }}>
                    <span style={{ color: isActive ? C.textPrimary : C.textSec }}>#{item.id} @ tick {item.tick}</span>
                    <span style={{ color: sColor, padding: '2px 6px', background: `${sColor}15`, borderRadius: 4, fontWeight: 700 }}>{item.severity_level}</span>
                  </div>
                  <div style={{ fontFamily: 'Inter', fontSize: 11, color: C.textDim }}>{item.anomaly_type} | score: {item.system_loss.toFixed(4)}</div>
                </button>
              );
            })}
          </div>

          {/* Details */}
          <div className="panel-recessed" style={{ padding: 16, display: 'flex', flexDirection: 'column' }}>
            {isDetailLoading && <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: C.textDim }}>// loading detail...</p>}
            {!isDetailLoading && !selectedItem && <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: C.textDim }}>// select anomaly to inspect detail</p>}
            {!isDetailLoading && selectedItem && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                 <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'JetBrains Mono', fontSize: 11, borderBottom: `1px solid ${C.border}`, paddingBottom: 8 }}>
                    <span style={{ color: C.textSec }}>Anomaly</span><span style={{ color: C.textPrimary, fontWeight: 700 }}>#{selectedItem.id}</span>
                 </div>
                 <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'JetBrains Mono', fontSize: 11, borderBottom: `1px solid ${C.border}`, paddingBottom: 8 }}>
                    <span style={{ color: C.textSec }}>Confidence</span><span style={{ color: C.textPrimary, fontWeight: 700 }}>{(selectedItem.confidence * 100).toFixed(1)}%</span>
                 </div>
                 <div>
                    <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: C.textSec, marginBottom: 8, letterSpacing: '0.1em' }}>HINTS:</div>
                    <ul style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: 0, margin: 0, listStyle: 'none' }}>
                      {selectedItem.investigation_hints.map((hint, i) => (
                        <li key={i} style={{ fontFamily: 'Inter', fontSize: 11, color: C.textPrimary, padding: '6px 10px', background: 'rgba(184,134,42,0.06)', border: `1px solid ${C.border}`, borderRadius: 4 }}>
                          <span style={{ color: C.cyan, marginRight: 6 }}>›</span>{hint}
                        </li>
                      ))}
                    </ul>
                 </div>
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
