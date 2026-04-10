import { useEffect, useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';

type ScoreComponents = {
  recon: number;
  forecast: number;
  corr: number;
};

type AlertExplanation = {
  severity_score: number;
  severity_level: 'info' | 'warning' | 'critical';
  confidence: number;
  anomaly_type: string;
  duration_steps: number;
  top_contributors: Array<{
    sensor: string;
    contribution_pct: number;
  }>;
  investigation_hints: string[];
};

type AnomalySourcePayload = {
  breakdown: {
    contribution_pct: {
      recon: number;
      forecast: number;
      corr: number;
    };
    z_scores: {
      recon: number;
      forecast: number;
      corr: number;
    };
  };
  correlation_change: {
    ready: boolean;
    fro_norm: number;
    top_pair_changes: Array<{
      sensor_a: string;
      sensor_b: string;
      prev_corr: number;
      curr_corr: number;
      delta: number;
      abs_delta: number;
    }>;
  };
};

type AnomalyRecord = {
  id: number;
  created_at_ms: number;
  dataset: string;
  tick: number;
  system_loss: number;
  threshold: number;
  severity_score: number;
  severity_level: string;
  confidence: number;
  anomaly_type: string;
  duration_steps: number;
  top_sensor: string;
  top_contributors: Array<{
    sensor: string;
    contribution_pct: number;
  }>;
  investigation_hints: string[];
  score_components: ScoreComponents;
  anomaly_source?: AnomalySourcePayload | null;
};

type Props = {
  activeDataset: string;
  alertExplanation: AlertExplanation | null;
  anomalySource: AnomalySourcePayload | null;
  scoreComponents: ScoreComponents | null;
  isConnected: boolean;
};

const API_BASE = 'http://127.0.0.1:8000';

const severityClass = (level: string) => {
  if (level === 'critical') return 'border-red-500/50 bg-red-500/10 text-red-300';
  if (level === 'warning') return 'border-yellow-500/50 bg-yellow-500/10 text-yellow-300';
  return 'border-blue-500/50 bg-blue-500/10 text-blue-300';
};

export default function AnomalySourceTab({
  activeDataset,
  alertExplanation,
  anomalySource,
  scoreComponents,
  isConnected,
}: Props) {
  const [items, setItems] = useState<AnomalyRecord[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedItem, setSelectedItem] = useState<AnomalyRecord | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [error, setError] = useState('');

  const loadAnomalies = async () => {
    setIsLoading(true);
    setError('');
    try {
      const response = await fetch(`${API_BASE}/anomalies?dataset=${encodeURIComponent(activeDataset)}&limit=120`);
      if (!response.ok) {
        throw new Error(`failed to load anomalies: ${response.status}`);
      }
      const payload = await response.json();
      const list = (payload.items ?? []) as AnomalyRecord[];
      setItems(list);
      if (list.length > 0 && (selectedId === null || !list.some((x) => x.id === selectedId))) {
        setSelectedId(list[0].id);
      }
      if (list.length === 0) {
        setSelectedId(null);
        setSelectedItem(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'failed to load anomaly list');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    setSelectedId(null);
    setSelectedItem(null);
    void loadAnomalies();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeDataset]);

  useEffect(() => {
    if (selectedId === null) return;
    const fetchDetail = async () => {
      setIsDetailLoading(true);
      try {
        const response = await fetch(`${API_BASE}/anomalies/${selectedId}`);
        if (!response.ok) {
          throw new Error(`failed to load anomaly detail: ${response.status}`);
        }
        const detail = (await response.json()) as AnomalyRecord;
        setSelectedItem(detail);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'failed to load anomaly detail');
      } finally {
        setIsDetailLoading(false);
      }
    };

    void fetchDetail();
  }, [selectedId]);

  const sourceView = useMemo(() => {
    if (selectedItem?.anomaly_source) return selectedItem.anomaly_source;
    return anomalySource;
  }, [selectedItem, anomalySource]);

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <h3 className="text-xs uppercase tracking-widest text-slate-400 mb-3">Live Source Snapshot</h3>
          {!alertExplanation ? (
            <p className="text-xs text-slate-500">Waiting for an anomalous event.</p>
          ) : (
            <div className="space-y-2 text-xs text-slate-300">
              <div className={`inline-block px-2 py-1 rounded border ${severityClass(alertExplanation.severity_level)}`}>
                {alertExplanation.severity_level} | severity {alertExplanation.severity_score}
              </div>
              <div>Type: <span className="text-slate-100 font-semibold">{alertExplanation.anomaly_type.replace('_', ' ')}</span></div>
              <div>Confidence: <span className="text-slate-100 font-semibold">{(alertExplanation.confidence * 100).toFixed(1)}%</span></div>
              {scoreComponents && (
                <div className="text-slate-400 mt-2 leading-5">
                  <div>Recon: {scoreComponents.recon.toFixed(6)}</div>
                  <div>Forecast: {scoreComponents.forecast.toFixed(6)}</div>
                  <div>Corr: {scoreComponents.corr.toFixed(6)}</div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <h3 className="text-xs uppercase tracking-widest text-slate-400 mb-3">Source Breakdown</h3>
          {!sourceView ? (
            <p className="text-xs text-slate-500">Enable FEATURE_ANOMALY_SOURCE_TAB and wait for anomaly frames.</p>
          ) : (
            <div className="space-y-2 text-xs text-slate-300">
              <div>Recon contribution: {sourceView.breakdown.contribution_pct.recon.toFixed(1)}%</div>
              <div>Forecast contribution: {sourceView.breakdown.contribution_pct.forecast.toFixed(1)}%</div>
              <div>Correlation contribution: {sourceView.breakdown.contribution_pct.corr.toFixed(1)}%</div>
              <div className="pt-2 text-slate-400">
                z-scores: r={sourceView.breakdown.z_scores.recon.toFixed(3)} | f={sourceView.breakdown.z_scores.forecast.toFixed(3)} | c={sourceView.breakdown.z_scores.corr.toFixed(3)}
              </div>
            </div>
          )}
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <h3 className="text-xs uppercase tracking-widest text-slate-400 mb-3">Correlation Shift</h3>
          {!sourceView?.correlation_change.ready ? (
            <p className="text-xs text-slate-500">No stable correlation snapshot yet.</p>
          ) : (
            <div className="space-y-2 text-xs text-slate-300">
              <div>Frobenius norm: {sourceView.correlation_change.fro_norm.toFixed(6)}</div>
              <div className="space-y-1 max-h-28 overflow-y-auto pr-1">
                {sourceView.correlation_change.top_pair_changes.slice(0, 5).map((pair) => (
                  <div key={`${pair.sensor_a}-${pair.sensor_b}`} className="border border-slate-800 rounded px-2 py-1 bg-slate-950/40">
                    {pair.sensor_a} vs {pair.sensor_b} | Δ {pair.delta.toFixed(4)}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm uppercase tracking-widest text-slate-400">Historical Anomaly Source Events ({activeDataset})</h3>
          <button
            onClick={() => void loadAnomalies()}
            className="text-xs border border-slate-700 rounded px-3 py-2 text-slate-300 hover:bg-slate-800 transition-colors inline-flex items-center gap-2"
          >
            <RefreshCw className={`w-3 h-3 ${isLoading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        {!isConnected && <p className="text-xs text-yellow-300 mb-3">Backend stream disconnected. Historical records may be stale.</p>}
        {error && <p className="text-xs text-red-300 mb-3">{error}</p>}

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <div className="border border-slate-800 rounded-lg divide-y divide-slate-800 max-h-96 overflow-y-auto">
            {items.length === 0 && !isLoading ? (
              <div className="p-4 text-xs text-slate-500">No anomalies recorded yet for {activeDataset}.</div>
            ) : (
              items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setSelectedId(item.id)}
                  className={`w-full text-left p-3 transition-colors ${selectedId === item.id ? 'bg-slate-800/70' : 'hover:bg-slate-800/40'}`}
                >
                  <div className="flex justify-between text-xs text-slate-200">
                    <span>#{item.id} @ tick {item.tick}</span>
                    <span className={`px-2 py-0.5 rounded border ${severityClass(item.severity_level)}`}>{item.severity_level}</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-400">
                    type={item.anomaly_type} | score={item.system_loss.toFixed(4)} | top={item.top_sensor}
                  </div>
                </button>
              ))
            )}
          </div>

          <div className="border border-slate-800 rounded-lg p-4 bg-slate-950/30">
            {isDetailLoading && <p className="text-xs text-slate-400">Loading anomaly detail...</p>}
            {!isDetailLoading && !selectedItem && <p className="text-xs text-slate-500">Select an anomaly to inspect source details.</p>}
            {!isDetailLoading && selectedItem && (
              <div className="space-y-3 text-xs text-slate-300">
                <div className="flex justify-between">
                  <span className="text-slate-400">Anomaly</span>
                  <span className="font-semibold">#{selectedItem.id}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Confidence</span>
                  <span className="font-semibold">{(selectedItem.confidence * 100).toFixed(1)}%</span>
                </div>
                <div className="text-slate-400">Hints</div>
                <ul className="space-y-1">
                  {selectedItem.investigation_hints.map((hint, idx) => (
                    <li key={`${selectedItem.id}-hint-${idx}`} className="border border-slate-800 rounded px-2 py-1 bg-slate-900/60">{hint}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
