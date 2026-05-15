import { useState, useMemo, useEffect } from 'react';
import { TopBar } from './TopBar';
import { SidePanel } from './SidePanel';
import { GraphView } from './GraphView';
import { useWebSocket, type NodeEvent } from '../hooks/useWebSocket';

export function Layout() {
  const [selectedNode, setSelectedNode] = useState<NodeEvent | null>(null);
  const [connectedFlows, setConnectedFlows] = useState<any[]>([]);
  const [traceNodeId, setTraceNodeId] = useState<string | null>(null);
  const [expandedNodeId, setExpandedNodeId] = useState<string | null>(null);

  // Connect to the WebSocket (using a placeholder or environment variable URL)
  // Replaces the placeholder with dynamic window location if built in production
  const wsUrl = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/api/ws/telemetry';
  const { isConnected, lastMessage } = useWebSocket(wsUrl);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setSelectedNode(null);
        setTraceNodeId(null);
        setExpandedNodeId(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

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

  const lastEventTime = useMemo(() => {
    if (!lastMessage) return undefined;
    return new Date().toLocaleTimeString();
  }, [lastMessage]);

  const dominantFamily = useMemo(() => {
    if (!lastMessage || !lastMessage.nodes) return undefined;
    const counts: Record<string, number> = {};
    lastMessage.nodes.forEach(n => {
      // Basic extraction if backend is not sending full family info in this payload,
      // fallback to graph logic by pulling it from GraphView computation if we wanted.
      // Here we just look at the incoming nodes from the stream.
      const fam = n.attack_type || 'BenignTraffic';
      counts[fam] = (counts[fam] || 0) + 1;
    });
    const entries = Object.entries(counts).filter(([f]) => !f.toLowerCase().includes('benign'));
    if (entries.length === 0) return 'benign';
    entries.sort((a, b) => b[1] - a[1]);
    return entries[0][0]; // we'll rely on cytoscapeConfig getAttackFamily mapping inside TopBar
  }, [lastMessage]);

  return (
    <div className="relative w-full h-screen overflow-hidden bg-[#0a0a0a] font-sans selection:bg-slate-800">
      <TopBar 
        activeThreats={activeThreats} 
        suspiciousHosts={suspiciousHosts}
        totalFlows={totalFlows} 
        isConnected={isConnected} 
        lastEventTime={lastEventTime}
        dominantFamily={dominantFamily}
      />
      
      {/* Interactive Core */}
      <GraphView 
        wsMessage={lastMessage} 
        onNodeSelect={(node, flows) => {
          setSelectedNode(node);
          if (flows) setConnectedFlows(flows);
        }}
        traceNodeId={traceNodeId}
        expandedNodeId={expandedNodeId}
        onClearFocus={() => {
          setTraceNodeId(null);
          setExpandedNodeId(null);
        }}
      />

      <SidePanel 
        selectedNode={selectedNode}
        connectedFlows={connectedFlows}
        onClose={() => setSelectedNode(null)}
        onTraceChain={() => {
          if (selectedNode) {
            setTraceNodeId(selectedNode.id);
            setExpandedNodeId(null);
          }
        }}
        onExpandKillChain={() => {
          if (selectedNode) {
            setExpandedNodeId(selectedNode.id);
            setTraceNodeId(null);
          }
        }}
      />
    </div>
  );
}
