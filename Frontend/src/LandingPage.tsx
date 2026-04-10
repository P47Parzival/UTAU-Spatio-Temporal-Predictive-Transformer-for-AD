import React, { useEffect, useRef, useState } from 'react';

const GOLD = '#C9922A';
const GOLD_BRIGHT = '#E8B84B';
const CRIMSON = '#C0392B';
const COPPER = '#B87333';

/* ── Google Fonts inject ── */
function FontLoader() {
  useEffect(() => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href =
      'https://fonts.googleapis.com/css2?family=Bebas+Neue&family=IBM+Plex+Mono:wght@400;500;600&family=Playfair+Display:ital,wght@0,400;0,700;1,400&display=swap';
    document.head.appendChild(link);
  }, []);
  return null;
}

/* ── CSS Variables + Global Styles ── */
const GLOBAL_CSS = `
  :root {
    --gold: #C9922A;
    --gold-bright: #E8B84B;
    --gold-dim: rgba(201,146,42,0.08);
    --gold-glow: 0 0 40px rgba(201,146,42,0.25);
    --crimson: #C0392B;
    --copper: #B87333;
    --bg: #080807;
    --bg-panel: #0E0D0C;
    --bg-card: #121110;
    --border: rgba(201,146,42,0.12);
    --border-light: rgba(201,146,42,0.06);
    --text: #F0EBE0;
    --text-muted: #7A7060;
    --text-dim: #3D3830;
    --font-display: 'Bebas Neue', sans-serif;
    --font-mono: 'IBM Plex Mono', monospace;
    --font-serif: 'Playfair Display', serif;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html { scroll-behavior: smooth; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-mono);
    overflow-x: hidden;
    line-height: 1;
  }
  body::before {
    content: '';
    position: fixed; inset: 0;
    background-image:
      linear-gradient(rgba(201,146,42,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(201,146,42,0.03) 1px, transparent 1px);
    background-size: 60px 60px;
    pointer-events: none;
    z-index: 0;
  }
  @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
  @keyframes pulse-inner { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.5;transform:scale(.7)} }
  @keyframes blink { 0%,90%,100%{opacity:1} 45%{opacity:.2} }
  @keyframes ticker { from{transform:translateX(0)} to{transform:translateX(-50%)} }
  @keyframes countup { from{opacity:0;transform:scale(.8)} to{opacity:1;transform:scale(1)} }
  .ring { position: absolute; border-radius: 50%; border: 1px solid var(--border); }
  .ring-1 { inset: 0; animation: spin 40s linear infinite; }
  .ring-2 { inset: 40px; animation: spin 25s linear infinite reverse; }
  .ring-3 { inset: 80px; animation: spin 60s linear infinite; }
  .ring-1::after, .ring-2::after {
    content: '';
    position: absolute;
    width: 8px; height: 8px;
    background: var(--gold);
    border-radius: 50%;
    top: 50%; left: -4px;
    transform: translateY(-50%);
    box-shadow: 0 0 10px var(--gold);
  }
  .ring-2::after { background: var(--copper); box-shadow: 0 0 10px var(--copper); }
  .nodes-spin { animation: spin 20s linear infinite; }
  .logo-icon-inner { animation: pulse-inner 2s ease-in-out infinite; }
  .eyebrow-dot { animation: blink 2.5s ease-in-out infinite; }
  .live-dot { animation: blink 1.5s ease-in-out infinite; }
  .ticker-track { animation: ticker 30s linear infinite; }
  .core-value-anim { animation: countup 1s ease-out forwards; }
  .fade-in { opacity: 0; transform: translateY(20px); transition: opacity .7s ease, transform .7s ease; }
  .fade-in.visible { opacity: 1; transform: translateY(0); }
`;

function GlobalStyles() {
  return <style dangerouslySetInnerHTML={{ __html: GLOBAL_CSS }} />;
}

