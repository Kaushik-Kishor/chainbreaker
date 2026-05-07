import { motion, AnimatePresence } from 'framer-motion';
import { X, Server, Activity, ShieldAlert, Crosshair, Wifi, BarChart3, AlertTriangle } from 'lucide-react';
import type { NodeEvent } from '../hooks/useWebSocket';
import { getAttackFamily, ATTACK_FAMILIES } from '../graph/cytoscapeConfig';

interface SidePanelProps {
  selectedNode: NodeEvent | null;
  onClose: () => void;
}

export function SidePanel({ selectedNode, onClose }: SidePanelProps) {
  if (!selectedNode) return null;

  const family = getAttackFamily(selectedNode.attack_type || 'BenignTraffic');
  const familyInfo = ATTACK_FAMILIES[family] || ATTACK_FAMILIES.unknown;
  const confidence = selectedNode.confidence ? (selectedNode.confidence * 100) : 0;
  const anomaly = selectedNode.anomaly_score || 0;

  const statusConfig: Record<string, { text: string; color: string; bg: string }> = {
    benign:     { text: 'Benign',           color: 'text-green-400',  bg: 'bg-green-400/10' },
    suspicious: { text: 'Suspicious',       color: 'text-orange-400', bg: 'bg-orange-400/10' },
    attack:     { text: 'Attack Detected',  color: 'text-red-400',    bg: 'bg-red-400/10' },
    critical:   { text: 'Critical Threat',  color: 'text-red-500',    bg: 'bg-red-500/15' },
  };

  const status = statusConfig[selectedNode.status] || statusConfig.benign;
  const severityLevel = anomaly > 80 ? 'CRITICAL' : anomaly > 50 ? 'HIGH' : anomaly > 20 ? 'MEDIUM' : 'LOW';
  const severityColor = anomaly > 80 ? 'text-red-400' : anomaly > 50 ? 'text-orange-400' : anomaly > 20 ? 'text-yellow-400' : 'text-green-400';

  return (
    <AnimatePresence>
      {selectedNode && (
        <motion.div
          initial={{ x: '100%', opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: '100%', opacity: 0 }}
          transition={{ type: 'spring', damping: 25, stiffness: 200 }}
          className="absolute top-0 right-0 h-full w-[380px] bg-[#0f0f11]/95 backdrop-blur-xl border-l border-white/5 z-30 shadow-2xl overflow-y-auto"
        >
          <div className="p-5">
            {/* Header */}
            <div className="flex justify-between items-center mb-6">
              <h2 className="text-[10px] uppercase tracking-[0.2em] text-slate-500 font-semibold">
                Host Inspector
              </h2>
              <button
                onClick={onClose}
                className="p-1.5 rounded-full hover:bg-slate-800 text-slate-400 transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* IP + Label */}
            <div className="mb-6">
              <div className="flex items-center gap-3 mb-1">
                <Server className="h-5 w-5 text-slate-400" />
                <h3 className="text-xl font-mono text-slate-100">{selectedNode.id}</h3>
              </div>
              <p className="text-xs text-slate-600 font-mono ml-8">{selectedNode.label}</p>
            </div>

            {/* ML Debug Panel */}
            <div
              className="mb-6 p-4 rounded-xl border"
              style={{
                borderColor: selectedNode.is_correct ? '#22c55e30' : '#ef444430',
                background: selectedNode.is_correct ? '#22c55e08' : '#ef444408',
              }}
            >
              <div className="flex items-center justify-between mb-3">
                <span className="text-[10px] uppercase tracking-wider text-slate-500">ML Prediction</span>
                <div
                  className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider flex items-center gap-1"
                  style={{ 
                    color: selectedNode.is_correct ? '#22c55e' : '#ef4444', 
                    backgroundColor: selectedNode.is_correct ? '#22c55e20' : '#ef444420' 
                  }}
                >
                  {selectedNode.is_correct ? 'Correct' : 'Mismatch'}
                </div>
              </div>
              
              <div className="space-y-3">
                <div>
                  <span className="text-[9px] text-slate-500 uppercase block mb-1">Predicted Class</span>
                  <div className="font-mono text-sm" style={{ color: familyInfo.color }}>
                    {selectedNode.attack_type || 'BenignTraffic'}
                  </div>
                </div>
                
                <div>
                  <span className="text-[9px] text-slate-500 uppercase block mb-1">Ground Truth (Label)</span>
                  <div className="font-mono text-sm text-slate-300">
                    {selectedNode.true_label || 'Unknown'}
                  </div>
                </div>
                
                <div>
                  <span className="text-[9px] text-slate-500 uppercase block mb-1">Family</span>
                  <div className="text-xs text-slate-400">
                    {familyInfo.label}
                  </div>
                </div>
              </div>
            </div>

            {/* Metric Cards */}
            <div className="grid grid-cols-2 gap-3 mb-6">
              {/* Status */}
              <div className={`p-3 rounded-xl border border-white/5 ${status.bg}`}>
                <div className="flex items-center gap-1.5 mb-1.5">
                  <ShieldAlert className={`h-3.5 w-3.5 ${status.color}`} />
                  <span className="text-[10px] uppercase tracking-wider text-slate-500">Status</span>
                </div>
                <div className={`font-semibold text-sm ${status.color}`}>
                  {status.text}
                </div>
              </div>

              {/* Severity */}
              <div className="p-3 rounded-xl border border-white/5 bg-slate-900/50">
                <div className="flex items-center gap-1.5 mb-1.5">
                  <AlertTriangle className={`h-3.5 w-3.5 ${severityColor}`} />
                  <span className="text-[10px] uppercase tracking-wider text-slate-500">Severity</span>
                </div>
                <div className={`font-bold text-sm ${severityColor}`}>
                  {severityLevel}
                </div>
              </div>

              {/* Confidence */}
              <div className="p-3 rounded-xl border border-white/5 bg-slate-900/50">
                <div className="flex items-center gap-1.5 mb-1.5">
                  <BarChart3 className="h-3.5 w-3.5 text-purple-400" />
                  <span className="text-[10px] uppercase tracking-wider text-slate-500">Confidence</span>
                </div>
                <div className="font-mono text-lg text-slate-200">
                  {confidence.toFixed(1)}
                  <span className="text-slate-500 text-xs ml-0.5">%</span>
                </div>
                <div className="mt-1.5 h-1 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${Math.min(confidence, 100)}%`,
                      backgroundColor: familyInfo.color,
                    }}
                  />
                </div>
              </div>

              {/* Anomaly Score */}
              <div className="p-3 rounded-xl border border-white/5 bg-slate-900/50">
                <div className="flex items-center gap-1.5 mb-1.5">
                  <Activity className="h-3.5 w-3.5 text-orange-400" />
                  <span className="text-[10px] uppercase tracking-wider text-slate-500">Anomaly</span>
                </div>
                <div className="font-mono text-lg text-slate-200">
                  {anomaly.toFixed(1)}
                  <span className="text-slate-500 text-xs ml-0.5">/100</span>
                </div>
                <div className="mt-1.5 h-1 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${Math.min(anomaly, 100)}%`,
                      backgroundColor: anomaly > 60 ? '#ef4444' : anomaly > 30 ? '#f97316' : '#22c55e',
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Network Info */}
            <div className="space-y-4">
              <div>
                <h4 className="text-[10px] uppercase tracking-[0.15em] text-slate-500 mb-2 flex items-center gap-1.5">
                  <Wifi className="h-3 w-3" />
                  Network Details
                </h4>
                <div className="space-y-1.5">
                  <div className="flex justify-between p-2.5 rounded-lg border border-white/5 bg-slate-900/30 text-xs font-mono">
                    <span className="text-slate-500">IP Address</span>
                    <span className="text-slate-200">{selectedNode.id}</span>
                  </div>
                  <div className="flex justify-between p-2.5 rounded-lg border border-white/5 bg-slate-900/30 text-xs font-mono">
                    <span className="text-slate-500">Attack Family</span>
                    <span style={{ color: familyInfo.color }}>{familyInfo.label}</span>
                  </div>
                  <div className="flex justify-between p-2.5 rounded-lg border border-white/5 bg-slate-900/30 text-xs font-mono">
                    <span className="text-slate-500">Attack Class</span>
                    <span className="text-slate-200 truncate ml-4">{selectedNode.attack_type || 'N/A'}</span>
                  </div>
                </div>
              </div>

              {/* Recent Flows */}
              <div>
                <h4 className="text-[10px] uppercase tracking-[0.15em] text-slate-500 mb-2 flex items-center gap-1.5">
                  <Crosshair className="h-3 w-3" />
                  Recent Activity
                </h4>
                <div className="space-y-1.5">
                  {[1, 2, 3].map((_, i) => (
                    <div key={i} className="flex justify-between items-center p-2.5 rounded-lg border border-white/5 bg-slate-900/30 text-xs font-mono text-slate-400">
                      <span>{selectedNode.id} &rarr; 10.0.1.{10 + i}</span>
                      <span className="text-slate-600 border border-slate-800 px-1.5 py-0.5 rounded text-[10px]">
                        TCP
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
