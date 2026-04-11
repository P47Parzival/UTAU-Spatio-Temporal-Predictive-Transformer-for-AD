import { useEffect, useMemo, useState } from 'react';
import { RefreshCw, Activity, Layers, ActivitySquare, Database } from 'lucide-react';

type ScoreComponents = { recon: number; forecast: number; corr: number; };
type SensorContributor = { sensor: string; sensor_label?: string; contribution_pct: number; recon_error?: number; forecast_error?: number; };

type SOPHistoryItem = {
  created_at_ms: number;
  mode: 'llm' | 'fallback';
  provider?: string;
  model?: string;
  objective: string;
  constraints?: string[];
  sop: string;
  llm_error?: string | null;
};

type AlertExplanation = {
  severity_score: number; severity_level: 'info' | 'warning' | 'critical';
  confidence: number; anomaly_type: string; duration_steps: number;
  top_contributors: SensorContributor[];
  investigation_hints: string[];
};

type AnomalySourcePayload = {
  breakdown: { contribution_pct: { recon: number; forecast: number; corr: number; }; z_scores: { recon: number; forecast: number; corr: number; }; };
  correlation_change: {
    ready: boolean; fro_norm: number;
    top_pair_changes: Array<{ sensor_a: string; sensor_b: string; sensor_a_label?: string; sensor_b_label?: string; prev_corr: number; curr_corr: number; delta: number; abs_delta: number; }>;
  };
};

type AnomalyRecord = {
  id: number; created_at_ms: number; dataset: string; tick: number; system_loss: number;
  threshold: number; severity_score: number; severity_level: string; confidence: number;
  anomaly_type: string; duration_steps: number; top_sensor: string; top_sensor_label?: string;
  top_contributors: SensorContributor[];
  investigation_hints: string[]; score_components: ScoreComponents;
  sensor_snapshot?: {
    top_sensors?: Array<{ sensor: string; sensor_label?: string; actual: number; forecast: number; abs_residual: number; recon_error: number; forecast_error: number; }>;
  } | null;
  sop_history?: SOPHistoryItem[];
  anomaly_source?: AnomalySourcePayload | null;
};

type Props = {
  activeDataset: string; alertExplanation: AlertExplanation | null;
  anomalySource: AnomalySourcePayload | null; scoreComponents: ScoreComponents | null; isConnected: boolean;
};

const API_BASE = 'http://127.0.0.1:8000';

const C = {
  cyan: 'var(--gold)', amber: 'var(--copper)', red: 'var(--crimson)', violet: 'var(--teal)',
  textPrimary: 'var(--text-primary)', textSec: 'var(--text-secondary)', textDim: 'var(--text-dim)', border: 'var(--border)',
};

const severityColor = (level: string) => {
  if (level === 'critical') return C.red;
  if (level === 'warning') return C.amber;
  return C.cyan;
};