/* ── TICKER DATA ── */
const TICKER_ITEMS = [
  { dot: 'green', text: 'SUBSYSTEM A', val: '99.97%', unit: 'UPTIME' },
  { dot: 'amber', text: 'THERMAL NODE 12', val: '+2.4°C', unit: 'DRIFT' },
  { dot: 'green', text: 'KAFKA INGEST', val: '48,291', unit: 'MSG/S' },
  { dot: 'green', text: 'FORECAST ACCURACY', val: '98.3%', unit: '' },
  { dot: 'red', text: 'ANOMALY THRESHOLD BREACH — SECTOR 7 — ROLLBACK INITIATED', val: '', unit: '' },
  { dot: 'green', text: 'INFLUXDB WRITE LATENCY', val: '0.4ms', unit: '' },
  { dot: 'green', text: 'RL POLICY UPDATE', val: 'CYCLE 1,847', unit: '' },
  { dot: 'amber', text: 'VIBRATION SENSOR V-04', val: 'RECALIBRATING', unit: '' },
];

const dotColors = {
  green: { bg: '#27AE60', shadow: '#27AE60' },
  amber: { bg: GOLD, shadow: GOLD },
  red: { bg: CRIMSON, shadow: CRIMSON },
};

function Ticker() {
  const doubled = [...TICKER_ITEMS, ...TICKER_ITEMS];
  return (
    <div style={{
      background: 'rgba(201,146,42,0.05)',
      borderBottom: '1px solid var(--border-light)',
      padding: '8px 0',
      overflow: 'hidden',
      position: 'relative',
      zIndex: 10,
    }}>
      <div className="ticker-track" style={{ display: 'flex', gap: 80, whiteSpace: 'nowrap', width: 'max-content' }}>
        {doubled.map((item, i) => {
          const dc = dotColors[item.dot];
          return (
            <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 500, letterSpacing: '0.15em', color: 'var(--text-muted)' }}>
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: dc.bg, boxShadow: `0 0 6px ${dc.shadow}`, flexShrink: 0, display: 'inline-block' }} />
              {item.text}&nbsp;
              {item.val && <span style={{ color: 'var(--text)', fontWeight: 600 }}>{item.val}</span>}
              {item.unit && <>&nbsp;{item.unit}</>}
            </span>
          );
        })}
      </div>
    </div>
  );
}

/* ── NAV ── */
function Nav({ onLaunch }) {
  return (
    <nav style={{
      position: 'sticky', top: 0, zIndex: 100,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '0 48px', height: 64,
      background: 'rgba(8,8,7,0.92)',
      borderBottom: '1px solid var(--border)',
      backdropFilter: 'blur(12px)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ width: 32, height: 32, border: '1.5px solid var(--gold)', transform: 'rotate(45deg)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div className="logo-icon-inner" style={{ width: 12, height: 12, background: 'var(--gold)' }} />
        </div>
        <span style={{ fontFamily: 'var(--font-display)', fontSize: 22, letterSpacing: '0.2em', color: 'var(--text)' }}>
          UTAU<span style={{ color: 'var(--gold)' }}>-IIoT</span>
        </span>
      </div>

      <ul style={{ display: 'flex', alignItems: 'center', gap: 32, listStyle: 'none' }}>
        {['ARCHITECTURE', 'TELEMETRY', 'GOVERNANCE', 'DOCS'].map(l => (
          <li key={l}>
            <a href="#" style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 500, letterSpacing: '0.18em', color: 'var(--text-muted)', textDecoration: 'none' }}
              onMouseEnter={e => e.currentTarget.style.color = 'var(--gold)'}
              onMouseLeave={e => e.currentTarget.style.color = 'var(--text-muted)'}
            >{l}</a>
          </li>
        ))}
      </ul>

      <button onClick={onLaunch} style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '9px 20px',
        border: '1px solid var(--gold)', background: 'var(--gold-dim)',
        fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600, letterSpacing: '0.15em',
        color: 'var(--gold)', cursor: 'pointer',
      }}
        onMouseEnter={e => { e.currentTarget.style.background = 'rgba(201,146,42,0.16)'; e.currentTarget.style.boxShadow = 'var(--gold-glow)'; }}
        onMouseLeave={e => { e.currentTarget.style.background = 'var(--gold-dim)'; e.currentTarget.style.boxShadow = 'none'; }}
      >
        INITIALIZE SYSTEM →
      </button>
    </nav>
  );
}

