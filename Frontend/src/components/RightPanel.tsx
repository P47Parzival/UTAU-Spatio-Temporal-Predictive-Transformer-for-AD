// // RightPanel — Cream Gold HUD Widgets
// import { Target, HardDrive, Clock, Shield, Check, AlertTriangle } from 'lucide-react';

// const G  = 'var(--gold)'; const CU = 'var(--copper)'; const CR = 'var(--crimson)'; const VI = 'var(--teal)';
// const TP = 'var(--text-primary)'; const TS = 'var(--text-secondary)'; const TD = 'var(--text-dim)';
// type SysState = 'HEALTHY' | 'WARNING' | 'CRITICAL';
// function accent(s: SysState) { return s === 'CRITICAL' ? CR : s === 'WARNING' ? CU : G; }

// export interface AlertExplanation {
//   severity_level: string; severity_score: number; anomaly_type: string; confidence: number;
//   duration_steps: number;
//   top_contributors: { sensor: string; contribution_pct: number }[];
//   historical_similar: { tick: number; dataset: string; summary: string; similarity?: number }[];
//   investigation_hints: string[];
// }

// export function IncidentReport({ alertExplanation }: { alertExplanation: AlertExplanation | null; activeDataset: string }) {
//   const isCrit = alertExplanation?.severity_level === 'critical';
//   const color  = isCrit ? CR : alertExplanation ? CU : TD;

//   return (
//     <div className="panel" style={{ flexShrink: 0 }}>
//       <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
//         <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
//           <Target size={11} color={color} />
//           <span className="section-label" style={{ color }}>INCIDENT REPORT</span>
//         </div>
//         {alertExplanation && (
//           <div style={{ fontFamily: "'Cinzel', serif", fontSize: 7, fontWeight: 700, color, padding: '2px 8px', borderRadius: 20, border: `1px solid ${color}40`, background: `${color}10`, letterSpacing: '0.18em', animation: isCrit ? 'golden-breathe 1s infinite' : 'none' }}>
//             {alertExplanation.severity_level.toUpperCase()}
//           </div>
//         )}
//       </div>
//       <div className="panel-recessed" style={{ margin: 10, padding: '10px 12px', maxHeight: 110, overflowY: 'auto' }}>
//         {!alertExplanation ? (
//           <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 12, color: TD, fontStyle: 'italic' }}>awaiting event signal…</span>
//         ) : (
//           <pre style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: TS, margin: 0, whiteSpace: 'pre-wrap' }}>
//             <span style={{ color: G }}>{'{'}</span>{'\n'}
//             {'  '}<span style={{ color: '#8B6020' }}>"type"</span>: <span style={{ color: CU }}>"{alertExplanation.anomaly_type}"</span>,{'\n'}
//             {'  '}<span style={{ color: '#8B6020' }}>"confidence"</span>: <span style={{ color: G }}>"{(alertExplanation.confidence * 100).toFixed(1)}%"</span>,{'\n'}
//             {'  '}<span style={{ color: '#8B6020' }}>"duration"</span>: <span style={{ color: G }}>{alertExplanation.duration_steps} steps</span>{'\n'}
//             <span style={{ color: G }}>{'}'}</span>
//           </pre>
//         )}
//       </div>
//     </div>
//   );
// }

// export function RootCausePanel({ alertExplanation }: { alertExplanation: AlertExplanation | null }) {
//   const color = alertExplanation ? CR : TD;
//   return (
//     <div className="panel" style={{ flexShrink: 0 }}>
//       <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
//         <HardDrive size={11} color={color} />
//         <span className="section-label" style={{ color }}>ROOT CAUSE DRIVERS</span>
//       </div>
//       {!alertExplanation ? (
//         <p style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 12, color: TD, padding: '10px 14px', fontStyle: 'italic' }}>no active anomaly</p>
//       ) : (
//         <div style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
//           {alertExplanation.top_contributors.slice(0, 5).map((c, i) => (
//             <div key={c.sensor}>
//               <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
//                 <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: i === 0 ? CR : TS }}>{c.sensor}</span>
//                 <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: i === 0 ? CR : TD, fontWeight: 700 }}>{c.contribution_pct.toFixed(1)}%</span>
//               </div>
//               <div style={{ height: 3, background: 'var(--border-dim)', borderRadius: 99 }}>
//                 <div style={{ height: '100%', width: `${c.contribution_pct}%`, background: i === 0 ? `linear-gradient(90deg, ${CR}80, ${CR})` : `linear-gradient(90deg, ${G}60, ${G})`, borderRadius: 99 }} />
//               </div>
//             </div>
//           ))}
//         </div>
//       )}
//     </div>
//   );
// }

