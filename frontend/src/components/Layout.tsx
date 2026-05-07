import { useState, useMemo } from 'react';
import { TopBar } from './TopBar';
import { SidePanel } from './SidePanel';
import { GraphView } from './GraphView';
import { useWebSocket, type NodeEvent } from '../hooks/useWebSocket';

export function Layout() {
  const [selectedNode, setSelectedNode] = useState<NodeEvent | null>(null);

  // Connect to the WebSocket (using a placeholder or environment variable URL)
  // Replaces the placeholder with dynamic window location if built in production
  const wsUrl = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/api/ws/telemetry';
  const { isConnected, lastMessage } = useWebSocket(wsUrl);

  const activeThreats = useMemo(() => {
    return lastMessage?.threat_summary?.threats || 0;
  }, [lastMessage]);

  const suspiciousHosts = useMemo(() => {
    // If backend doesn't provide suspicious explicitly, compute it
    if (!lastMessage) return 0;
    return lastMessage.nodes.filter(n => n.status === 'suspicious').length;
  }, [lastMessage]);

  const totalFlows = useMemo(() => {
    return lastMessage?.threat_summary?.flows || 0;
  }, [lastMessage]);

  return (
    <div className="relative w-full h-screen overflow-hidden bg-[#0a0a0a] font-sans selection:bg-slate-800">
      <TopBar 
        activeThreats={activeThreats} 
        suspiciousHosts={suspiciousHosts}
        totalFlows={totalFlows} 
        isConnected={isConnected} 
      />
      
      {/* Interactive Core */}
      <GraphView 
        wsMessage={lastMessage} 
        onNodeSelect={setSelectedNode} 
      />

      <SidePanel 
        selectedNode={selectedNode} 
        onClose={() => setSelectedNode(null)} 
      />
    </div>
  );
}