/* ── VISUAL CORE ── */
function VisualCore() {
  const [coreVal, setCoreVal] = useState('98.3');
  useEffect(() => {
    const t = setInterval(() => {
      setCoreVal((97.8 + Math.random() * 0.8).toFixed(1));
    }, 3000);
    return () => clearInterval(t);
  }, []);

  const nodes = [
    { val: '4.2ms', lbl: 'LATENCY', style: { top: 20, left: '50%', transform: 'translateX(-50%)' } },
    { val: '48K', lbl: 'MSG/S', style: { top: '50%', right: 10, transform: 'translateY(-50%)' } },
    { val: '1,847', lbl: 'CYCLES', style: { bottom: 20, left: '50%', transform: 'translateX(-50%)' } },
    { val: '0.3%', lbl: 'ERR RATE', style: { top: '50%', left: 10, transform: 'translateY(-50%)' } },
  ];

  return (
    <div style={{ position: 'relative', width: 520, height: 520 }}>
      <div className="ring ring-1" />
      <div className="ring ring-2" />
      <div className="ring ring-3" />

      {/* Core hexagon */}
      <div style={{
        position: 'absolute', inset: 130,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--bg-card)',
        clipPath: 'polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%)',
      }}>
        <div style={{ position: 'relative', zIndex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
          <div className="core-value-anim" style={{ fontFamily: 'var(--font-display)', fontSize: 52, letterSpacing: '0.05em', color: 'var(--gold)' }}>
            {coreVal}
          </div>
          <div style={{ fontSize: 9, fontWeight: 600, letterSpacing: '0.2em', color: 'var(--text-muted)', textAlign: 'center', lineHeight: 1.4 }}>
            HEALTH<br />SCORE
          </div>
          <div style={{ fontSize: 9, color: '#27AE60', letterSpacing: '0.15em', marginTop: 4 }}>● OPERATIONAL</div>
        </div>
      </div>

      {/* Satellite nodes */}
      <div className="nodes-spin" style={{ position: 'absolute', inset: 0 }}>
        {nodes.map((n, i) => (
          <div key={i} style={{
            position: 'absolute', width: 56, height: 56,
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 2,
            ...n.style,
          }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600, color: 'var(--gold)' }}>{n.val}</div>
            <div style={{ fontSize: 7, fontWeight: 600, letterSpacing: '0.12em', color: 'var(--text-muted)', textAlign: 'center' }}>{n.lbl}</div>
          </div>
        ))}
      </div>

      {/* Connector lines */}
      <svg style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }} viewBox="0 0 520 520" xmlns="http://www.w3.org/2000/svg">
        {[[260, 24, 260, 130], [496, 260, 390, 260], [260, 496, 260, 390], [24, 260, 130, 260]].map(([x1, y1, x2, y2], i) => (
          <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(201,146,42,0.15)" strokeWidth="1" strokeDasharray="4 4" />
        ))}
      </svg>
    </div>
  );
}

