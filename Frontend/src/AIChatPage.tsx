import React, { useState, useRef, useEffect } from 'react';
import { Target, ChevronLeft, Terminal, User, Send, Sparkles } from 'lucide-react';
import { motion } from 'framer-motion';

type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
};

export default function AIChatPage({ onBack }: { onBack: () => void }) {
  const [messages, setMessages] = useState<Message[]>([
    { 
      id: '1', role: 'assistant', 
      content: 'UTAU-IIoT Copilot initialized.\nSystem architecture mapped. Telemetry pipeline active.\nHow can I assist you with spatio-temporal telemetry analysis today?',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    }
  ]);
  const [input, setInput] = useState('');
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!input.trim()) return;
    
    setMessages(prev => [...prev, { 
      id: Date.now().toString(), role: 'user', content: input,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    }]);
    setInput('');
    
    // Simulate AI response
    setTimeout(() => {
      setMessages(prev => [...prev, { 
        id: (Date.now() + 1).toString(), 
        role: 'assistant', 
        content: 'Analyzing historical telemetry...\nThe current anomaly signature strongly correlates with a predictive failure in the planetary gearbox (Confidence Score: 98.3%).\n\nI recommend initiating an autonomic canary rollback immediately before mechanical failure occurs.',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      }]);
    }, 1200);
  };

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
        
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 12px', border: '1px solid rgba(184, 134, 42, 0.28)', background: 'rgba(184, 134, 42, 0.14)' }}>
           <Target size={12} color="var(--gold)" />
           <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fontWeight: 600, letterSpacing: '0.2em', color: 'var(--gold)' }}>AGENT ONLINE</span>
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
                    lineHeight: 1.6, whiteSpace: 'pre-wrap'
                  }}>
                    {msg.content}
                  </div>
                </div>
              </motion.div>
            ))}
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
                disabled={!input.trim()}
                style={{ 
                  position: 'absolute', right: 16, display: 'flex', alignItems: 'center', justifyContent: 'center',
                  width: 48, height: 48, background: input.trim() ? 'var(--gold)' : 'transparent', 
                  border: input.trim() ? '1px solid var(--gold-bright)' : '1px solid var(--border)', 
                  cursor: input.trim() ? 'pointer' : 'not-allowed', transition: 'all 0.2s',
                }}
                onMouseEnter={e => input.trim() && (e.currentTarget.style.boxShadow = 'var(--gold-glow)')}
                onMouseLeave={e => e.currentTarget.style.boxShadow = 'none'}
              >
                <Send size={16} color={input.trim() ? '#0A0800' : 'var(--text-dim)'} />
              </button>
            </form>
          </div>

        </div>
      </main>
    </div>
  );
}
