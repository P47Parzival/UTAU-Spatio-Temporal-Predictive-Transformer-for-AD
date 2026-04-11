// RightPanel — Cream Gold HUD Widgets
import { Target, HardDrive, Clock, Shield, Check, AlertTriangle } from 'lucide-react';

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

export function GovernancePanel({ systemState, isSubmitting, feedbackStatus, onAcknowledge, onDismiss }: {
  systemState: SysState; isSubmitting: boolean; feedbackStatus: string;
  onAcknowledge: () => void; onDismiss: () => void;
}) {
  const isHealthy = systemState === 'HEALTHY';

  return (
    <div className="panel" style={{ flexShrink: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
        <Shield size={11} color={isHealthy ? G : CU} />
        <span className="section-label" style={{ color: isHealthy ? G : CU }}>GOVERNANCE LOOP</span>
      </div>
      <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <button className="btn-acknowledge" disabled={isHealthy || isSubmitting} onClick={onAcknowledge}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
            <Check size={11} /> ACKNOWLEDGE ANOMALY
          </div>
        </button>
        <button className="btn-dismiss" disabled={isHealthy || isSubmitting} onClick={onDismiss}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
            <AlertTriangle size={11} /> DISMISS & CALIBRATE
          </div>
        </button>
        {feedbackStatus && (
          <div style={{ padding: '6px 8px', borderRadius: 4, background: 'var(--bg-deep)', border: '1px dashed var(--border)', fontFamily: "'Cormorant Garamond', serif", fontSize: 11, color: TS, fontStyle: 'italic' }}>
            {feedbackStatus}
          </div>
        )}
      </div>
    </div>
  );
}