/* ── HERO ── */
function Hero({ onLaunch }) {
  return (
    <section style={{
      position: 'relative', zIndex: 10,
      minHeight: 'calc(100vh - 64px - 37px)',
      display: 'grid', gridTemplateColumns: '1fr 1fr',
      alignItems: 'center',
      padding: '0 48px 0 64px', gap: 0, overflow: 'hidden',
    }}>
      {/* radial glow */}
      <div style={{ position: 'absolute', right: -100, top: '50%', transform: 'translateY(-50%)', width: 700, height: 700, borderRadius: '50%', background: 'radial-gradient(ellipse, rgba(201,146,42,0.06) 0%, transparent 65%)', pointerEvents: 'none' }} />

      {/* Left */}
      <div style={{ paddingRight: 48 }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10, marginBottom: 40, padding: '6px 14px', border: '1px solid var(--border)', background: 'var(--bg-card)' }}>
          <span className="eyebrow-dot" style={{ width: 7, height: 7, borderRadius: '50%', background: '#27AE60', boxShadow: '0 0 8px #27AE60', display: 'inline-block' }} />
          <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.2em', color: 'var(--text-muted)' }}>ALL SYSTEMS NOMINAL</span>
          <span style={{ color: 'var(--border)' }}>|</span>
          <span style={{ fontSize: 10, color: 'var(--gold)', fontWeight: 500, letterSpacing: '0.1em' }}>V4.2.1-STABLE</span>
        </div>

        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 'clamp(72px, 8vw, 108px)', lineHeight: 0.9, letterSpacing: '0.02em', color: 'var(--text)', marginBottom: 12 }}>
          SELF-HEALING<br />
          <span style={{ color: 'var(--gold)' }}>INDUSTRIAL</span><br />
          <span style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 'clamp(52px, 5.5vw, 72px)', fontWeight: 400, color: 'var(--text-muted)', letterSpacing: '0.01em', display: 'block' }}>
            intelligence.
          </span>
        </h1>

        <div style={{ width: 80, height: 1, background: 'linear-gradient(90deg, var(--gold), transparent)', margin: '32px 0' }} />

        <p style={{ fontFamily: 'var(--font-serif)', fontSize: 17, lineHeight: 1.7, color: 'var(--text-muted)', maxWidth: 460, marginBottom: 48 }}>
          Continuous multi-signal forecasting for critical industrial telemetry. Utau-IIoT isolates structural degradation and executes autonomic canary rollbacks before infrastructure fails.
        </p>

        <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
          <button onClick={onLaunch} style={{
            display: 'inline-flex', alignItems: 'center', gap: 12,
            padding: '15px 32px', background: 'var(--gold)',
            border: '1px solid var(--gold-bright)',
            fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, letterSpacing: '0.15em',
            color: '#0A0800', cursor: 'pointer', transition: 'all .2s',
          }}
            onMouseEnter={e => { e.currentTarget.style.background = GOLD_BRIGHT; e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 8px 32px rgba(201,146,42,0.3)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = GOLD; e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = 'none'; }}
          >ENTER DASHBOARD →</button>

          <button style={{
            display: 'inline-flex', alignItems: 'center', gap: 10,
            padding: '15px 32px', background: 'transparent',
            border: '1px solid var(--text-dim)',
            fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 500, letterSpacing: '0.15em',
            color: 'var(--text-muted)', cursor: 'pointer', transition: 'all .2s',
          }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text)'; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--text-dim)'; e.currentTarget.style.color = 'var(--text-muted)'; }}
          >VIEW ARCHITECTURE</button>
        </div>
      </div>

      {/* Right */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <VisualCore />
      </div>
    </section>
  );
}

/* ── STATS BAR ── */
const STATS = [
  { idx: '01', val: '99', suffix: '.97%', label: 'System Uptime SLA', delta: '+0.02%' },
  { idx: '02', val: '0.4', suffix: 'ms', label: 'Mean Ingest Latency', delta: null },
  { idx: '03', val: '48', suffix: 'K/s', label: 'Peak Telemetry Throughput', delta: '+12%' },
  { idx: '04', val: '1', suffix: 'ms', label: 'Anomaly Detection TTD', delta: null },
];

function StatsBar() {
  return (
    <div style={{ position: 'relative', zIndex: 10, display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)' }}>
      {STATS.map((s, i) => (
        <StatCell key={i} {...s} isLast={i === STATS.length - 1} delay={i * 0.1} />
      ))}
    </div>
  );
}

function StatCell({ idx, val, suffix, label, delta, isLast, delay }) {
  const [hov, setHov] = useState(false);
  return (
    <div className="fade-in" style={{
      padding: '40px 48px',
      borderRight: isLast ? 'none' : '1px solid var(--border)',
      position: 'relative', overflow: 'hidden',
      background: hov ? 'var(--gold-dim)' : 'transparent',
      transitionDelay: `${delay}s`,
      transition: 'background .3s',
    }}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
    >
      {/* bottom line on hover */}
      <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 2, background: 'var(--gold)', transform: hov ? 'scaleX(1)' : 'scaleX(0)', transition: 'transform .3s', transformOrigin: 'left' }} />
      <div style={{ fontSize: 9, fontWeight: 600, letterSpacing: '0.15em', color: 'var(--text-dim)', marginBottom: 12 }}>{idx}</div>
      <div style={{ fontFamily: 'var(--font-display)', fontSize: 56, lineHeight: 1, color: 'var(--text)', marginBottom: 8, letterSpacing: '0.02em' }}>
        {val}<span style={{ color: 'var(--gold)' }}>{suffix}</span>
      </div>
      <div style={{ fontSize: 10, fontWeight: 500, letterSpacing: '0.12em', color: 'var(--text-muted)', textTransform: 'uppercase' }}>{label}</div>
      {delta && (
        <div style={{ position: 'absolute', top: 40, right: 48, fontSize: 10, fontWeight: 600, letterSpacing: '0.1em', color: '#27AE60', display: 'flex', alignItems: 'center', gap: 4 }}>
          ▲ {delta}
        </div>
      )}
    </div>
  );
}

