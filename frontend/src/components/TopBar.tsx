import { Activity, ShieldCheck, Zap, Radio, Skull, Eye, Clock, Shield } from 'lucide-react';
import { ATTACK_FAMILIES } from '../graph/cytoscapeConfig';

interface TopBarProps {
  activeThreats: number;
  suspiciousHosts: number;
  totalFlows: number;
  isConnected: boolean;
  lastEventTime?: string;
  dominantFamily?: string;
}

export function TopBar({ activeThreats, suspiciousHosts, totalFlows, isConnected, lastEventTime, dominantFamily }: TopBarProps) {
  const familyInfo = dominantFamily ? (ATTACK_FAMILIES[dominantFamily] || ATTACK_FAMILIES.unknown) : null;
  return (
    <div className="absolute top-0 left-0 w-full z-20 flex items-center justify-between px-4 py-3 pointer-events-auto">
      {/* Brand */}
      <div className="flex items-center gap-2.5 bg-[#0a0a0a]/85 backdrop-blur-md border border-white/5 py-2 px-4 rounded-full">
        <Zap className="h-4 w-4 text-cyan-500" />
        <span className="font-semibold text-slate-100 tracking-wide text-sm">ChainBreaker</span>
        <span className="text-[10px] text-cyan-500/60 font-mono">NIDS</span>
      </div>

      {/* Stats */}
      <div className="flex items-center gap-2.5">
        {/* Last Event */}
        {lastEventTime && (
          <div className="flex items-center gap-2 bg-[#0a0a0a]/85 backdrop-blur-md border border-white/5 py-1.5 px-3 rounded-full text-xs">
            <Clock className="h-3 w-3 text-slate-500" />
            <span className="text-slate-400 font-mono text-[11px]">{lastEventTime}</span>
          </div>
        )}

        {/* Dominant Family */}
        {familyInfo && (
          <div className="flex items-center gap-2 bg-[#0a0a0a]/85 backdrop-blur-md border border-white/5 py-1.5 px-3 rounded-full text-xs">
            <div 
              className="w-2 h-2 rounded-full" 
              style={{ backgroundColor: familyInfo.color, boxShadow: `0 0 6px ${familyInfo.glow}` }}
            />
            <span className="text-slate-300 font-mono text-[11px] uppercase">{familyInfo.label}</span>
          </div>
        )}

        {/* Total Flows */}
        <div className="flex items-center gap-2 bg-[#0a0a0a]/85 backdrop-blur-md border border-white/5 py-1.5 px-3 rounded-full text-xs">
          <Activity className="h-3.5 w-3.5 text-slate-500" />
          <span className="text-slate-300 font-mono tabular-nums transition-all">{totalFlows.toLocaleString()}</span>
          <span className="text-slate-600 text-[10px] uppercase tracking-wider">Flows</span>
        </div>

        {/* Suspicious */}
        <div className={`flex items-center gap-2 bg-[#0a0a0a]/85 backdrop-blur-md border py-1.5 px-3 rounded-full text-xs
          ${suspiciousHosts > 0 ? 'border-orange-500/20' : 'border-white/5'}`}
        >
          <Eye className={`h-3.5 w-3.5 ${suspiciousHosts > 0 ? 'text-orange-500' : 'text-slate-500'}`} />
          <span className={`font-mono tabular-nums ${suspiciousHosts > 0 ? 'text-orange-400' : 'text-slate-400'}`}>
            {suspiciousHosts}
          </span>
          <span className="text-slate-600 text-[10px] uppercase tracking-wider">Suspicious</span>
        </div>

        {/* Active Threats */}
        <div className={`flex items-center gap-2 bg-[#0a0a0a]/85 backdrop-blur-md border py-1.5 px-3 rounded-full text-xs transition-colors
          ${activeThreats > 0 ? 'border-red-500/20 shadow-[0_0_10px_rgba(239,68,68,0.1)]' : 'border-white/5'}`}
        >
          <Skull className={`h-3.5 w-3.5 transition-colors ${activeThreats > 0 ? 'text-red-500' : 'text-slate-500'}`} />
          <span className={`font-mono tabular-nums transition-colors ${activeThreats > 0 ? 'text-red-400' : 'text-slate-400'}`}>
            {activeThreats}
          </span>
          <span className="text-slate-600 text-[10px] uppercase tracking-wider">Threats</span>
        </div>

        {/* Connection */}
        <div className="flex items-center gap-2 bg-[#0a0a0a]/85 backdrop-blur-md border border-white/5 py-1.5 px-3 rounded-full text-xs">
          <div className="relative flex h-2 w-2">
            {isConnected && (
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            )}
            <span className={`relative inline-flex rounded-full h-2 w-2 ${isConnected ? 'bg-emerald-500' : 'bg-red-500'}`} />
          </div>
          <Radio className={`h-3 w-3 ${isConnected ? 'text-emerald-500' : 'text-red-500'}`} />
          <span className="text-slate-500 text-[10px] uppercase tracking-wider">
            {isConnected ? 'Live' : 'Offline'}
          </span>
        </div>
      </div>
    </div>
  );
}
