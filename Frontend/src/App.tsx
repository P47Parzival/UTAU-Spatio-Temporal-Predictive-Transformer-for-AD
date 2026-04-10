import { useState, useEffect, useRef } from 'react';
import { AegisHeader }  from './components/Header';
import TopologyPanel    from './components/TopologyPanel';
import { HeroSection, ResidualSection } from './components/CenterPanel';
import { IncidentReport, RootCausePanel, SimilarIncidents, GovernancePanel } from './components/RightPanel';
import AnomalySourceTab from './components/AnomalySourceTab';

interface AlertExplanation {
  severity_score: number;
  severity_level: 'info' | 'warning' | 'critical';
  confidence: number;
  anomaly_type: string;
  duration_steps: number;
  top_contributors: { sensor: string; contribution_pct: number }[];
  historical_similar: { tick: number; dataset: string; summary: string; similarity?: number }[];
  investigation_hints: string[];
}

interface DataPoint {
  tick: number; system_loss: number; is_anomalous: boolean; threshold: number;
  score_components?: { recon: number; forecast: number; corr: number };
  alert_explanation?: AlertExplanation;
  [key: string]: any;
}

const DATASET_TABS = [
  { label: 'SMD',       value: 'SMD'       },
  { label: 'MSL',       value: 'MSL'       },
  { label: 'SMAP',      value: 'SMAP'      },
  { label: 'Synthetic', value: 'synthetic' },
];

const featureFlag = (value: unknown, defaultValue = false): boolean => {
  if (typeof value !== 'string') return defaultValue;
  return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase());
};