/* ── ARCHITECTURE ── */
const ARCH_CARDS = [
  {
    num: '01', labelClass: 'gold', label: 'INGEST LAYER',
    pipeline: ['KAFKA', 'INFLUXDB', 'REDIS'],
    title: 'STREAMING\nINGEST ENGINE',
    desc: 'Zero-latency event bus ingesting highly concurrent multi-dimensional telemetry feeds from critical edge nodes across distributed infrastructure.',
  },
  {
    num: '02', labelClass: 'red', label: 'INTELLIGENCE LAYER',
    pipeline: ['RECON', 'FORECAST', 'CORRELATE'],
    title: 'STP-TranAD\nFORECASTING',
    desc: 'Tri-metric contextual modeling isolates anomalous structural degradation across interdependent sub-systems with 98.3% detection accuracy.',
  },
  {
    num: '03', labelClass: 'copper', label: 'GOVERNANCE LAYER',
    pipeline: ['RL POLICY', 'CANARY', 'ROLLBACK'],
    title: 'AUTONOMIC\nGOVERNANCE',
    desc: 'Closed-loop feedback control implementing immediate mitigation workflows when threat confidence exceeds defined operational thresholds.',
  },
];

const labelColors = { gold: GOLD, red: CRIMSON, copper: COPPER };

function ArchSection() {
  return (
    <section style={{ position: 'relative', zIndex: 10, padding: '120px 64px' }}>
      <SectionLabel num="02" text="ENTERPRISE ARCHITECTURE" />
      <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 'clamp(48px,6vw,80px)', letterSpacing: '0.02em', lineHeight: 0.95, color: 'var(--text)', marginBottom: 24 }}>
        ENGINEERED<br />FOR RESILIENCE.
        <span style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', color: 'var(--text-muted)', fontSize: '0.7em', fontWeight: 400, display: 'block' }}>
          Three pillars. Zero tolerance.
        </span>
      </h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 1, border: '1px solid var(--border)', background: 'var(--border)', marginTop: 64 }}>
        {ARCH_CARDS.map((c, i) => <ArchCard key={i} {...c} delay={i * 0.15} />)}
      </div>
    </section>
  );
}

function ArchCard({ num, labelClass, label, pipeline, title, desc, delay }) {
  const [hov, setHov] = useState(false);
  return (
    <div className="fade-in" style={{
      background: hov ? 'var(--bg-card)' : 'var(--bg-panel)',
      padding: '56px 48px', position: 'relative', overflow: 'hidden',
      transition: 'background .3s', transitionDelay: `${delay}s`,
    }}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
    >
      {/* big background number */}
      <div style={{ position: 'absolute', right: 32, top: 32, fontFamily: 'var(--font-display)', fontSize: 80, letterSpacing: '0.02em', color: 'rgba(201,146,42,0.05)', lineHeight: 1, pointerEvents: 'none' }}>{num}</div>

      <span style={{ fontSize: 9, fontWeight: 600, letterSpacing: '0.2em', marginBottom: 32, padding: '4px 10px', display: 'inline-block', border: '1px solid', color: labelColors[labelClass], borderColor: `${labelColors[labelClass]}33` }}>
        {label}
      </span>

      <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap', marginBottom: 24 }}>
        {pipeline.map((p, i) => (
          <React.Fragment key={i}>
            <span style={{ fontSize: 9, fontWeight: 600, letterSpacing: '0.12em', color: 'var(--text-dim)', padding: '3px 8px', border: '1px solid var(--text-dim)' }}>{p}</span>
            {i < pipeline.length - 1 && <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>→</span>}
          </React.Fragment>
        ))}
      </div>

      <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 28, letterSpacing: '0.05em', color: 'var(--text)', marginBottom: 16, lineHeight: 1.1, whiteSpace: 'pre-line' }}>{title}</h3>
      <p style={{ fontFamily: 'var(--font-serif)', fontSize: 16, lineHeight: 1.65, color: 'var(--text-muted)' }}>{desc}</p>
    </div>
  );
}

