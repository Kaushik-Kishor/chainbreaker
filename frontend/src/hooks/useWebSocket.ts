import { useState, useEffect, useRef, useCallback } from 'react';

// Defines the structure of the incoming flow events from the Neo4j backend
export interface NodeEvent {
  id: string; // IP
  label: string;
  risk_score?: number; // legacy
  anomaly_score?: number; // 0 to 100 from ML
  confidence?: number;
  attack_type?: string;
  true_label?: string;
  is_correct?: boolean;
  ml_flag?: boolean;
  status: 'benign' | 'suspicious' | 'critical' | 'attack';
}

export interface EdgeEvent {
  source: string;
  target: string;
  protocol?: string;
  suspicious: boolean;
  lateral_movement?: boolean;
  rate?: number;
}

export interface ThreatSummary {
  flows: number;
  threats: number;
  live: boolean;
}

export interface WsMessage {
  type: string;
  nodes: NodeEvent[];
  edges: EdgeEvent[];
  telemetry_event?: Record<string, any>;
  threat_summary?: ThreatSummary;
  timestamp?: string;
}

export function useWebSocket(url: string) {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WsMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket(url);
      
      ws.onopen = () => {
        setIsConnected(true);
        console.log('[WebSocket] Connected to', url);
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
          reconnectTimeoutRef.current = null;
        }
      };

      ws.onmessage = (event) => {
        try {
          const data: WsMessage = JSON.parse(event.data);
          setLastMessage(data);
        } catch (e) {
          console.error('[WebSocket] Failed to parse message', e);
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        console.log('[WebSocket] Disconnected from', url);
        // Exponential backoff or simple retry
        if (!reconnectTimeoutRef.current) {
          reconnectTimeoutRef.current = setTimeout(connect, 5000) as unknown as number;
        }
      };

      ws.onerror = (error) => {
        console.error('[WebSocket] Error:', error);
        ws.close();
      };

      wsRef.current = ws;
    } catch (e) {
      console.error('[WebSocket] Failed to connect', e);
      if (!reconnectTimeoutRef.current) {
        reconnectTimeoutRef.current = setTimeout(connect, 5000) as unknown as number;
      }
    }
  }, [url]);

  useEffect(() => {
    connect();
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [connect]);

  // Expose a method to manually send data if necessary
  const sendMessage = useCallback((msg: any) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  return { isConnected, lastMessage, sendMessage };
}
