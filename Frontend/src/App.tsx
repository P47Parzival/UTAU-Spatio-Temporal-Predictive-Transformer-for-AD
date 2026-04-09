import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from 'recharts';
import { AlertTriangle, CheckCircle, Activity, Server, Database, ShieldAlert } from 'lucide-react';

interface DataPoint {
  tick: number;
  system_loss: number;
  is_anomalous: boolean;
  threshold: number;
  [key: string]: number | boolean;
}

export default function App() {
  const [data, setData] = useState<DataPoint[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [systemState, setSystemState] = useState<'HEALTHY' | 'WARNING' | 'CRITICAL'>('HEALTHY');
  const [dimensions, setDimensions] = useState<number>(0);
  
  useEffect(() => {
    // Connect to FastAPI Backend
    const ws = new WebSocket('ws://localhost:8000/ws/stream');
    
    ws.onopen = () => setIsConnected(true);
    ws.onclose = () => setIsConnected(false);
    
    ws.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      
      if (payload.dimensions && payload.dimensions !== dimensions) {
          setDimensions(payload.dimensions);
      }
      
      const newPoint: DataPoint = {
        tick: payload.tick,
        system_loss: payload.system_loss,
        is_anomalous: payload.is_anomalous,
        threshold: payload.threshold,
        ...payload.sensors,
        ...payload.forecast
      };

      setData(prev => {
        const next = [...prev, newPoint];
        if (next.length > 50) next.shift(); // keep sliding window of max 50 points on screen
        return next;
      });

      if (payload.is_anomalous) {
        setSystemState('CRITICAL');
      } else if (payload.system_loss > payload.threshold * 0.8) {
        setSystemState('WARNING');
      } else {
        setSystemState('HEALTHY');
      }
    };

    return () => ws.close();
  }, []);

  const dismissAlarm = async () => {
    try {
      await fetch('http://localhost:8000/calibrate', { method: 'POST' });
      setSystemState('HEALTHY');
      console.log('Model weights successfully re-calibrated for concept drift.');
    } catch (err) {
      console.error('Failed to calibrate model', err);
    }
  };

  const getStatusColor = () => {
    if (systemState === 'CRITICAL') return 'text-red-500';
    if (systemState === 'WARNING') return 'text-yellow-500';
    return 'text-green-500';
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 p-6 font-sans">
      {/* Header */}
      <header className="flex justify-between items-center mb-8 border-b border-slate-800 pb-4">
        <div className="flex items-center space-x-3">
          <Activity className="w-8 h-8 text-blue-500" />
          <h1 className="text-2xl font-bold tracking-wider text-slate-100">STP-TranAD <span className="text-slate-500">| Predictive Telemetry Pipeline</span></h1>
        </div>
        <div className="flex items-center space-x-6">
          <div className="flex items-center space-x-2">
            <Database className="w-5 h-5 text-slate-400" />
            <span className="text-sm font-medium">Model: GAT + Transformer</span>
          </div>
          <div className={`px-4 py-1.5 rounded-full border ${isConnected ? 'border-green-500 bg-green-500/10 text-green-400' : 'border-slate-700 bg-slate-800 text-slate-400'} flex items-center space-x-2`}>
            <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500 animate-pulse' : 'bg-slate-500'}`} />
            <span className="text-sm font-bold">{isConnected ? 'LIVE STREAMING' : 'DISCONNECTED'}</span>
          </div>
        </div>
      </header>

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 mb-6">
        
        {/* System Health Card */}
        <div className="lg:col-span-1 bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-2xl flex flex-col justify-between">
          <div>
            <h2 className="text-sm uppercase tracking-widest text-slate-400 mb-6">System Status</h2>
            <div className="flex items-center justify-center py-8">
              {systemState === 'HEALTHY' ? (
                <CheckCircle className={`w-32 h-32 ${getStatusColor()}`} />
              ) : systemState === 'WARNING' ? (
                <AlertTriangle className={`w-32 h-32 ${getStatusColor()}`} />
              ) : (
                <ShieldAlert className={`w-32 h-32 ${getStatusColor()} animate-pulse`} />
              )}
            </div>
            <h3 className={`text-3xl text-center font-bold tracking-widest ${getStatusColor()}`}>{systemState}</h3>
          </div>
          
          <div className="mt-8 space-y-3">
            <button 
              onClick={dismissAlarm}
              disabled={systemState === 'HEALTHY'}
              className="w-full bg-slate-800 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed border border-slate-700 rounded-lg py-3 text-sm font-bold transition-all text-slate-300"
            >
              DISMISS (Calibrate Drift)
            </button>
            <button 
              className="w-full bg-blue-600 hover:bg-blue-500 border border-blue-500 rounded-lg py-3 text-sm font-bold transition-all text-white shadow-[0_0_15px_rgba(37,99,235,0.3)]"
            >
              ACKNOWLEDGE ALERT
            </button>
          </div>
        </div>

        {/* Reconstruction Loss Chart */}
        <div className="lg:col-span-3 bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-2xl">
          <div className="flex justify-between items-center mb-6">
            <h2 className="flex items-center space-x-2 text-sm uppercase tracking-widest text-slate-400">
              <Server className="w-4 h-4" />
              <span>GAT Spatio-Temporal Reconstruction Error</span>
            </h2>
            <span className="text-xs bg-slate-800 px-3 py-1 rounded text-slate-300">Evaluating 38 Dimensions</span>
          </div>
          <div className="h-[300px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 5, right: 20, left: -20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                <XAxis dataKey="tick" stroke="#475569" tick={{fill: '#64748b', fontSize: 12}} />
                <YAxis stroke="#475569" tick={{fill: '#64748b', fontSize: 12}} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px' }}
                  itemStyle={{ color: '#e2e8f0' }}
                />
                <ReferenceLine y={0.05} label="Threshold" stroke="#ef4444" strokeDasharray="3 3" />
                <Line 
                  type="monotone" 
                  dataKey="system_loss" 
                  stroke={systemState === 'CRITICAL' ? '#ef4444' : '#3b82f6'} 
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Sensor Multivariant Forecast Charts */}
      <h2 className="text-xl font-bold tracking-widest text-slate-300 mb-6 flex items-center">
        <Server className="w-5 h-5 mr-3 text-slate-500" />
        Dynamic Asset Telemetry ({dimensions} Active Dimensions)
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {Array.from({ length: dimensions }).map((_, i) => (
          <div key={i} className="bg-slate-900 border border-slate-800 rounded-lg p-4 hover:border-slate-700 transition-colors">
            <h2 className="text-[10px] sm:text-xs uppercase tracking-widest text-slate-400 mb-2 truncate">Metric {i} Forecast vs Actual</h2>
            <div className="h-[120px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data}>
                  <YAxis domain={['auto', 'auto']} stroke="#334155" tick={{fill: '#475569', fontSize: 10}} width={30} tickFormatter={(val) => val.toFixed(2)} />
                  <Tooltip 
                    wrapperStyle={{ outline: 'none' }} 
                    contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', borderRadius: '4px', fontSize: '12px' }} 
                  />
                  {/* Actual physical behavior */}
                  <Line 
                    type="stepAfter" 
                    dataKey={`s${i}_actual`} 
                    stroke="#64748b" 
                    strokeWidth={1.5} 
                    dot={false} 
                    isAnimationActive={false}
                  />
                  {/* Model Forecast trajectory */}
                  <Line 
                    type="monotone" 
                    dataKey={`s${i}_forecast`} 
                    stroke="#10b981" 
                    strokeWidth={1.5} 
                    strokeDasharray="4 4"
                    dot={false} 
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