/* ── SIGNAL CHART (canvas) ── */
function SignalChart() {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);
  const dataRef = useRef([]);

  useEffect(() => {
    const NUM = 80;
    function genSignal() {
      const d = [];
      for (let i = 0; i < NUM; i++) {
        let v = 0.5 + Math.sin(i * 0.18) * 0.25 + Math.random() * 0.12;
        if (i > 55 && i < 68) v += (i - 55) * 0.07 + Math.random() * 0.2;
        d.push(parseFloat(v.toFixed(2)));
      }
      return d;
    }
    dataRef.current = genSignal();

    // Dynamically load Chart.js
    const existingScript = document.querySelector('script[data-chartjs]');
    const load = (cb) => {
      if (window.Chart) { cb(); return; }
      const s = document.createElement('script');
      s.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js';
      s.setAttribute('data-chartjs', '1');
      s.onload = cb;
      document.head.appendChild(s);
    };

    load(() => {
      if (!canvasRef.current) return;
      const ctx = canvasRef.current.getContext('2d');
      chartRef.current = new window.Chart(ctx, {
        type: 'line',
        data: {
          labels: Array.from({ length: NUM }, (_, i) => i),
          datasets: [
            {
              data: dataRef.current,
              borderColor: GOLD,
              borderWidth: 1.5,
              pointRadius: 0,
              fill: true,
              backgroundColor: (context) => {
                const c = context.chart.ctx;
                const g = c.createLinearGradient(0, 0, 0, 160);
                g.addColorStop(0, 'rgba(201,146,42,0.2)');
                g.addColorStop(1, 'rgba(201,146,42,0)');
                return g;
              },
              tension: 0.4,
            },
            {
              data: dataRef.current.map(v => parseFloat((v + 0.1).toFixed(2))),
              borderColor: 'rgba(192,57,43,0.5)',
              borderWidth: 1,
              borderDash: [4, 4],
              pointRadius: 0,
              fill: false,
              tension: 0.4,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          plugins: { legend: { display: false }, tooltip: { enabled: false } },
          scales: {
            x: { display: false },
            y: {
              display: true,
              grid: { color: 'rgba(201,146,42,0.06)', drawBorder: false },
              ticks: { color: '#3D3830', font: { size: 9, family: "'IBM Plex Mono', monospace" }, maxTicksLimit: 4 },
              border: { display: false },
            },
          },
        },
      });

      const interval = setInterval(() => {
        dataRef.current.shift();
        const v = parseFloat((0.5 + Math.sin(Date.now() * 0.001) * 0.25 + Math.random() * 0.12).toFixed(2));
        dataRef.current.push(v);
        chartRef.current.data.datasets[0].data = dataRef.current;
        chartRef.current.data.datasets[1].data = dataRef.current.map(d => parseFloat((d + 0.1).toFixed(2)));
        chartRef.current.update();
      }, 800);

      return () => clearInterval(interval);
    });

    return () => { if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null; } };
  }, []);

  return (
    <div style={{ border: '1px solid var(--border)', background: 'var(--bg)', padding: 32, position: 'relative' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 32 }}>
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.15em', color: 'var(--text-muted)' }}>VIBRATION SPECTRUM — COMPRESSOR UNIT C-07</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 9, fontWeight: 600, letterSpacing: '0.15em', color: '#27AE60' }}>
          <span className="live-dot" style={{ width: 6, height: 6, borderRadius: '50%', background: '#27AE60', boxShadow: '0 0 6px #27AE60', display: 'inline-block' }} />
          LIVE FEED
        </span>
      </div>
      <div style={{ position: 'relative', height: 160 }}>
        <canvas ref={canvasRef} style={{ width: '100%', height: 160 }} />
        {/* Anomaly marker */}
        <div style={{ position: 'absolute', top: 0, bottom: 0, left: `${(60 / 80) * 100}%`, width: 1, background: 'rgba(192,57,43,0.6)', pointerEvents: 'none' }}>
          <span style={{ position: 'absolute', top: -20, left: 4, fontSize: 8, fontWeight: 600, letterSpacing: '0.12em', color: CRIMSON }}>ANOMALY</span>
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12 }}>
        {['T-60s', 'T-45s', 'T-30s', 'T-15s', 'NOW'].map(l => (
          <span key={l} style={{ fontSize: 9, color: 'var(--text-dim)', letterSpacing: '0.08em' }}>{l}</span>
        ))}
      </div>
    </div>
  );
}