// export function SimilarIncidents({ alertExplanation }: { alertExplanation: AlertExplanation | null }) {
//   const sims = alertExplanation?.historical_similar ?? [];
//   return (
//     <div className="panel" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
//       <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 14px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
//         <Clock size={11} color={TD} />
//         <span className="section-label">SIMILAR INCIDENTS</span>
//       </div>
//       <div style={{ flex: 1, overflowY: 'auto', padding: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
//         {sims.length === 0 ? (
//           <p style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 12, color: TD, fontStyle: 'italic', padding: '4px 4px' }}>no historical matches</p>
//         ) : sims.map((s, i) => (
//           <div key={i} className="panel-recessed" style={{ padding: '7px 10px', borderLeft: `2px solid ${G}30` }}>
//             <div style={{ fontFamily: "'Cinzel', serif", fontSize: 8, color: TS, marginBottom: 4, letterSpacing: '0.1em' }}>{s.dataset} @ tick {s.tick}</div>
//             <p style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 12, color: TD, margin: 0, lineHeight: 1.4 }}>{s.summary.slice(0, 65)}…</p>
//           </div>
//         ))}
//       </div>
//     </div>
//   );
// }

// export function GovernancePanel({ systemState, isSubmitting, feedbackStatus, onAcknowledge, onDismiss }: {
//   systemState: SysState; isSubmitting: boolean; feedbackStatus: string;
//   onAcknowledge: () => void; onDismiss: () => void;
// }) {
//   const isHealthy = systemState === 'HEALTHY';

//   return (
//     <div className="panel" style={{ flexShrink: 0 }}>
//       <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
//         <Shield size={11} color={isHealthy ? G : CU} />
//         <span className="section-label" style={{ color: isHealthy ? G : CU }}>GOVERNANCE LOOP</span>
//       </div>
//       <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
//         <button className="btn-acknowledge" disabled={isHealthy || isSubmitting} onClick={onAcknowledge}>
//           <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
//             <Check size={11} /> ACKNOWLEDGE ANOMALY
//           </div>
//         </button>
//         <button className="btn-dismiss" disabled={isHealthy || isSubmitting} onClick={onDismiss}>
//           <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
//             <AlertTriangle size={11} /> DISMISS & CALIBRATE
//           </div>
//         </button>
//         {feedbackStatus && (
//           <div style={{ padding: '6px 8px', borderRadius: 4, background: 'var(--bg-deep)', border: '1px dashed var(--border)', fontFamily: "'Cormorant Garamond', serif", fontSize: 11, color: TS, fontStyle: 'italic' }}>
//             {feedbackStatus}
//           </div>
//         )}
//       </div>
//     </div>
//   );
// }







import { useEffect, useRef, useState } from 'react';
import { Target, HardDrive, Clock, Shield, Check, AlertTriangle, RefreshCw, Cpu, Zap } from 'lucide-react';

const G  = 'var(--gold)'; const CU = 'var(--copper)'; const CR = 'var(--crimson)'; const VI = 'var(--teal)';
const TP = 'var(--text-primary)'; const TS = 'var(--text-secondary)'; const TD = 'var(--text-dim)';
type SysState = 'HEALTHY' | 'WARNING' | 'CRITICAL';
function accent(s: SysState) { return s === 'CRITICAL' ? CR : s === 'WARNING' ? CU : G; }

export interface AlertExplanation {
  severity_level: string; severity_score: number; anomaly_type: string; confidence: number;
  duration_steps: number;
  top_contributors: { sensor: string; contribution_pct: number }[];
  historical_similar: { tick: number; dataset: string; summary: string; similarity?: number }[];
  investigation_hints: string[];
  degradation_velocity?: number;
  predicted_ttf?: number;
  rul_status?: string;
}