const sensorDisplayName = (sensor?: string, label?: string) => {
  if (label && label.trim()) return label;
  if (!sensor) return 'unknown sensor';
  return sensor.toUpperCase();
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
  const [isSopLoading, setIsSopLoading] = useState(false);
  const [sopText, setSopText] = useState('');
  const [sopMode, setSopMode] = useState<'llm' | 'fallback' | ''>('');
  const [sopError, setSopError] = useState('');

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
    setSopText('');
    setSopMode('');
    setSopError('');
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

  const sourceContributors = useMemo(() => {
    if (selectedItem?.top_contributors?.length) return selectedItem.top_contributors.slice(0, 5);
    if (alertExplanation?.top_contributors?.length) return alertExplanation.top_contributors.slice(0, 5);
    return [] as SensorContributor[];
  }, [selectedItem, alertExplanation]);

  const selectedTopSensors = useMemo(() => {
    return selectedItem?.sensor_snapshot?.top_sensors ?? [];
  }, [selectedItem]);

  const generateSop = async () => {
    if (!selectedItem) return;
    setIsSopLoading(true);
    setSopError('');
    try {
      const response = await fetch(`${API_BASE}/anomalies/${selectedItem.id}/sop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ objective: 'Prevent recurrence at source', max_steps: 8 }),
      });
      if (!response.ok) throw new Error(`failed to generate SOP: ${response.status}`);
      const data = await response.json();
      setSopText(String(data.sop ?? ''));
      setSopMode(data.mode === 'llm' ? 'llm' : 'fallback');
      if (data.history_entry) {
        setSelectedItem((prev) => {
          if (!prev) return prev;
          const prior = prev.sop_history ?? [];
          return { ...prev, sop_history: [...prior, data.history_entry as SOPHistoryItem] };
        });
      }
    } catch (err) {
      setSopError(err instanceof Error ? err.message : 'failed to generate SOP');
    } finally {
      setIsSopLoading(false);
    }
  };

  const sopHistory = useMemo(() => {
    return (selectedItem?.sop_history ?? []).slice().reverse();
  }, [selectedItem]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      
      {/* Top 3 Metric Cards */}
      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 1 }}>
        
        {/* Live Source Snapshot */}
        <div style={{ padding: 32, background: 'var(--bg-card)', border: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 24 }}>
            <Activity size={12} color={C.cyan} />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600, letterSpacing: '0.2em', color: C.cyan }}>LIVE SNAPSHOT</span>
          </div>
          {!alertExplanation ? (
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: C.textDim }}>// awaiting anomalous event...</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{
                display: 'inline-block', alignSelf: 'flex-start', padding: '4px 12px', fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, letterSpacing: '0.15em',
                color: severityColor(alertExplanation.severity_level), border: `1px solid ${severityColor(alertExplanation.severity_level)}40`, background: `${severityColor(alertExplanation.severity_level)}15`
              }}>
                {alertExplanation.severity_level.toUpperCase()} | SCORE: {alertExplanation.severity_score}
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: C.textSec }}>Type: <span style={{ color: C.textPrimary, fontWeight: 600 }}>{alertExplanation.anomaly_type.replace('_', ' ')}</span></div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: C.textSec }}>Confidence: <span style={{ color: C.textPrimary, fontWeight: 600 }}>{(alertExplanation.confidence * 100).toFixed(1)}%</span></div>
              {scoreComponents && (
                <div style={{ marginTop: 8, padding: 12, background: 'var(--bg)', border: `1px solid ${C.border}`, fontFamily: 'var(--font-mono)', fontSize: 10, color: C.textSec, lineHeight: 1.8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Recon</span><span style={{color: C.cyan}}>{scoreComponents.recon.toFixed(6)}</span></div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Forecast</span><span style={{color: C.violet}}>{scoreComponents.forecast.toFixed(6)}</span></div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Corr</span><span style={{color: C.amber}}>{scoreComponents.corr.toFixed(6)}</span></div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Source Breakdown */}
        <div style={{ padding: 32, background: 'var(--bg-card)', border: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 24 }}>
            <Layers size={12} color={C.violet} />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600, letterSpacing: '0.2em', color: C.violet }}>SOURCE BREAKDOWN</span>
          </div>
           {!sourceView && sourceContributors.length === 0 ? (
             <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: C.textDim }}>// waiting for source frames...</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {sourceContributors.length === 0 ? (
                <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: C.textDim }}>// no sensor contributors yet</p>
              ) : sourceContributors.map((contributor, idx) => (
                <div key={contributor.sensor}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 10, marginBottom: 8, letterSpacing: '0.1em' }}>
                    <span style={{ color: C.textSec }}>{sensorDisplayName(contributor.sensor, contributor.sensor_label)}:</span><span style={{ color: idx === 0 ? C.red : C.violet, fontWeight: 700 }}>{contributor.contribution_pct.toFixed(1)}%</span>
                  </div>
                  <div style={{ height: 2, background: 'var(--border)', borderRadius: 0 }}><div style={{ width: `${Math.max(2, Math.min(100, contributor.contribution_pct))}%`, height: '100%', background: idx === 0 ? C.red : C.violet, boxShadow: `0 0 10px ${idx === 0 ? C.red : C.violet}60` }}/></div>
                </div>
              ))}
              <div style={{ marginTop: 2, padding: '10px 12px', background: 'var(--bg)', border: `1px solid ${C.border}`, fontFamily: 'var(--font-mono)', fontSize: 9, color: C.textSec, letterSpacing: '0.15em' }}>
                TOP SENSOR: {sensorDisplayName(sourceContributors[0]?.sensor, sourceContributors[0]?.sensor_label)}
              </div>
              <div style={{ marginTop: 2, padding: '10px 12px', background: 'var(--bg)', border: `1px solid ${C.border}`, fontFamily: 'var(--font-mono)', fontSize: 9, color: C.amber, lineHeight: 1.5 }}>
                NOTE: Source ranking is probabilistic attribution, not guaranteed root-cause causality. Confidence: {((selectedItem?.confidence ?? alertExplanation?.confidence ?? 0) * 100).toFixed(1)}%
              </div>
              {sourceView && (
                <div style={{ marginTop: 8, padding: '10px 12px', background: 'var(--bg)', border: `1px solid ${C.border}`, fontFamily: 'var(--font-mono)', fontSize: 9, color: C.textSec, letterSpacing: '0.15em' }}>
                  Z-SCORES: R {sourceView.breakdown.z_scores.recon.toFixed(3)} | F {sourceView.breakdown.z_scores.forecast.toFixed(3)} | C {sourceView.breakdown.z_scores.corr.toFixed(3)}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Correlation Shift */}
        <div style={{ padding: 32, background: 'var(--bg-card)', border: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 24 }}>
             <ActivitySquare size={12} color={C.amber} />
             <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600, letterSpacing: '0.2em', color: C.amber }}>CORRELATION SHIFT</span>
          </div>
          {!sourceView?.correlation_change.ready ? (
             <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: C.textDim }}>// no stable snapshot yet</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: C.textSec }}>Frobenius Norm: <span style={{ color: C.amber }}>{sourceView.correlation_change.fro_norm.toFixed(6)}</span></div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1, overflowY: 'auto' }}>
                {sourceView.correlation_change.top_pair_changes.slice(0, 5).map((pair) => (
                  <div key={`${pair.sensor_a}-${pair.sensor_b}`} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 10px', background: 'var(--bg)', border: `1px solid ${C.border}`, fontFamily: 'var(--font-mono)', fontSize: 9 }}>
                    <span style={{ color: C.textSec }}>{sensorDisplayName(pair.sensor_a, pair.sensor_a_label)} ↔ {sensorDisplayName(pair.sensor_b, pair.sensor_b_label)}</span>
                    <span style={{ color: C.red }}>Δ {pair.delta.toFixed(4)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div style={{ marginTop: 16, borderTop: `1px solid ${C.border}`, paddingTop: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: C.textSec, letterSpacing: '0.1em' }}>SOP (SOURCE PREVENTION)</div>
              <button
                onClick={() => void generateSop()}
                disabled={isSopLoading || !selectedItem}
                style={{ padding: '6px 12px', border: `1px solid ${C.border}`, background: 'transparent', color: C.textPrimary, fontFamily: 'var(--font-mono)', fontSize: 10, cursor: selectedItem ? 'pointer' : 'not-allowed', opacity: selectedItem ? 1 : 0.6 }}
              >
                {isSopLoading ? 'GENERATING...' : 'GENERATE SOP'}
              </button>
            </div>
            {!selectedItem && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: C.textDim, marginBottom: 8 }}>Select a historical anomaly to generate SOP.</div>}
            {selectedItem && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: C.textSec, marginBottom: 8 }}>
                Context: {selectedItem.anomaly_type.replace('_', ' ')} | {sensorDisplayName(selectedItem.top_sensor, selectedItem.top_sensor_label)}
              </div>
            )}
            {sopError && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: C.red, marginBottom: 8 }}>{sopError}</div>}
            {sopText && (
              <div style={{ border: `1px solid ${C.border}`, background: 'var(--bg)', padding: 12, marginBottom: 10 }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: C.textSec, marginBottom: 8 }}>MODE: {sopMode || 'fallback'}</div>
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)', fontSize: 11, color: C.textPrimary, lineHeight: 1.6 }}>{sopText}</pre>
              </div>
            )}
            {sopHistory.length > 0 && (
              <div style={{ border: `1px solid ${C.border}`, background: 'var(--bg)', padding: 12 }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: C.textSec, marginBottom: 8, letterSpacing: '0.1em' }}>SOP HISTORY ({sopHistory.length})</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 140, overflowY: 'auto' }}>
                  {sopHistory.slice(0, 5).map((item, idx) => (
                    <div key={`${item.created_at_ms}-${idx}`} style={{ border: `1px solid ${C.border}`, background: 'var(--bg-recessed)', padding: 8 }}>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: C.textSec, marginBottom: 6 }}>
                        {new Date(item.created_at_ms).toLocaleString()} | {item.mode.toUpperCase()} | {(item.provider || 'fallback').toUpperCase()}
                      </div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: C.textPrimary, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {item.objective}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Historical List + Detail */}
      <section style={{ padding: 32, background: 'var(--bg-card)', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 400 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Database size={16} color={C.textPrimary} />
            <span style={{ fontFamily: 'var(--font-display)', fontSize: 24, letterSpacing: '0.05em', color: C.textPrimary }}>HISTORICAL ANOMALY SOURCE EVENTS</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: C.textSec, borderLeft: '1px solid var(--border)', paddingLeft: 12 }}>{activeDataset}</span>
          </div>
          <button onClick={() => void loadAnomalies()} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px', background: 'transparent', border: `1px solid ${C.border}`, color: C.textPrimary, fontFamily: 'var(--font-mono)', fontSize: 10, cursor: 'pointer', transition: 'all 0.2s' }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--text-primary)'; e.currentTarget.style.color = 'var(--bg)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = C.textPrimary; }}
          >
            <RefreshCw size={11} className={isLoading ? 'animate-spin' : ''} /> REFRESH
          </button>
        </div>

        {!isConnected && <p style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: C.amber, marginBottom: 8 }}># Backend disconnected. History may be stale.</p>}
        {error && <p style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: C.red, marginBottom: 8 }}>{error}</p>}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr', gap: 0, flex: 1, minHeight: 0, border: '1px solid var(--border)' }}>
          
          {/* List */}
          <div style={{ display: 'flex', flexDirection: 'column', overflowY: 'auto', borderRight: '1px solid var(--border)', background: 'var(--bg)' }}>
            {items.length === 0 && !isLoading ? (
               <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: C.textDim, padding: 24 }}>// no anomalies recorded for {activeDataset}</p>
            ) : items.map((item) => {
              const isActive = selectedId === item.id;
              const sColor = severityColor(item.severity_level);
              return (
                <button key={item.id} onClick={() => setSelectedId(item.id)} style={{
                  display: 'flex', flexDirection: 'column', padding: '16px 20px', background: isActive ? 'var(--gold-dim)' : 'transparent',
                  borderBottom: `1px solid var(--border)`, cursor: 'pointer', textAlign: 'left', transition: 'all 0.2s',
                  borderLeft: isActive ? `2px solid ${C.cyan}` : '2px solid transparent'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 11, marginBottom: 8, width: '100%' }}>
                    <span style={{ color: isActive ? C.textPrimary : C.textSec }}>#{item.id} @ {item.tick}</span>
                    <span style={{ color: sColor, padding: '2px 8px', border: `1px solid ${sColor}40`, background: `${sColor}15`, fontWeight: 600 }}>{item.severity_level.toUpperCase()}</span>
                  </div>
                  <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: C.textDim }}>{item.anomaly_type.replace('_', ' ')} <span style={{ color: C.textSec, fontSize: 12, marginLeft: 8 }}>| sys_loss: {item.system_loss.toFixed(4)}</span></div>
                </button>
              );
            })}
          </div>

          {/* Details */}
          <div style={{ padding: 32, display: 'flex', flexDirection: 'column', background: 'var(--bg-recessed)' }}>
            {isDetailLoading && <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: C.textDim }}>// loading detail...</p>}
            {!isDetailLoading && !selectedItem && <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: C.textDim }}>// select anomaly to inspect detail</p>}
            {!isDetailLoading && selectedItem && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
                 <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 11, borderBottom: `1px solid ${C.border}`, paddingBottom: 12 }}>
                    <span style={{ color: C.textSec }}>Anomaly ID</span><span style={{ color: C.textPrimary, fontWeight: 700 }}>#{selectedItem.id}</span>
                 </div>
                 <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 11, borderBottom: `1px solid ${C.border}`, paddingBottom: 12 }}>
                    <span style={{ color: C.textSec }}>Confidence Score</span><span style={{ color: C.textPrimary, fontWeight: 700 }}>{(selectedItem.confidence * 100).toFixed(1)}%</span>
                 </div>
                 <div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: C.textSec, marginBottom: 12, letterSpacing: '0.1em' }}>INVESTIGATION HINTS:</div>
                    <ul style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 0, margin: 0, listStyle: 'none' }}>
                      {selectedItem.investigation_hints.map((hint, i) => (
                        <li key={i} style={{ fontFamily: 'var(--font-serif)', fontSize: 16, color: C.textPrimary, padding: '12px 16px', background: 'var(--bg)', border: `1px solid ${C.border}` }}>
                          <span style={{ color: C.cyan, marginRight: 12, fontFamily: 'var(--font-mono)' }}>›</span>{hint}
                        </li>
                      ))}
                    </ul>
                 </div>
                 {selectedTopSensors.length > 0 && (
                  <div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: C.textSec, marginBottom: 12, letterSpacing: '0.1em' }}>TOP SENSOR EVIDENCE:</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {selectedTopSensors.slice(0, 3).map((sensorEvidence) => (
                        <div key={sensorEvidence.sensor} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 10, color: C.textSec, padding: '10px 12px', border: `1px solid ${C.border}`, background: 'var(--bg)' }}>
                          <span>{sensorDisplayName(sensorEvidence.sensor, sensorEvidence.sensor_label)} actual {sensorEvidence.actual.toFixed(4)}</span>
                          <span>forecast {sensorEvidence.forecast.toFixed(4)}</span>
                          <span style={{ color: C.red }}>|residual| {sensorEvidence.abs_residual.toFixed(4)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                 )}
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