/* ── ALERT CARDS ── */
const ALERTS = [
  {
    sev: 'critical', badge: 'CRITICAL', time: '00:42:17',
    title: 'Resonance Frequency Breach',
    desc: 'Sector 7 — Compressor C-07 shows 3σ deviation from baseline spectral signature.',
    metricVal: '847', metricUnit: 'Hz', metricLabel: 'PEAK FREQUENCY',
    action: 'ROLLBACK ↗', actionNote: 'CANARY ACTIVE',
  },
  {
    sev: 'warning', badge: 'WARNING', time: '00:38:52',
    title: 'Thermal Drift Detected',
    desc: 'Node TH-12 reporting +2.4°C above projected thermal envelope model.',
    metricVal: '+2.4', metricUnit: '°C', metricLabel: 'DELTA TEMP',
    action: 'MONITORING', actionNote: 'THRESHOLD 3.0°C',
  },
  {
    sev: 'nominal', badge: 'NOMINAL', time: '00:35:00',
    title: 'Pressure Subsystem P-02',
    desc: 'All sensors within operational envelope. RL policy stable at cycle 1,847.',
    metricVal: '99.97', metricUnit: '%', metricLabel: 'HEALTH SCORE',
    action: null, actionNote: null,
  },
];

const sevColors = { critical: CRIMSON, warning: GOLD, nominal: '#27AE60' };
const sevBg = { critical: 'rgba(192,57,43,0.1)', warning: 'var(--gold-dim)', nominal: 'rgba(39,174,96,0.08)' };

function AlertCard({ alert, delay }) {
  const c = sevColors[alert.sev];
  return (
    <div className="fade-in" style={{
      background: 'var(--bg)', border: `1px solid var(--border)`, borderLeft: `2px solid ${c}`,
      padding: '20px 24px', transitionDelay: `${delay}s`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontSize: 8, fontWeight: 600, letterSpacing: '0.15em', padding: '2px 8px', color: c, background: sevBg[alert.sev] }}>{alert.badge}</span>
        <span style={{ fontSize: 9, color: 'var(--text-dim)', letterSpacing: '0.08em' }}>{alert.time}</span>
      </div>
      <div style={{ fontSize: 12, fontWeight: 500, letterSpacing: '0.05em', color: 'var(--text)', marginBottom: 4 }}>{alert.title}</div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: '0.05em', lineHeight: 1.5 }}>{alert.desc}</div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--border-light)' }}>
        <div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 24, letterSpacing: '0.05em', color: c }}>
            {alert.metricVal}<span style={{ fontSize: 14 }}>{alert.metricUnit}</span>
          </div>
          <div style={{ fontSize: 9, color: 'var(--text-dim)', letterSpacing: '0.1em' }}>{alert.metricLabel}</div>
        </div>
        {alert.action && (
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, color: c, letterSpacing: '0.1em', fontWeight: 600 }}>{alert.action}</div>
            <div style={{ fontSize: 9, color: 'var(--text-dim)', letterSpacing: '0.08em', marginTop: 2 }}>{alert.actionNote}</div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── MONITOR SECTION ── */
function MonitorSection() {
  return (
    <div style={{ position: 'relative', zIndex: 10, padding: '80px 64px', borderTop: '1px solid var(--border)', background: 'var(--bg-panel)' }}>
      <SectionLabel num="03" text="LIVE SIGNAL MONITOR" />
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 48, alignItems: 'start' }}>
        <SignalChart />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {ALERTS.map((a, i) => <AlertCard key={i} alert={a} delay={i * 0.15} />)}
        </div>
      </div>
    </div>
  );
}

