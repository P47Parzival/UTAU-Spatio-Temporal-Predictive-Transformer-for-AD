import { useEffect, useState, type CSSProperties } from 'react';
import { RefreshCw, Cable, HeartPulse, FlaskConical, ShieldCheck } from 'lucide-react';

type SourceItem = {
  id: number;
  name: string;
  protocol: 'kafka' | 'mqtt' | 'opcua' | 'http';
  endpoint: string;
  topic: string | null;
  dataset: string | null;
  expected_dimensions: number | null;
  enabled: boolean;
  is_active: boolean;
  notes: string | null;
  mapping: Record<string, unknown>;
  auth: Record<string, unknown>;
  created_at_ms: number;
  updated_at_ms: number;
};

type SourceHealth = {
  source_id: number;
  source_name: string;
  status: 'healthy' | 'degraded' | 'offline' | 'idle' | 'waiting';
  reason: string;
  message_age_ms: number | null;
  ingest_total: number;
  ingest_drop_ratio: number;
  kafka_connected: boolean;
  dataset_active: boolean;
};

type ValidationResult = {
  valid: boolean;
  issues: string[];
  warnings: string[];
  resolved_mapping: {
    timestamp_path: string;
    vector_path: string;
    expected_dimensions: number | null;
    active_model_dimensions: number;
  };
  sample_check: {
    checked: boolean;
    timestamp_ok: boolean;
    vector_ok: boolean;
    vector_length: number | null;
  };
};

type SourceForm = {
  name: string;
  protocol: 'kafka' | 'mqtt' | 'opcua' | 'http';
  endpoint: string;
  topic: string;
  dataset: string;
  expectedDimensions: string;
  enabled: boolean;
  isActive: boolean;
  notes: string;
  timestampPath: string;
  vectorPath: string;
  authUsername: string;
  authToken: string;
};

const API_BASE = 'http://127.0.0.1:8000';

const palette = {
  text: 'var(--text-primary)',
  dim: 'var(--text-dim)',
  sub: 'var(--text-secondary)',
  border: 'var(--border)',
  bg: 'var(--bg-card)',
  recess: 'var(--bg-recessed)',
  gold: 'var(--gold)',
  copper: 'var(--copper)',
  crimson: 'var(--crimson)',
  teal: 'var(--teal)',
};

const defaultForm = (): SourceForm => ({
  name: '',
  protocol: 'mqtt',
  endpoint: '127.0.0.1:1883',
  topic: 'esp32/telemetry',
  dataset: 'ESP32',
  expectedDimensions: '64',
  enabled: true,
  isActive: false,
  notes: '',
  timestampPath: 'timestamp_ms',
  vectorPath: 'sensors',
  authUsername: '',
  authToken: '',
});

const toForm = (source: SourceItem): SourceForm => ({
  name: source.name ?? '',
  protocol: source.protocol ?? 'kafka',
  endpoint: source.endpoint ?? '',
  topic: source.topic ?? '',
  dataset: source.dataset ?? '',
  expectedDimensions: source.expected_dimensions == null ? '' : String(source.expected_dimensions),
  enabled: Boolean(source.enabled),
  isActive: Boolean(source.is_active),
  notes: source.notes ?? '',
  timestampPath: String((source.mapping?.timestamp_path as string) ?? 'timestamp_ms'),
  vectorPath: String((source.mapping?.vector_path as string) ?? 'sensors'),
  authUsername: String((source.auth?.username as string) ?? ''),
  authToken: '',
});