export function PredictiveRULPanel({ alertExplanation }: { alertExplanation: AlertExplanation | null; activeDataset: string }) {
  const isCrit = alertExplanation?.severity_level === 'critical';
  const color  = isCrit ? CR : alertExplanation ? CU : TD;
  
  const velocity = alertExplanation?.degradation_velocity || 0;
  const ttf = alertExplanation?.predicted_ttf || 0;
  const rul_directive = alertExplanation?.rul_status || "Awaiting signature analysis...";

  return (
    <div className="panel" style={{ flexShrink: 0 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Target size={11} color={color} />
          <span className="section-label" style={{ color }}>PREDICTIVE RUL INTELLIGENCE</span>
        </div>
        {alertExplanation && (
          <div style={{ fontFamily: "'Cinzel', serif", fontSize: 7, fontWeight: 700, color, padding: '2px 8px', borderRadius: 20, border: `1px solid ${color}40`, background: `${color}10`, letterSpacing: '0.18em', animation: isCrit ? 'golden-breathe 1s infinite' : 'none' }}>
            {alertExplanation.severity_level.toUpperCase()}
          </div>
        )}
      </div>
      <div className="panel-recessed" style={{ margin: 10, padding: '12px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        {!isCrit && !alertExplanation?.predicted_ttf ? (
          <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 13, color: TD, fontStyle: 'italic', textAlign: 'center' }}>{rul_directive}</span>
        ) : (
          <>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 10, color: TS, fontFamily: "'JetBrains Mono', monospace" }}>TIME TO FAILURE</span>
                <span style={{ fontSize: 10, color: CR, fontFamily: "'JetBrains Mono', monospace", animation: 'golden-breathe 1.5s infinite' }}>
                  T-MINUS 00:{ttf.toString().padStart(2, '0')}:00
                </span>
              </div>
              {/* Velocity Progress Bar representing threshold approach */}
              <div style={{ width: '100%', height: 4, background: 'rgba(0,0,0,0.4)', borderRadius: 2, overflow: 'hidden', border: `1px solid ${CR}30` }}>
                <div style={{ width: `${Math.min(100, Math.max(5, velocity * 10000))}%`, height: '100%', background: CR, transition: 'width 0.4s ease-out' }} />
              </div>
            </div>
            <div style={{ background: 'rgba(231,76,60,0.05)', borderLeft: `2px solid ${CR}`, padding: '6px 10px' }}>
              <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 14, color: TP, lineHeight: 1.3 }}>
                {rul_directive}
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export function RootCausePanel({ alertExplanation }: { alertExplanation: AlertExplanation | null }) {
  const color = alertExplanation ? CR : TD;
  return (
    <div className="panel" style={{ flexShrink: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
        <HardDrive size={11} color={color} />
        <span className="section-label" style={{ color }}>ROOT CAUSE DRIVERS</span>
      </div>
      {!alertExplanation ? (
        <p style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 12, color: TD, padding: '10px 14px', fontStyle: 'italic' }}>no active anomaly</p>
      ) : (
        <div style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {alertExplanation.top_contributors.slice(0, 5).map((c, i) => (
            <div key={c.sensor}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: i === 0 ? CR : TS }}>{c.sensor}</span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: i === 0 ? CR : TD, fontWeight: 700 }}>{c.contribution_pct.toFixed(1)}%</span>
              </div>
              <div style={{ height: 3, background: 'var(--border-dim)', borderRadius: 99 }}>
                <div style={{ height: '100%', width: `${c.contribution_pct}%`, background: i === 0 ? `linear-gradient(90deg, ${CR}80, ${CR})` : `linear-gradient(90deg, ${G}60, ${G})`, borderRadius: 99 }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function SimilarIncidents({ alertExplanation }: { alertExplanation: AlertExplanation | null }) {
  const sims = alertExplanation?.historical_similar ?? [];
  return (
    <div className="panel" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 14px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        <Clock size={11} color={TD} />
        <span className="section-label">SIMILAR INCIDENTS</span>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
        {sims.length === 0 ? (
          <p style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 12, color: TD, fontStyle: 'italic', padding: '4px 4px' }}>no historical matches</p>
        ) : sims.map((s, i) => (
          <div key={i} className="panel-recessed" style={{ padding: '7px 10px', borderLeft: `2px solid ${G}30` }}>
            <div style={{ fontFamily: "'Cinzel', serif", fontSize: 8, color: TS, marginBottom: 4, letterSpacing: '0.1em' }}>{s.dataset} @ tick {s.tick}</div>
            <p style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 12, color: TD, margin: 0, lineHeight: 1.4 }}>{s.summary.slice(0, 65)}…</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── NEW: GovernancePanel with model version badge + retrain indicator ─────────
export function GovernancePanel({
  systemState, isSubmitting, feedbackStatus,
  onAcknowledge, onDismiss,
  modelVersion, retrainRecommended, onManualRetrain, onTriggerAnomaly,
}: {
  systemState: SysState;
  isSubmitting: boolean;
  feedbackStatus: string;
  onAcknowledge: () => void;
  onDismiss: () => void;
  // NEW props — all optional so existing callers without them still compile
  modelVersion?: string;
  retrainRecommended?: boolean;
  onManualRetrain?: () => void;
  onTriggerAnomaly?: () => void;
}) {
  const isHealthy = systemState === 'HEALTHY';
  const [isRetraining, setIsRetraining] = useState(false);
  const [isTriggeringAnomaly, setIsTriggeringAnomaly] = useState(false);
  const retrainResetTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (retrainResetTimerRef.current !== null) {
        window.clearTimeout(retrainResetTimerRef.current);
        retrainResetTimerRef.current = null;
      }
    };
  }, []);

  const handleManualRetrain = async () => {
    if (!onManualRetrain || isRetraining) return;
    setIsRetraining(true);
    try {
      await onManualRetrain();
    } finally {
      // Keep spinner for 3 s so the user knows something happened
      if (retrainResetTimerRef.current !== null) {
        window.clearTimeout(retrainResetTimerRef.current);
      }
      retrainResetTimerRef.current = window.setTimeout(() => {
        setIsRetraining(false);
        retrainResetTimerRef.current = null;
      }, 3000);
    }
  };

  const handleTriggerAnomaly = async () => {
    if (!onTriggerAnomaly || isTriggeringAnomaly) return;
    setIsTriggeringAnomaly(true);
    try {
      await onTriggerAnomaly();
    } finally {
      setIsTriggeringAnomaly(false);
    }
  };

  // Derive a display-friendly version string
  const versionLabel = modelVersion && modelVersion !== 'default' ? modelVersion.toUpperCase() : null;

  return (
    <div className="panel" style={{ flexShrink: 0 }}>
      {/* ── Header row ────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Shield size={11} color={isHealthy ? G : CU} />
          <span className="section-label" style={{ color: isHealthy ? G : CU }}>GOVERNANCE LOOP</span>
        </div>

        {/* Model version badge — only shown once fine-tuning has run at least once */}
        {versionLabel && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 4,
            fontFamily: "'Cinzel', serif", fontSize: 7, fontWeight: 700,
            color: VI, padding: '2px 7px', borderRadius: 20,
            border: `1px solid ${VI}40`, background: `${VI}12`,
            letterSpacing: '0.14em',
          }}>
            <Cpu size={8} color={VI} />
            {versionLabel}
          </div>
        )}
      </div>

      {/* ── Retrain recommended banner ─────────────────────────────────── */}
      {retrainRecommended && (
        <div style={{
          margin: '8px 10px 0',
          padding: '6px 10px',
          borderRadius: 6,
          background: `${CU}14`,
          border: `1px solid ${CU}40`,
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: CU, animation: 'golden-breathe 1s infinite', flexShrink: 0 }} />
          <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 11, color: CU }}>
            Adaptive fine-tune recommended — threshold reached
          </span>
        </div>
      )}

      {/* ── Action buttons ─────────────────────────────────────────────── */}
      <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <button className="btn-acknowledge" disabled={isHealthy || isSubmitting} onClick={onAcknowledge}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
            <Check size={11} /> ACKNOWLEDGE ANOMALY
          </div>
        </button>
        <button className="btn-dismiss" disabled={isHealthy || isSubmitting} onClick={onDismiss}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
            <AlertTriangle size={11} /> DISMISS &amp; CALIBRATE
          </div>
        </button>

        {onTriggerAnomaly && (
          <button
            onClick={handleTriggerAnomaly}
            disabled={isTriggeringAnomaly}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
              padding: '6px 10px', borderRadius: 6, fontSize: 10, fontWeight: 700,
              fontFamily: "'Cinzel', serif", letterSpacing: '0.12em', cursor: isTriggeringAnomaly ? 'not-allowed' : 'pointer',
              border: `1px solid ${CR}60`,
              background: isTriggeringAnomaly ? `${CR}18` : `${CR}0d`,
              color: isTriggeringAnomaly ? TD : CR,
              transition: 'background 0.2s, color 0.2s',
              opacity: isTriggeringAnomaly ? 0.7 : 1,
            }}
          >
            <Zap size={10} />
            {isTriggeringAnomaly ? 'TRIGGERING…' : 'TRIGGER TEST ANOMALY'}
          </button>
        )}

        {/* Manual retrain — always shown; disabled while a retrain is running */}
        {onManualRetrain && (
          <button
            onClick={handleManualRetrain}
            disabled={isRetraining}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
              padding: '6px 10px', borderRadius: 6, fontSize: 10, fontWeight: 600,
              fontFamily: "'Cinzel', serif", letterSpacing: '0.1em', cursor: isRetraining ? 'not-allowed' : 'pointer',
              border: `1px solid ${VI}60`,
              background: isRetraining ? `${VI}14` : `${VI}0d`,
              color: isRetraining ? TD : VI,
              transition: 'background 0.2s, color 0.2s',
              opacity: isRetraining ? 0.6 : 1,
            }}
          >
            <RefreshCw size={10} style={{ animation: isRetraining ? 'spin 1s linear infinite' : 'none' }} />
            {isRetraining ? 'FINE-TUNING…' : 'MANUAL RETRAIN'}
          </button>
        )}

        {feedbackStatus && (
          <div style={{ padding: '6px 8px', borderRadius: 4, background: 'var(--bg-deep)', border: '1px dashed var(--border)', fontFamily: "'Cormorant Garamond', serif", fontSize: 11, color: TS, fontStyle: 'italic' }}>
            {feedbackStatus}
          </div>
        )}
      </div>
    </div>
  );
}