export default function App() {
  const isAnomalySourceTabEnabled = featureFlag(import.meta.env.VITE_FEATURE_ANOMALY_SOURCE_TAB, true);
  const isRlPolicySuggestionsEnabled = featureFlag(import.meta.env.VITE_FEATURE_RL_POLICY_SUGGESTIONS);

  const [data,                  setData]                  = useState<DataPoint[]>([]);
  const [isConnected,           setIsConnected]           = useState(false);
  const [systemState,           setSystemState]           = useState<'HEALTHY' | 'WARNING' | 'CRITICAL'>('HEALTHY');
  const [dimensions,            setDimensions]            = useState<number>(0);
  const [activeDataset,         setActiveDataset]         = useState('SMD');
  const [isTransitioning,       setIsTransitioning]       = useState(false);
  const [alertExplanation,      setAlertExplanation]      = useState<AlertExplanation | null>(null);
  const [anomalySource,         setAnomalySource]         = useState<any | null>(null);
  const [scoreComponents,       setScoreComponents]       = useState<{ recon: number; forecast: number; corr: number } | null>(null);
  const [feedbackStatus,        setFeedbackStatus]        = useState('');
  const [isSubmittingFeedback,  setIsSubmittingFeedback]  = useState(false);
  const [activeFeatureTab,      setActiveFeatureTab]      = useState<'live' | 'anomaly-source'>('live');

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);

  useEffect(() => {
    let stopped = false;
    const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${wsScheme}://127.0.0.1:8000/ws/stream`;

    const connect = () => {
      if (stopped) return;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => setIsConnected(true);
      ws.onclose = () => {
        setIsConnected(false);
        if (!stopped) {
          reconnectTimerRef.current = window.setTimeout(connect, 1000);
        }
      };
      ws.onerror = () => {
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close();
        }
      };
      ws.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        if (payload.dimensions) {
          setDimensions(prev => (payload.dimensions !== prev ? payload.dimensions : prev));
        }
        const newPoint: DataPoint = {
          tick: payload.tick, system_loss: payload.system_loss,
          is_anomalous: payload.is_anomalous, threshold: payload.threshold,
          score_components: payload.score_components, alert_explanation: payload.alert_explanation,
          ...payload.sensors, ...payload.forecast,
        };
        if (payload.alert_explanation) setAlertExplanation(payload.alert_explanation);
        if (payload.anomaly_source)    setAnomalySource(payload.anomaly_source);
        if (payload.score_components)  setScoreComponents(payload.score_components);
        setData(prev => { const n = [...prev, newPoint]; if (n.length > 50) n.shift(); return n; });
        if (payload.is_anomalous)                               setSystemState('CRITICAL');
        else if (payload.system_loss > payload.threshold * 0.8) setSystemState('WARNING');
        else                                                    setSystemState('HEALTHY');
      };
    };

    connect();
    return () => {
      stopped = true;
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, []);

  const submitFeedback = async (wasAnomaly: boolean, calibrateRequested: boolean, note: string) => {
    const last = data.length ? data[data.length - 1] : null;
    const res = await fetch('http://127.0.0.1:8000/feedback', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        was_anomaly: wasAnomaly, tick: last?.tick, note,
        severity_level: alertExplanation?.severity_level, confidence: alertExplanation?.confidence,
        anomaly_type: alertExplanation?.anomaly_type, calibrate_requested: calibrateRequested,
        system_loss: last?.system_loss, threshold: last?.threshold,
      }),
    });
    if (!res.ok) throw new Error(`feedback submit failed: ${res.status}`);
    return res.json();
  };

  const dismissAlarm = async () => {
    setIsSubmittingFeedback(true); setFeedbackStatus('');
    try {
      await submitFeedback(false, true, 'Operator dismissed alert and requested adaptive calibration.');
      await fetch('http://localhost:8000/calibrate', { method: 'POST' });
      setSystemState('HEALTHY');
      setFeedbackStatus('Dismissed as non-anomalous. Calibration executed.');
    } catch (err) { setFeedbackStatus('Failed to submit dismissal or calibration.'); } 
    finally { setIsSubmittingFeedback(false); }
  };

  const acknowledgeAlert = async () => {
    setIsSubmittingFeedback(true); setFeedbackStatus('');
    try {
      await submitFeedback(true, false, 'Operator acknowledged anomaly alert as valid.');
      setFeedbackStatus('Alert acknowledged. Feedback recorded for retraining.');
    } catch (err) { setFeedbackStatus('Failed to submit acknowledgment feedback.'); } 
    finally { setIsSubmittingFeedback(false); }
  };

  const changeDataset = async (ds: string) => {
    if (ds === activeDataset) return;
    setIsTransitioning(true);
    setData([]); setDimensions(0); setAlertExplanation(null);
    setAnomalySource(null); setScoreComponents(null); setActiveDataset(ds);
    try {
      await fetch('http://127.0.0.1:8000/change_dataset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dataset: ds }) });
    } catch (e) { console.error('Failed to hot-swap dataset:', e); }
    finally { setIsTransitioning(false); }
  };

  const hotSensors = new Set<string>(alertExplanation?.top_contributors.map(c => c.sensor) ?? []);

  return (
    <div id="aegis-root" style={{ display: 'flex', flexDirection: 'column', width: '100vw', height: '100vh', overflow: 'hidden', background: '#F4EDD8' }}>

      {/* Header */}
      <div style={{ height: 56, flexShrink: 0 }} className="hud-header">
        <AegisHeader
          state={systemState} isConnected={isConnected && !isTransitioning}
          tabs={DATASET_TABS} activeDataset={activeDataset} isTransitioning={isTransitioning}
          onChangeDataset={changeDataset} isAnomalySourceTabEnabled={isAnomalySourceTabEnabled}
          isRlPolicySuggestionsEnabled={isRlPolicySuggestionsEnabled}
          activeFeatureTab={activeFeatureTab} onFeatureTabChange={setActiveFeatureTab}
        />
      </div>

      {/* Body */}
      {activeFeatureTab === 'anomaly-source' ? (
        <div className="panel" style={{ margin: 12, overflow: 'auto', padding: 18, flex: 1, minHeight: 0 }}>
          <AnomalySourceTab activeDataset={activeDataset} alertExplanation={alertExplanation} anomalySource={anomalySource} scoreComponents={scoreComponents} isConnected={isConnected} />
        </div>
      ) : (
        /* Standard 3-Column Dashboard */
        <div style={{
          flex: 1, minHeight: 0,
          display: 'grid',
          gridTemplateColumns: '320px 1fr 340px',
          gap: 16, padding: '16px',
        }}>

          {/* LEFT: 3D Asset & Topology */}
          <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            <TopologyPanel activeDataset={activeDataset} scoreComponents={scoreComponents} alertExplanation={alertExplanation} systemState={systemState} />
          </div>

          {/* CENTER: Charts dominating the center */}
          <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Hero score chart */}
            <div style={{ flex: '0 0 45%', minHeight: 0 }}>
              <HeroSection data={data} systemState={systemState} dimensions={dimensions} />
            </div>
            {/* Sensor residuals */}
            <div style={{ flex: 1, minHeight: 0 }}>
              <ResidualSection data={data} dimensions={dimensions} activeDataset={activeDataset} hotSensors={hotSensors} />
            </div>
          </div>

          {/* RIGHT: Incident & Governance */}
          <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', gap: 12, overflow: 'hidden' }}>
            <IncidentReport alertExplanation={alertExplanation} activeDataset={activeDataset} />
            <RootCausePanel alertExplanation={alertExplanation} />
            <SimilarIncidents alertExplanation={alertExplanation} />
            <GovernancePanel systemState={systemState} isSubmitting={isSubmittingFeedback} feedbackStatus={feedbackStatus} onAcknowledge={acknowledgeAlert} onDismiss={dismissAlarm} />
          </div>

        </div>
      )}
    </div>
  );
}