export default function DataSourceTab() {
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [form, setForm] = useState<SourceForm>(defaultForm);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [health, setHealth] = useState<SourceHealth | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [sampleJson, setSampleJson] = useState('');

  const loadSources = async () => {
    setIsLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/sources`);
      if (!res.ok) throw new Error(`Failed to load sources (${res.status})`);
      const payload = await res.json();
      const items = Array.isArray(payload.items) ? payload.items as SourceItem[] : [];
      setSources(items);

      const nextSelected = items.find((x) => x.id === selectedId)
        ?? (payload.active_source_id ? items.find((x) => x.id === payload.active_source_id) : null)
        ?? items[0]
        ?? null;

      if (nextSelected) {
        setSelectedId(nextSelected.id);
        setForm(toForm(nextSelected));
      } else {
        setSelectedId(null);
        setForm(defaultForm());
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load sources');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadSources();
  }, []);

  const selectSource = (source: SourceItem) => {
    setSelectedId(source.id);
    setForm(toForm(source));
    setMessage('');
    setError('');
    setValidation(null);
    setHealth(null);
  };

  const buildPayload = () => {
    const expected = form.expectedDimensions.trim();
    return {
      name: form.name.trim(),
      protocol: form.protocol,
      endpoint: form.endpoint.trim(),
      topic: form.topic.trim() || null,
      dataset: form.dataset.trim() || null,
      expected_dimensions: expected ? Number(expected) : null,
      enabled: form.enabled,
      is_active: form.isActive,
      notes: form.notes.trim() || null,
      mapping: {
        timestamp_path: form.timestampPath.trim() || 'timestamp_ms',
        vector_path: form.vectorPath.trim() || 'sensors',
      },
      auth: {
        username: form.authUsername.trim() || undefined,
        token: form.authToken.trim() || undefined,
      },
    };
  };

  const saveSource = async (mode: 'create' | 'update') => {
    setIsSaving(true);
    setMessage('');
    setError('');
    setValidation(null);

    try {
      const payload = buildPayload();
      const endpoint = mode === 'create' ? `${API_BASE}/sources` : `${API_BASE}/sources/${selectedId}`;
      const method = mode === 'create' ? 'POST' : 'PATCH';
      const res = await fetch(endpoint, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Save failed (${res.status})`);

      setMessage(mode === 'create' ? 'Source created.' : 'Source updated.');
      await loadSources();
      if (mode === 'create' && data?.item?.id) {
        setSelectedId(Number(data.item.id));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save source');
    } finally {
      setIsSaving(false);
    }
  };

  const checkHealth = async () => {
    if (!selectedId) return;
    setError('');
    setMessage('');
    try {
      const res = await fetch(`${API_BASE}/sources/${selectedId}/health`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Health check failed (${res.status})`);
      setHealth(data as SourceHealth);
      setMessage('Health check completed.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Health check failed');
    }
  };

  const validateMapping = async () => {
    if (!selectedId) return;
    setError('');
    setMessage('');
    try {
      let sample: Record<string, unknown> | undefined;
      if (sampleJson.trim()) {
        const parsed = JSON.parse(sampleJson);
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          throw new Error('Sample JSON must be an object.');
        }
        sample = parsed as Record<string, unknown>;
      }

      const res = await fetch(`${API_BASE}/sources/${selectedId}/mapping/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sample }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Validation failed (${res.status})`);
      setValidation(data as ValidationResult);
      setMessage('Mapping validation completed.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Mapping validation failed');
    }
  };

  const statusColor = (status: SourceHealth['status']) => {
    if (status === 'healthy') return palette.teal;
    if (status === 'degraded') return palette.copper;
    if (status === 'waiting' || status === 'idle') return palette.gold;
    return palette.crimson;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, minHeight: 0 }}>
      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
        <div style={{ padding: 16, border: `1px solid ${palette.border}`, background: palette.bg }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.dim, letterSpacing: '0.16em' }}>TOTAL SOURCES</div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 24, color: palette.text }}>{sources.length}</div>
        </div>
        <div style={{ padding: 16, border: `1px solid ${palette.border}`, background: palette.bg }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.dim, letterSpacing: '0.16em' }}>ENABLED</div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 24, color: palette.text }}>{sources.filter((s) => s.enabled).length}</div>
        </div>
        <div style={{ padding: 16, border: `1px solid ${palette.border}`, background: palette.bg }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.dim, letterSpacing: '0.16em' }}>ACTIVE SOURCE</div>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 18, color: palette.text }}>{sources.find((s) => s.is_active)?.name ?? 'none'}</div>
        </div>
      </section>

      <section style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 12, flex: 1, minHeight: 0 }}>
        <div style={{ border: `1px solid ${palette.border}`, background: palette.bg, overflow: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: 12, borderBottom: `1px solid ${palette.border}` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Cable size={14} color={palette.gold} />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.16em', color: palette.sub }}>DATA SOURCES</span>
            </div>
            <button
              onClick={() => void loadSources()}
              disabled={isLoading}
              style={{ border: `1px solid ${palette.border}`, background: 'transparent', color: palette.text, cursor: 'pointer', padding: '4px 8px' }}
            >
              <RefreshCw size={12} className={isLoading ? 'animate-spin' : ''} />
            </button>
          </div>

          {sources.length === 0 ? (
            <div style={{ padding: 16, fontFamily: 'var(--font-mono)', fontSize: 11, color: palette.dim }}>No sources configured.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {sources.map((s) => {
                const active = selectedId === s.id;
                return (
                  <button
                    key={s.id}
                    onClick={() => selectSource(s)}
                    style={{
                      padding: 12,
                      textAlign: 'left',
                      background: active ? 'var(--gold-dim)' : 'transparent',
                      border: 'none',
                      borderBottom: `1px solid ${palette.border}`,
                      cursor: 'pointer',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: palette.text }}>{s.name}</span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: palette.dim }}>{s.protocol.toUpperCase()}</span>
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: palette.dim }}>
                      {s.dataset ?? 'all datasets'} {s.is_active ? ' • active' : ''} {s.enabled ? '' : ' • disabled'}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div style={{ border: `1px solid ${palette.border}`, background: palette.bg, padding: 16, overflow: 'auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12 }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub }}>Name</span>
              <input value={form.name} onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} style={inputStyle} />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub }}>Protocol</span>
              <select value={form.protocol} onChange={(e) => setForm((p) => ({ ...p, protocol: e.target.value as SourceForm['protocol'] }))} style={inputStyle}>
                <option value="kafka">Kafka</option>
                <option value="mqtt">MQTT</option>
                <option value="opcua">OPC UA</option>
                <option value="http">HTTP</option>
              </select>
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub }}>Endpoint</span>
              <input value={form.endpoint} onChange={(e) => setForm((p) => ({ ...p, endpoint: e.target.value }))} style={inputStyle} />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub }}>Topic</span>
              <input value={form.topic} onChange={(e) => setForm((p) => ({ ...p, topic: e.target.value }))} style={inputStyle} />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub }}>Dataset</span>
              <select value={form.dataset} onChange={(e) => setForm((p) => ({ ...p, dataset: e.target.value }))} style={inputStyle}>
                <option value="">All</option>
                <option value="SMD">SMD</option>
                <option value="MSL">MSL</option>
                <option value="SMAP">SMAP</option>
                <option value="ESP32">ESP32</option>
                <option value="synthetic">Synthetic</option>
              </select>
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub }}>Expected Dimensions</span>
              <input value={form.expectedDimensions} onChange={(e) => setForm((p) => ({ ...p, expectedDimensions: e.target.value }))} style={inputStyle} placeholder="e.g. 38" />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub }}>Timestamp Path</span>
              <input value={form.timestampPath} onChange={(e) => setForm((p) => ({ ...p, timestampPath: e.target.value }))} style={inputStyle} placeholder="timestamp_ms" />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub }}>Vector Path</span>
              <input value={form.vectorPath} onChange={(e) => setForm((p) => ({ ...p, vectorPath: e.target.value }))} style={inputStyle} placeholder="sensors" />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub }}>Auth Username</span>
              <input value={form.authUsername} onChange={(e) => setForm((p) => ({ ...p, authUsername: e.target.value }))} style={inputStyle} />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub }}>Auth Token</span>
              <input value={form.authToken} onChange={(e) => setForm((p) => ({ ...p, authToken: e.target.value }))} style={inputStyle} type="password" />
            </label>
          </div>

          <label style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 12 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub }}>Notes</span>
            <textarea
              value={form.notes}
              onChange={(e) => setForm((p) => ({ ...p, notes: e.target.value }))}
              style={{ ...inputStyle, minHeight: 72, resize: 'vertical' }}
            />
          </label>

          <div style={{ display: 'flex', gap: 18, marginTop: 10 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub }}>
              <input type="checkbox" checked={form.enabled} onChange={(e) => setForm((p) => ({ ...p, enabled: e.target.checked }))} /> Enabled
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub }}>
              <input type="checkbox" checked={form.isActive} onChange={(e) => setForm((p) => ({ ...p, isActive: e.target.checked }))} /> Active Source
            </label>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 14 }}>
            <button onClick={() => void saveSource('create')} disabled={isSaving} style={buttonStyle}>
              {isSaving ? 'Saving...' : 'Create'}
            </button>
            <button onClick={() => void saveSource('update')} disabled={!selectedId || isSaving} style={buttonStyle}>
              Update
            </button>
            <button onClick={checkHealth} disabled={!selectedId} style={buttonStyleSecondary}>
              <HeartPulse size={12} /> Health
            </button>
            <button onClick={validateMapping} disabled={!selectedId} style={buttonStyleSecondary}>
              <FlaskConical size={12} /> Validate Mapping
            </button>
            <button
              onClick={() => {
                setSelectedId(null);
                setForm(defaultForm());
                setValidation(null);
                setHealth(null);
                setMessage('Ready for new source.');
                setError('');
              }}
              style={buttonStyleSecondary}
            >
              New Draft
            </button>
          </div>

          <label style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 14 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub }}>Sample JSON for Mapping Validation (optional)</span>
            <textarea
              value={sampleJson}
              onChange={(e) => setSampleJson(e.target.value)}
              style={{ ...inputStyle, minHeight: 92, resize: 'vertical', fontFamily: 'var(--font-mono)' }}
              placeholder='{"timestamp_ms": 1710000000000, "sensors": [0.1, 0.2]}'
            />
          </label>

          {error && <div style={{ marginTop: 12, color: palette.crimson, fontFamily: 'var(--font-mono)', fontSize: 11 }}>{error}</div>}
          {message && <div style={{ marginTop: 12, color: palette.teal, fontFamily: 'var(--font-mono)', fontSize: 11 }}>{message}</div>}

          {health && (
            <div style={{ marginTop: 14, border: `1px solid ${palette.border}`, background: palette.recess, padding: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <ShieldCheck size={13} color={statusColor(health.status)} />
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.14em', color: statusColor(health.status) }}>
                  HEALTH: {health.status.toUpperCase()} ({health.reason})
                </span>
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub, lineHeight: 1.8 }}>
                kafka_connected: {String(health.kafka_connected)} | dataset_active: {String(health.dataset_active)} | message_age_ms: {health.message_age_ms ?? 'n/a'}
                <br />
                ingest_total: {health.ingest_total} | ingest_drop_ratio: {(health.ingest_drop_ratio * 100).toFixed(1)}%
              </div>
            </div>
          )}

          {validation && (
            <div style={{ marginTop: 14, border: `1px solid ${palette.border}`, background: palette.recess, padding: 12 }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: validation.valid ? palette.teal : palette.copper, marginBottom: 8, letterSpacing: '0.14em' }}>
                MAPPING VALIDATION: {validation.valid ? 'VALID' : 'ISSUES FOUND'}
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.sub, lineHeight: 1.8 }}>
                timestamp_path: {validation.resolved_mapping.timestamp_path} | vector_path: {validation.resolved_mapping.vector_path}
                <br />
                expected_dimensions: {validation.resolved_mapping.expected_dimensions ?? 'unset'} | active_model_dimensions: {validation.resolved_mapping.active_model_dimensions}
              </div>
              {validation.issues.length > 0 && (
                <div style={{ marginTop: 8, fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.crimson }}>
                  Issues: {validation.issues.join(' | ')}
                </div>
              )}
              {validation.warnings.length > 0 && (
                <div style={{ marginTop: 8, fontFamily: 'var(--font-mono)', fontSize: 10, color: palette.copper }}>
                  Warnings: {validation.warnings.join(' | ')}
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

const inputStyle: CSSProperties = {
  border: '1px solid var(--border)',
  background: 'var(--bg)',
  color: 'var(--text-primary)',
  padding: '8px 10px',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
};

const buttonStyle: CSSProperties = {
  border: '1px solid var(--gold)',
  background: 'var(--gold-dim)',
  color: 'var(--text-primary)',
  padding: '7px 10px',
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  letterSpacing: '0.1em',
  cursor: 'pointer',
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
};

const buttonStyleSecondary: CSSProperties = {
  border: '1px solid var(--border)',
  background: 'transparent',
  color: 'var(--text-primary)',
  padding: '7px 10px',
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  letterSpacing: '0.1em',
  cursor: 'pointer',
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
};