/* ── FOOTER CTA ── */
function FooterCTA({ onLaunch }) {
  return (
    <div className="fade-in" style={{
      position: 'relative', zIndex: 10,
      padding: '120px 64px',
      borderTop: '1px solid var(--border)',
      display: 'grid', gridTemplateColumns: '1fr auto',
      alignItems: 'center', gap: 48,
      background: 'var(--bg)', overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', left: 64, bottom: -60, width: 400, height: 400, borderRadius: '50%', background: 'radial-gradient(ellipse, rgba(201,146,42,0.04) 0%, transparent 60%)', pointerEvents: 'none' }} />
      <div>
        <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.2em', color: 'var(--text-muted)', marginBottom: 20 }}>INITIALIZE DEPLOYMENT</div>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 'clamp(48px,5vw,72px)', lineHeight: 0.95, color: 'var(--text)', letterSpacing: '0.02em' }}>
          READY TO<br />
          <span style={{ color: 'var(--gold)', display: 'block' }}>DEPLOY UTAU?</span>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, alignItems: 'flex-end' }}>
        <button onClick={onLaunch} style={{
          display: 'inline-flex', alignItems: 'center', gap: 12,
          padding: '15px 32px', background: 'var(--gold)',
          border: '1px solid var(--gold-bright)', whiteSpace: 'nowrap',
          fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, letterSpacing: '0.15em',
          color: '#0A0800', cursor: 'pointer',
        }}
          onMouseEnter={e => { e.currentTarget.style.background = GOLD_BRIGHT; }}
          onMouseLeave={e => { e.currentTarget.style.background = GOLD; }}
        >ACCESS DASHBOARD →</button>
        <button style={{
          display: 'inline-flex', alignItems: 'center', gap: 10,
          padding: '15px 32px', background: 'transparent',
          border: '1px solid var(--text-dim)', whiteSpace: 'nowrap',
          fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 500, letterSpacing: '0.15em',
          color: 'var(--text-muted)', cursor: 'pointer',
        }}>REQUEST ENTERPRISE DEMO</button>
        <div style={{ fontSize: 9, color: 'var(--text-dim)', letterSpacing: '0.12em', textAlign: 'right' }}>
          SOC 2 TYPE II · ISO 27001 · NERC CIP COMPLIANT
        </div>
      </div>
    </div>
  );
}

/* ── BOTTOM BAR ── */
function BottomBar() {
  return (
    <div style={{
      position: 'relative', zIndex: 10,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '20px 64px',
      borderTop: '1px solid var(--border-light)',
      background: 'var(--bg-panel)',
    }}>
      <div style={{ fontSize: 9, color: 'var(--text-dim)', letterSpacing: '0.1em' }}>© 2026 UTAU-IIOT SYSTEMS. ALL RIGHTS RESERVED.</div>
      <div style={{ display: 'flex', gap: 24 }}>
        {['PRIVACY', 'SECURITY', 'COMPLIANCE', 'STATUS'].map(l => (
          <a key={l} href="#" style={{ fontSize: 9, color: 'var(--text-dim)', textDecoration: 'none', letterSpacing: '0.1em' }}
            onMouseEnter={e => e.currentTarget.style.color = 'var(--text-muted)'}
            onMouseLeave={e => e.currentTarget.style.color = 'var(--text-dim)'}
          >{l}</a>
        ))}
      </div>
    </div>
  );
}

/* ── SECTION LABEL ── */
function SectionLabel({ num, text }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 64 }}>
      <span style={{ fontFamily: 'var(--font-display)', fontSize: 13, letterSpacing: '0.2em', color: 'var(--gold)' }}>{num}</span>
      <span style={{ flex: '0 0 40px', height: 1, background: 'var(--border)' }} />
      <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.2em', color: 'var(--text-muted)' }}>{text}</span>
    </div>
  );
}

/* ── SCROLL OBSERVER ── */
function useScrollReveal() {
  useEffect(() => {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('visible'); observer.unobserve(e.target); }
      });
    }, { threshold: 0.1 });
    document.querySelectorAll('.fade-in').forEach(el => observer.observe(el));
    setTimeout(() => {
      document.querySelectorAll('.fade-in').forEach(el => {
        if (el.getBoundingClientRect().top < window.innerHeight) el.classList.add('visible');
      });
    }, 100);
    return () => observer.disconnect();
  }, []);
}

/* ── ROOT ── */
export default function LandingPage({ onLaunch = () => { } }) {
  useScrollReveal();
  return (
    <>
      <FontLoader />
      <GlobalStyles />
      <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
        <Nav onLaunch={onLaunch} />
        <Ticker />
        <Hero onLaunch={onLaunch} />
        <StatsBar />
        <ArchSection />
        <MonitorSection />
        <FooterCTA onLaunch={onLaunch} />
        <BottomBar />
      </div>
    </>
  );
}