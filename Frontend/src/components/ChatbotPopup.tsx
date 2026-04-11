import React, { useState, useRef, useEffect } from 'react';
import { Terminal, User, Send, Sparkles, X, Bot, Minimize2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';

type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
};

interface ChatbotPopupProps {
  systemState?: string;
  activeDataset?: string;
  alertExplanation?: any;
  currentMetrics?: any;
}

export default function ChatbotPopup({
  systemState,
  activeDataset,
  alertExplanation,
  currentMetrics,
}: ChatbotPopupProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      role: 'assistant',
      content: 'UTAU Copilot ready.\nAsk me anything about the live telemetry, anomaly status, or sensor contributors.',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [feedbackHistory, setFeedbackHistory] = useState<any[]>([]);
  const [pulse, setPulse] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to newest message
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Focus input when popup opens
  useEffect(() => {
    if (isOpen && !isMinimized) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen, isMinimized]);

  // Pulse the button whenever an anomaly fires while popup is closed
  useEffect(() => {
    if (!isOpen && alertExplanation?.severity_level === 'critical') {
      setPulse(true);
      const t = setTimeout(() => setPulse(false), 4000);
      return () => clearTimeout(t);
    }
  }, [alertExplanation, isOpen]);

  // Load feedback history for richer context
  useEffect(() => {
    fetch('http://127.0.0.1:8000/api/feedback_history?limit=10')
      .then(r => r.ok ? r.json() : [])
      .then(d => setFeedbackHistory(Array.isArray(d) ? d : []))
      .catch(() => {});
  }, [isOpen]);

  const buildSystemPrompt = () => {
    const anomalyBlock = alertExplanation
      ? [
          `- Anomaly Type: ${alertExplanation.anomaly_type}`,
          `- Detection Confidence: ${(Number(alertExplanation.confidence) * 100).toFixed(1)}%`,
          `- Severity: ${(alertExplanation.severity_level || '').toUpperCase()}`,
          `- Primary Sensor: ${alertExplanation.top_contributors?.[0]?.sensor} (${Number(alertExplanation.top_contributors?.[0]?.contribution_pct || 0).toFixed(1)}%)`,
          alertExplanation.investigation_hints?.length
            ? `- Hints: ${alertExplanation.investigation_hints.join('; ')}`
            : '',
        ].filter(Boolean).join('\n')
      : '- No active anomaly. All sensors nominal.';

    const metricsLine = currentMetrics
      ? `- System Loss: ${Number(currentMetrics.system_loss).toFixed(4)} | Threshold: ${Number(currentMetrics.threshold).toFixed(4)}`
      : '';

    const dbBlock = feedbackHistory.length > 0
      ? feedbackHistory.map((f: any, i: number) =>
          `- [#${i + 1}] ${f.dataset} | Tick ${f.tick} | ${f.was_anomaly ? 'CONFIRMED' : 'DISMISSED'} | ${f.anomaly_type} | Severity: ${f.severity_level}`
        ).join('\n')
      : '- No feedback records.';

    return `You are UTAU-CORE, an elite IIoT anomaly detection AI embedded in a real-time command center.
You have access to live telemetry and an operator feedback database.

## LIVE TELEMETRY
- Dataset: ${activeDataset || 'UNKNOWN'}
- System State: ${systemState || 'UNKNOWN'}
${anomalyBlock}
${metricsLine}

## OPERATOR FEEDBACK (${feedbackHistory.length} records)
${dbBlock}

## RULES
1. Be direct, concise, actionable. No filler phrases.
2. Lead with the most critical finding.
3. Use Markdown formatting (bold, bullet lists, headers).
4. Never speculate beyond available data.
5. Reference DB records by number (#1, #2) when relevant.`;
  };

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMsg = input.trim();
    setInput('');
    setMessages(prev => [...prev, {
      id: Date.now().toString(),
      role: 'user',
      content: userMsg,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
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
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model: 'llama-3.3-70b-versatile',
          messages: [systemMessage, ...apiHistory, { role: 'user', content: userMsg }],
          temperature: 0.15,
        }),
      });

      if (!res.ok) throw new Error(`Groq API error: ${res.statusText}`);
      const raw = await res.json();
      const botResponse = raw.choices?.[0]?.message?.content || 'No response from AI core.';

      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: botResponse,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }]);
    } catch (err: any) {
      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `**[ERROR]** ${err.message}`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const severityColor =
    alertExplanation?.severity_level === 'critical' ? '#ef4444'
    : alertExplanation?.severity_level === 'warning' ? '#f59e0b'
    : 'var(--gold, #C9921A)';

  return (
    <>
      {/* ── Floating Round Button ── */}
      <button
        id="chatbot-popup-trigger"
        onClick={() => { setIsOpen(o => !o); setIsMinimized(false); }}
        title="Open UTAU Copilot"
        style={{
          position: 'fixed',
          bottom: 28,
          right: 28,
          zIndex: 10000,
          width: 56,
          height: 56,
          borderRadius: '50%',
          border: `2px solid ${severityColor}`,
          background: 'rgba(10,8,5,0.95)',
          backdropFilter: 'blur(12px)',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: `0 0 ${pulse ? '24px' : '12px'} ${severityColor}55, 0 4px 20px rgba(0,0,0,0.6)`,
          transition: 'box-shadow 0.4s ease, transform 0.2s ease',
          transform: isOpen ? 'scale(0.92)' : 'scale(1)',
          animation: pulse ? 'chatbot-pulse 1s ease-in-out infinite' : 'none',
        }}
        onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1.1)'; }}
        onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.transform = isOpen ? 'scale(0.92)' : 'scale(1)'; }}
      >
        <Bot size={24} color={severityColor} />
        {/* Unread badge when anomaly is active and popup is closed */}
        {!isOpen && alertExplanation?.severity_level === 'critical' && (
          <span style={{
            position: 'absolute', top: -3, right: -3,
            width: 14, height: 14, borderRadius: '50%',
            background: '#ef4444', border: '2px solid #0a0805',
            animation: 'chatbot-pulse 1s ease-in-out infinite',
          }} />
        )}
      </button>

      {/* ── Popup Window ── */}
      {isOpen && (
        <div
          id="chatbot-popup-window"
          style={{
            position: 'fixed',
            bottom: 96,
            right: 28,
            zIndex: 9999,
            width: 400,
            height: isMinimized ? 52 : 540,
            display: 'flex',
            flexDirection: 'column',
            background: 'rgba(10,8,5,0.97)',
            border: `1px solid ${severityColor}44`,
            borderRadius: 12,
            boxShadow: `0 24px 48px rgba(0,0,0,0.7), 0 0 32px ${severityColor}22`,
            backdropFilter: 'blur(20px)',
            overflow: 'hidden',
            transition: 'height 0.3s cubic-bezier(0.4,0,0.2,1)',
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          }}
        >
          {/* ── Header Bar ── */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 14px',
            borderBottom: isMinimized ? 'none' : `1px solid rgba(201,146,42,0.15)`,
            background: 'rgba(201,146,42,0.06)',
            flexShrink: 0,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{
                width: 8, height: 8, borderRadius: '50%',
                background: severityColor,
                boxShadow: `0 0 6px ${severityColor}`,
                animation: 'chatbot-pulse 2s ease-in-out infinite',
              }} />
              <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.18em', color: severityColor }}>
                UTAU COPILOT
              </span>
              <span style={{ fontSize: 9, color: 'rgba(160,157,148,0.6)', letterSpacing: '0.12em' }}>
                {activeDataset || 'UNKNOWN'}
              </span>
            </div>
            <div style={{ display: 'flex', gap: 4 }}>
              <button
                onClick={() => setIsMinimized(m => !m)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: '#A09D94', display: 'flex' }}
                title={isMinimized ? 'Expand' : 'Minimize'}
              >
                <Minimize2 size={13} />
              </button>
              <button
                onClick={() => setIsOpen(false)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: '#A09D94', display: 'flex' }}
                title="Close"
              >
                <X size={13} />
              </button>
            </div>
          </div>

          {/* ── Messages ── */}
          {!isMinimized && (
            <>
              <div style={{
                flex: 1,
                overflowY: 'auto',
                padding: '12px 14px',
                display: 'flex',
                flexDirection: 'column',
                gap: 12,
                scrollbarWidth: 'thin',
                scrollbarColor: 'rgba(201,146,42,0.2) transparent',
              }}>
                {messages.map(msg => (
                  <div
                    key={msg.id}
                    style={{
                      display: 'flex',
                      gap: 8,
                      alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                      maxWidth: '88%',
                      flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
                    }}
                  >
                    {/* Avatar */}
                    <div style={{
                      flexShrink: 0,
                      width: 28, height: 28,
                      borderRadius: '50%',
                      background: 'rgba(10,8,5,0.9)',
                      border: `1px solid ${msg.role === 'assistant' ? 'rgba(201,146,42,0.5)' : 'rgba(160,157,148,0.3)'}`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      {msg.role === 'assistant'
                        ? <Terminal size={13} color="var(--gold, #C9921A)" />
                        : <User size={13} color="#A09D94" />}
                    </div>

                    {/* Bubble */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                      <span style={{
                        fontSize: 8, letterSpacing: '0.15em', fontWeight: 700,
                        color: msg.role === 'assistant' ? 'rgba(201,146,42,0.7)' : 'rgba(160,157,148,0.6)',
                        textAlign: msg.role === 'user' ? 'right' : 'left',
                      }}>
                        {msg.role === 'assistant' ? 'UTAU' : 'YOU'} · {msg.timestamp}
                      </span>
                      <div style={{
                        padding: '9px 12px',
                        background: msg.role === 'user'
                          ? 'rgba(30,25,15,0.8)'
                          : 'rgba(201,146,42,0.07)',
                        border: `1px solid ${msg.role === 'user' ? 'rgba(160,157,148,0.15)' : 'rgba(201,146,42,0.2)'}`,
                        borderRadius: msg.role === 'user' ? '10px 3px 10px 10px' : '3px 10px 10px 10px',
                        fontSize: 11.5,
                        color: '#E8E4DC',
                        lineHeight: 1.65,
                        overflowWrap: 'break-word',
                      }}>
                        {msg.role === 'user' ? (
                          <span style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</span>
                        ) : (
                          <ReactMarkdown
                            components={{
                              strong: ({ ...props }) => <strong style={{ color: 'var(--gold, #C9921A)', fontWeight: 700 }} {...props} />,
                              p: ({ ...props }) => <p style={{ margin: '0 0 6px 0' }} {...props} />,
                              ul: ({ ...props }) => <ul style={{ listStyleType: 'square', paddingLeft: 16, margin: '4px 0' }} {...props} />,
                              li: ({ ...props }) => <li style={{ marginBottom: 3 }} {...props} />,
                              code: ({ ...props }) => <code style={{ background: 'rgba(201,146,42,0.12)', padding: '1px 4px', borderRadius: 2, fontSize: 10.5, color: '#E8B84B' }} {...props} />,
                              h2: ({ ...props }) => <h2 style={{ fontSize: 12, color: '#F0EBE0', margin: '8px 0 4px', letterSpacing: '0.06em' }} {...props} />,
                              h3: ({ ...props }) => <h3 style={{ fontSize: 11, color: '#A09D94', margin: '6px 0 3px' }} {...props} />,
                            }}
                          >
                            {msg.content}
                          </ReactMarkdown>
                        )}
                      </div>
                    </div>
                  </div>
                ))}

                {/* Loading indicator */}
                {isLoading && (
                  <div style={{ display: 'flex', gap: 8, alignSelf: 'flex-start', maxWidth: '88%' }}>
                    <div style={{
                      flexShrink: 0, width: 28, height: 28, borderRadius: '50%',
                      background: 'rgba(10,8,5,0.9)', border: '1px solid rgba(201,146,42,0.5)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <Terminal size={13} color="var(--gold, #C9921A)" />
                    </div>
                    <div style={{
                      padding: '9px 14px',
                      background: 'rgba(201,146,42,0.07)',
                      border: '1px solid rgba(201,146,42,0.2)',
                      borderRadius: '3px 10px 10px 10px',
                      display: 'flex', alignItems: 'center', gap: 8,
                    }}>
                      <span style={{
                        display: 'inline-block', width: 6, height: 6, borderRadius: '50%',
                        background: 'var(--gold, #C9921A)',
                        animation: 'chatbot-pulse 0.8s ease-in-out infinite',
                      }} />
                      <span style={{ fontSize: 10, color: '#A09D94', letterSpacing: '0.18em' }}>PROCESSING…</span>
                    </div>
                  </div>
                )}
                <div ref={endRef} />
              </div>

              {/* ── Input Bar ── */}
              <div style={{
                borderTop: '1px solid rgba(201,146,42,0.12)',
                padding: '10px 12px',
                background: 'rgba(10,8,5,0.6)',
                flexShrink: 0,
              }}>
                <form onSubmit={handleSend} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Sparkles size={13} color="rgba(201,146,42,0.5)" style={{ flexShrink: 0 }} />
                  <input
                    ref={inputRef}
                    type="text"
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    placeholder="Query telemetry..."
                    style={{
                      flex: 1,
                      background: 'rgba(20,16,8,0.85)',
                      border: '1px solid rgba(201,146,42,0.18)',
                      borderRadius: 6,
                      padding: '7px 10px',
                      fontSize: 11,
                      fontFamily: 'inherit',
                      color: '#E8E4DC',
                      outline: 'none',
                      letterSpacing: '0.04em',
                      transition: 'border-color 0.2s, box-shadow 0.2s',
                    }}
                    onFocus={e => {
                      e.currentTarget.style.borderColor = 'rgba(201,146,42,0.5)';
                      e.currentTarget.style.boxShadow = '0 0 10px rgba(201,146,42,0.08)';
                    }}
                    onBlur={e => {
                      e.currentTarget.style.borderColor = 'rgba(201,146,42,0.18)';
                      e.currentTarget.style.boxShadow = 'none';
                    }}
                  />
                  <button
                    type="submit"
                    disabled={!input.trim() || isLoading}
                    style={{
                      flexShrink: 0,
                      width: 32, height: 32,
                      borderRadius: 6,
                      border: '1px solid',
                      borderColor: input.trim() && !isLoading ? 'rgba(201,146,42,0.6)' : 'rgba(201,146,42,0.15)',
                      background: input.trim() && !isLoading ? 'rgba(201,146,42,0.18)' : 'transparent',
                      cursor: input.trim() && !isLoading ? 'pointer' : 'not-allowed',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      transition: 'all 0.2s',
                    }}
                  >
                    <Send size={13} color={input.trim() && !isLoading ? '#C9921A' : '#4a4740'} />
                  </button>
                </form>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Keyframe Animations (injected once) ── */}
      <style>{`
        @keyframes chatbot-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.6; transform: scale(1.15); }
        }
      `}</style>
    </>
  );
}
