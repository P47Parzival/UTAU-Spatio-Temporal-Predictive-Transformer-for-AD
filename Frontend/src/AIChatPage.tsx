import React, { useState, useRef, useEffect } from 'react';
import { Target, ChevronLeft, Terminal, User, Send, Sparkles } from 'lucide-react';
import { motion } from 'framer-motion';
import ReactMarkdown from 'react-markdown';

type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
};

interface AIChatPageProps {
  onBack: () => void;
  systemState?: string;
  activeDataset?: string;
  alertExplanation?: any;
  currentMetrics?: any;
}

export default function AIChatPage({ onBack, systemState, activeDataset, alertExplanation, currentMetrics }: AIChatPageProps) {
  const [messages, setMessages] = useState<Message[]>([
    { 
      id: '1', role: 'assistant', 
      content: 'UTAU-IIoT Copilot initialized.\nSystem architecture mapped. Telemetry pipeline active.\nHow can I assist you with spatio-temporal telemetry analysis today?',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    }
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [feedbackHistory, setFeedbackHistory] = useState<any[]>([]);
  const [dbStatus, setDbStatus] = useState<'connecting' | 'live' | 'offline'>('connecting');
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  useEffect(() => {
    const loadFeedback = () => {
      fetch('http://127.0.0.1:8000/api/feedback_history?limit=10')
        .then(res => { if (!res.ok) throw new Error('non-200'); return res.json(); })
        .then(data => {
          setFeedbackHistory(Array.isArray(data) ? data : []);
          setDbStatus('live');
        })
        .catch(() => setDbStatus('offline'));
    };
    loadFeedback();
    const t = setInterval(loadFeedback, 15000);
    return () => clearInterval(t);
  }, []);

  const buildSystemPrompt = () => {
    const anomalyBlock = alertExplanation
      ? [
          `- **Anomaly Type**: ${alertExplanation.anomaly_type}`,
          `- **Detection Confidence**: **${(Number(alertExplanation.confidence) * 100).toFixed(2)}%**`,
          `- **Severity**: **${(alertExplanation.severity_level || '').toUpperCase()}**`,
          `- **Primary Failing Sensor**: **${alertExplanation.top_contributors?.[0]?.sensor}** (${Number(alertExplanation.top_contributors?.[0]?.contribution_pct || 0).toFixed(1)}% contribution)`,
          alertExplanation.top_contributors?.length > 1
            ? `- **All Contributors**: ${alertExplanation.top_contributors.map((c: any) => `${c.sensor} (${Number(c.contribution_pct).toFixed(1)}%)`).join(', ')}`
            : '',
          alertExplanation.investigation_hints?.length
            ? `- **Investigation Hints**: ${alertExplanation.investigation_hints.join('; ')}`
            : '',
        ].filter(Boolean).join('\n')
      : '- No active anomaly. All sensor streams are within operational thresholds.';

    const metricsLine = currentMetrics
      ? `- **System Loss**: ${Number(currentMetrics.system_loss).toFixed(4)} | **Threshold**: ${Number(currentMetrics.threshold).toFixed(4)}`
      : '';

    const dbBlock = feedbackHistory.length > 0
      ? feedbackHistory.map((f: any, i: number) =>
          `- **[#${i + 1}]** ${f.dataset} | Tick ${f.tick} | ${f.was_anomaly ? '🔴 CONFIRMED' : '⚪ DISMISSED'} | **${f.anomaly_type}** | Severity: ${f.severity_level} | Confidence: **${(Number(f.confidence) * 100).toFixed(1)}%** | Calibration: ${f.calibrate_requested ? 'YES' : 'NO'} | Note: _"${f.note || 'none'}"_`
        ).join('\n')
      : '- No records available. Backend may be offline.';

    return `You are UTAU-CORE, an elite industrial AI embedded inside a hardened IIoT command center.
You have DIRECT READ ACCESS to live telemetry, real-time anomaly scores, and the operator feedback database.

## LIVE TELEMETRY CONTEXT
- **Dataset**: ${activeDataset || 'UNKNOWN'}
- **System State**: **${systemState || 'UNKNOWN'}**
${anomalyBlock}
${metricsLine}

## OPERATOR FEEDBACK DATABASE (${feedbackHistory.length} record${feedbackHistory.length !== 1 ? 's' : ''})
${dbBlock}

## YOUR RESPONSE RULES
1. **Be direct and terse** — this is a military-grade terminal. Never say "I would be happy to", "please let me know", or "if you would like". Just execute the analysis.
2. **Lead with the most critical finding** — never bury the important info.
3. **Always cite DB record numbers** (#1, #2) when referencing past incidents.
4. **Format every response using Markdown** — use ## headers, **bold** for numbers/sensors/severities, bullet lists for multi-point analysis. Do not output raw asterisks or markdown symbols literally.
5. **Never invent or speculate** beyond what is present in the telemetry context and DB above.
6. **If asked a question with data available**, answer it fully and concisely without asking for further permission.`;
  };

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMsg = input.trim();
    setInput('');
    setMessages(prev => [...prev, {
      id: Date.now().toString(), role: 'user', content: userMsg,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    }]);

    setIsLoading(true);

    try {
      const apiKey = import.meta.env.VITE_GROQ_API_KEY;
      const systemMessage = { role: 'system', content: buildSystemPrompt() };
      const apiHistory = messages.map(m => ({ role: m.role, content: m.content }));

      const res = await fetch('https://api.groq.com/openai/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${apiKey}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          model: 'llama-3.3-70b-versatile',
          messages: [systemMessage, ...apiHistory, { role: 'user', content: userMsg }],
          temperature: 0.15,
        })
      });

      if (!res.ok) {
        throw new Error(`Groq API Failed: ${res.statusText}. Verify VITE_GROQ_API_KEY in .env.`);
      }

      const raw = await res.json();
      const botResponse = raw.choices?.[0]?.message?.content || 'No completion returned by AI core.';

      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: botResponse,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      }]);

    } catch (err: any) {
      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `**[SYSTEM FAILURE]** ${err.message}\n\nVerify your \`.env\` contains a valid \`VITE_GROQ_API_KEY\`.`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const dbBorderColor = dbStatus === 'live' ? 'rgba(39,174,96,0.4)' : dbStatus === 'offline' ? 'rgba(192,57,43,0.4)' : 'rgba(160,157,148,0.3)';
  const dbBgColor = dbStatus === 'live' ? 'rgba(39,174,96,0.08)' : dbStatus === 'offline' ? 'rgba(192,57,43,0.08)' : 'transparent';
  const dbDotColor = dbStatus === 'live' ? '#27AE60' : dbStatus === 'offline' ? '#C0392B' : '#A09D94';
  const dbLabel = dbStatus === 'live' ? `DB LIVE (${feedbackHistory.length})` : dbStatus === 'offline' ? 'DB OFFLINE' : 'CONNECTING...';

  return (
    <div style={{ height: '100vh', width: '100vw', display: 'flex', flexDirection: 'column', background: 'var(--bg)', overflow: 'hidden' }}>

      {/* ── Nav Header ── */}
      <nav style={{
        flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 48px', height: 64,
        background: 'rgba(8,8,7,0.92)',
        borderBottom: '1px solid var(--border)',
        backdropFilter: 'blur(12px)',
        position: 'relative', zIndex: 100
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 32 }}>
          <button onClick={onBack} style={{
            display: 'flex', alignItems: 'center', gap: 8, padding: '9px 16px',
            border: '1px solid rgba(201,146,42,0.12)', background: 'transparent',
            fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fontWeight: 600, letterSpacing: '0.15em',
            color: '#A09D94', cursor: 'pointer', transition: 'all 0.2s'
          }}
            onMouseEnter={e => { e.currentTarget.style.color = '#F0EBE0'; e.currentTarget.style.borderColor = '#A09D94'; }}
            onMouseLeave={e => { e.currentTarget.style.color = '#A09D94'; e.currentTarget.style.borderColor = 'rgba(201,146,42,0.12)'; }}
          >
            <ChevronLeft size={14} /> COMMAND CENTER
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ width: 24, height: 24, border: '1.5px solid var(--gold)', transform: 'rotate(45deg)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <div className="logo-icon-inner" style={{ width: 8, height: 8, background: 'var(--gold)' }} />
            </div>
            <span style={{ fontFamily: "'Bebas Neue', sans-serif", fontSize: 22, letterSpacing: '0.2em', color: '#F0EBE0', transform: 'translateY(2px)' }}>
              UTAU <span style={{ color: 'var(--gold)' }}>COPILOT</span>
            </span>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 12px', border: '1px solid rgba(184, 134, 42, 0.28)', background: 'rgba(184, 134, 42, 0.14)' }}>
            <Target size={12} color="var(--gold)" />
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fontWeight: 600, letterSpacing: '0.2em', color: 'var(--gold)' }}>AGENT ONLINE</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 12px', border: `1px solid ${dbBorderColor}`, background: dbBgColor }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', display: 'inline-block', background: dbDotColor, boxShadow: dbStatus === 'live' ? `0 0 6px ${dbDotColor}` : 'none' }} />
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fontWeight: 600, letterSpacing: '0.15em', color: dbDotColor }}>
              {dbLabel}
            </span>
          </div>
        </div>
      </nav>

      {/* ── Main Chat Interface ── */}
      <main style={{ flex: 1, display: 'flex', justifyContent: 'center', overflow: 'hidden', position: 'relative' }}>

        {/* ambient grid background */}
        <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(rgba(201,146,42,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(201,146,42,0.03) 1px, transparent 1px)', backgroundSize: '60px 60px', opacity: 0.5, pointerEvents: 'none' }} />

        <div style={{
          width: '100%', maxWidth: 1000, margin: '48px 0',
          display: 'flex', flexDirection: 'column',
          background: 'var(--bg-panel)', border: '1px solid var(--border)',
          boxShadow: '0 20px 40px rgba(0,0,0,0.4)', position: 'relative', zIndex: 10
        }}>

          {/* Chat History */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '48px', display: 'flex', flexDirection: 'column', gap: 32 }}>
            {messages.map((msg) => (
              <motion.div
                initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                key={msg.id}
                style={{
                  alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  maxWidth: '85%', display: 'flex', gap: 16,
                  flexDirection: msg.role === 'user' ? 'row-reverse' : 'row'
                }}
              >
                {/* Avatar Icon */}
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                  width: 40, height: 40, background: 'var(--bg)', border: `1px solid ${msg.role === 'assistant' ? 'var(--gold)' : 'var(--text-dim)'}`
                }}>
                  {msg.role === 'assistant' ? <Terminal size={18} color="var(--gold)" /> : <User size={18} color="var(--text-muted)" />}
                </div>

                {/* Bubble */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    flexDirection: msg.role === 'user' ? 'row-reverse' : 'row'
                  }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600, letterSpacing: '0.15em', color: msg.role === 'assistant' ? 'var(--gold)' : 'var(--text-muted)' }}>
                      {msg.role === 'assistant' ? 'UTAU SYSTEM' : 'OPERATOR'}
                    </span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)' }}>{msg.timestamp}</span>
                  </div>

                  <div style={{
                    padding: '20px 24px',
                    background: msg.role === 'user' ? 'var(--bg-recessed)' : 'var(--gold-dim)',
                    border: '1px solid', borderColor: msg.role === 'user' ? 'var(--border)' : 'var(--gold-border)',
                    fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text)',
                    lineHeight: 1.7, overflowWrap: 'break-word',
                  }}>
                    {msg.role === 'user' ? (
                      <span style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</span>
                    ) : (
                      <ReactMarkdown
                        components={{
                          strong: ({ node, ...props }) => <strong style={{ color: 'var(--gold)', fontWeight: 700 }} {...props} />,
                          ul: ({ node, ...props }) => <ul style={{ listStyleType: 'square', paddingLeft: 20, margin: '10px 0' }} {...props} />,
                          ol: ({ node, ...props }) => <ol style={{ paddingLeft: 20, margin: '10px 0' }} {...props} />,
                          li: ({ node, ...props }) => <li style={{ marginBottom: 5, color: 'var(--text)' }} {...props} />,
                          p: ({ node, ...props }) => <p style={{ margin: '0 0 10px 0', lineHeight: 1.7 }} {...props} />,
                          code: ({ node, ...props }) => <code style={{ background: 'rgba(201,146,42,0.12)', padding: '1px 5px', borderRadius: 2, color: '#E8B84B', fontSize: 12 }} {...props} />,
                          h1: ({ node, ...props }) => <h1 style={{ fontSize: 15, color: 'var(--gold)', margin: '16px 0 8px', borderBottom: '1px solid var(--border)', paddingBottom: 6, letterSpacing: '0.1em' }} {...props} />,
                          h2: ({ node, ...props }) => <h2 style={{ fontSize: 13, color: '#F0EBE0', margin: '14px 0 6px', letterSpacing: '0.08em' }} {...props} />,
                          h3: ({ node, ...props }) => <h3 style={{ fontSize: 12, color: 'var(--text-muted)', margin: '10px 0 4px', letterSpacing: '0.06em' }} {...props} />,
                          blockquote: ({ node, ...props }) => <blockquote style={{ borderLeft: '2px solid var(--gold)', paddingLeft: 12, margin: '8px 0', color: 'var(--text-muted)', fontStyle: 'italic' }} {...props} />,
                          hr: ({ node, ...props }) => <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '12px 0' }} {...props} />,
                        }}
                      >
                        {msg.content}
                      </ReactMarkdown>
                    )}
                  </div>
                </div>
              </motion.div>
            ))}

            {isLoading && (
              <motion.div
                initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                style={{ alignSelf: 'flex-start', maxWidth: '85%', display: 'flex', gap: 16 }}
              >
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                  width: 40, height: 40, background: 'var(--bg)', border: '1px solid var(--gold)'
                }}>
                  <Terminal size={18} color="var(--gold)" />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600, letterSpacing: '0.15em', color: 'var(--gold)' }}>UTAU SYSTEM</span>
                  <div style={{
                    padding: '20px 24px', background: 'var(--gold-dim)', border: '1px solid var(--gold-border)',
                    fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text)',
                    display: 'flex', alignItems: 'center', gap: 10
                  }}>
                    <span className="live-dot" style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: 'var(--gold)', flexShrink: 0 }} />
                    <span style={{ letterSpacing: '0.2em', color: 'var(--text-dim)', fontSize: 10 }}>PROCESSING TELEMETRY...</span>
                  </div>
                </div>
              </motion.div>
            )}
            <div ref={endRef} />
          </div>

          {/* Input Area */}
          <div style={{ padding: '24px 48px 48px 48px', borderTop: '1px solid var(--border)' }}>
            <form onSubmit={handleSend} style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
              <div style={{ position: 'absolute', left: 24 }}>
                <Sparkles size={16} color="var(--gold)" />
              </div>
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="PROMPT > QUERY TELEMETRY HISTORY OR REQUEST DIAGNOSTICS..."
                style={{
                  width: '100%', padding: '20px 80px 20px 56px',
                  background: 'var(--bg)', border: '1px solid var(--border)',
                  fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.1em', color: 'var(--text)',
                  outline: 'none', transition: 'all 0.3s'
                }}
                onFocus={e => { e.currentTarget.style.borderColor = 'var(--gold)'; e.currentTarget.style.boxShadow = '0 0 20px rgba(201,146,42,0.1)'; }}
                onBlur={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.boxShadow = 'none'; }}
              />
              <button
                type="submit"
                disabled={!input.trim() || isLoading}
                style={{
                  position: 'absolute', right: 16, display: 'flex', alignItems: 'center', justifyContent: 'center',
                  width: 48, height: 48, background: input.trim() && !isLoading ? 'var(--gold)' : 'transparent',
                  border: input.trim() && !isLoading ? '1px solid var(--gold-bright)' : '1px solid var(--border)',
                  cursor: input.trim() && !isLoading ? 'pointer' : 'not-allowed', transition: 'all 0.2s',
                }}
                onMouseEnter={e => input.trim() && !isLoading && (e.currentTarget.style.boxShadow = 'var(--gold-glow)')}
                onMouseLeave={e => e.currentTarget.style.boxShadow = 'none'}
              >
                <Send size={16} color={input.trim() && !isLoading ? '#0A0800' : 'var(--text-dim)'} />
              </button>
            </form>
          </div>

        </div>
      </main>
    </div>
  );
}
