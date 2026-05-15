import React, { useEffect, useRef, useCallback, useState } from 'react';
import cytoscape from 'cytoscape';
import fcose from 'cytoscape-fcose';
import CytoscapeComponent from 'react-cytoscapejs';
import { Crosshair, Maximize2, RefreshCw } from 'lucide-react';
import {
  cytoscapeStylesheet,
  layoutConfig,
  getNodeColor,
  getNodeGlow,
  getAttackFamily,
  getClusterPosition,
  ATTACK_FAMILIES,
} from '../graph/cytoscapeConfig';
import type { WsMessage, NodeEvent } from '../hooks/useWebSocket';

cytoscape.use(fcose);

/* ═══════════════════════════════════════════════════════════════════════════
 *  TUNING CONSTANTS
 * ═══════════════════════════════════════════════════════════════════════════ */

const MAX_NODES              = 180;   // Rolling node cap
const MAX_EDGES              = 400;   // Rolling edge cap
const INITIAL_LAYOUT_AT      = 50;    // Run first layout after this many nodes
const RELAYOUT_BATCH         = 30;    // Re-layout after this many new unsettled nodes
const RELAYOUT_COOLDOWN_MS   = 20000; // Min ms between layouts (increased for stability)
const EDGE_FADE_MS           = 8000;  // Start fading edge after this
const EDGE_REMOVE_MS         = 25000; // Remove edge after this
const GC_INTERVAL_MS         = 4000;  // Garbage collection cycle
const STATS_INTERVAL_MS      = 2000;  // How often to recompute stats
const HUB_DEGREE_THRESHOLD   = 4;     // Nodes with this many edges get .hub class

const INFRA_IPS = new Set([
  '192.168.1.1', '192.168.1.2', '192.168.1.3',
  '10.0.0.1', '10.0.0.2', '10.0.1.1',
  '192.168.1.53', '192.168.1.100',
]);

/* ═══════════════════════════════════════════════════════════════════════════
 *  TYPES
 * ═══════════════════════════════════════════════════════════════════════════ */

interface GraphViewProps {
  wsMessage: WsMessage | null;
  onNodeSelect: (node: NodeEvent | null, connectedFlows?: any[]) => void;
  traceNodeId?: string | null;
  expandedNodeId?: string | null;
  onClearFocus?: () => void;
}

interface ThreatStats {
  totalNodes: number;
  totalEdges: number;
  attackNodes: number;
  suspiciousNodes: number;
  dominantFamily: string;
  familyCounts: Record<string, number>;
  totalPredictions: number;
  correctPredictions: number;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  NODE IMPORTANCE SCORING (for lifecycle eviction)
 * ═══════════════════════════════════════════════════════════════════════════ */

function computeImportance(node: cytoscape.NodeSingular, now: number): number {
  let score = 0;
  const status = node.data('status') || 'benign';
  const lastSeen = node.data('lastSeen') || 0;
  const age = now - lastSeen;

  // Status weight
  if (status === 'attack' || status === 'critical') score += 80;
  else if (status === 'suspicious') score += 50;

  // Connectivity (hubs are important)
  score += Math.min(node.degree(false) * 12, 60);

  // Recency
  if (age < 5000) score += 40;
  else if (age < 15000) score += 20;
  else if (age < 30000) score += 5;

  // Infrastructure is always important
  if (INFRA_IPS.has(node.id())) score += 100;

  // Anomaly score
  score += Math.min((node.data('anomaly_score') || 0) / 3, 30);

  return score;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  GRAPH VIEW COMPONENT
 * ═══════════════════════════════════════════════════════════════════════════ */

export const GraphView = React.memo(({ 
  wsMessage, 
  onNodeSelect, 
  traceNodeId, 
  expandedNodeId, 
  onClearFocus 
}: GraphViewProps) => {
  const cyRef = useRef<cytoscape.Core | null>(null);
  const layoutTimerRef = useRef<number>(0);
  const newNodeCountRef = useRef<number>(0);
  const initialLayoutDoneRef = useRef<boolean>(false);
  const manualPositionsRef = useRef<Map<string, { x: number; y: number }>>(new Map());
  const dashAnimationRef = useRef<number | null>(null);
  const [stats, setStats] = useState<ThreatStats>({
    totalNodes: 0, totalEdges: 0, attackNodes: 0, suspiciousNodes: 0,
    dominantFamily: 'benign', familyCounts: {}, totalPredictions: 0, correctPredictions: 0,
  });

  /* ── Layout runner (viewport-preserving) ─────────────────────────────── */
  const runLayout = useCallback((initial: boolean) => {
    const cy = cyRef.current;
    if (!cy || cy.nodes().length < 3) return;

    const now = Date.now();
    if (!initial && now - layoutTimerRef.current < RELAYOUT_COOLDOWN_MS) return;
    layoutTimerRef.current = now;

    // Save viewport
    const zoom = cy.zoom();
    const pan = { ...cy.pan() };

    // Lock manually positioned nodes
    manualPositionsRef.current.forEach((pos, id) => {
      const n = cy.getElementById(id);
      if (n.length > 0) { n.position(pos); n.lock(); }
    });

    const opts: any = {
      ...layoutConfig,
      animate: true,
      animationDuration: initial ? 1200 : 800,
      fit: initial,
      stop: () => {
        // Restore viewport for incremental layouts
        if (!initial) {
          cy.zoom(zoom);
          cy.pan(pan);
        }
        // Unlock
        manualPositionsRef.current.forEach((_, id) => {
          const n = cy.getElementById(id);
          if (n.length > 0) n.unlock();
        });
        // Mark hubs
        cy.nodes().forEach(n => {
          if (n.degree(false) >= HUB_DEGREE_THRESHOLD) n.addClass('hub');
          else n.removeClass('hub');
        });
      },
    };

    cy.layout(opts).run();
    newNodeCountRef.current = 0;
  }, []);

  /* ── Process incoming WS messages ────────────────────────────────────── */
  useEffect(() => {
    if (!wsMessage || !cyRef.current) return;
    const cy = cyRef.current;
    const now = Date.now();
    let newNodesAdded = 0;

    cy.batch(() => {
      /* ── NODES ──────────────────────────────────────────────────────── */
      wsMessage.nodes.forEach(node => {
        const attackType = node.attack_type || 'BenignTraffic';
        const family = getAttackFamily(attackType);
        const color = getNodeColor(attackType);
        const glowColor = getNodeGlow(attackType);
        const score = node.anomaly_score || 0;
        const trueLabel = node.true_label || 'BenignTraffic';
        const isCorrect = node.is_correct !== false; // default true if missing

        // Size by anomaly + base. We'll also boost by degree later.
        const baseSize = family === 'benign' ? 12 : 16;
        const size = baseSize + Math.min(score / 5, 20);
        
        // Correctness borders
        let borderColor = family === 'benign' ? '#22c55e30' : color;
        if (!isCorrect) {
          borderColor = '#ef4444'; // Red border for incorrect predictions
        } else if (family !== 'benign') {
          borderColor = '#22c55e'; // Green border for correct attack predictions
        }

        const isInfra = INFRA_IPS.has(node.id);

        const existing = cy.getElementById(node.id);

        if (existing.length > 0) {
          const newData: any = {
            status: node.status,
            attack_type: attackType,
            attack_family: family,
            true_label: trueLabel,
            is_correct: isCorrect,
            color, glowColor, borderColor, size,
            lastSeen: now,
          };
          if (node.anomaly_score !== undefined) newData.anomaly_score = score;
          if (node.confidence !== undefined) newData.confidence = node.confidence;
          existing.data(newData);
          existing.removeClass('fading');

          if (node.status === 'attack' || node.status === 'critical') {
            existing.addClass('pulse');
          } else {
            existing.removeClass('pulse');
          }
          if (node.confidence !== undefined && node.confidence < 60.0) {
            existing.addClass('unreliable');
          } else {
            existing.removeClass('unreliable');
          }
          if (!isCorrect) {
            existing.addClass('misclassified');
          } else {
            existing.removeClass('misclassified');
          }
        } else {
          // Pre-position by cluster
          const pos = getClusterPosition(node.id);

          const n = cy.add({
            group: 'nodes',
            data: {
              id: node.id,
              label: node.id,
              status: node.status,
              anomaly_score: score,
              confidence: node.confidence,
              attack_type: attackType,
              attack_family: family,
              true_label: trueLabel,
              is_correct: isCorrect,
              color, glowColor, borderColor, size,
              lastSeen: now,
            },
            position: pos,
          });

          if (isInfra) n.addClass('infra');
          if (node.status === 'attack' || node.status === 'critical') n.addClass('pulse');
          if (node.confidence !== undefined && node.confidence < 60.0) n.addClass('unreliable');
          if (!isCorrect) n.addClass('misclassified');
          if (traceNodeId || expandedNodeId) n.addClass('dimmed'); // Dim new nodes if trace is active
          newNodesAdded++;
        }
      });

      /* ── EDGES ──────────────────────────────────────────────────────── */
      wsMessage.edges.forEach(edge => {
        const edgeId = `${edge.source}->${edge.target}`;
        const existing = cy.getElementById(edgeId);

        const srcNode = cy.getElementById(edge.source);
        const srcFamily = srcNode.length > 0 ? srcNode.data('attack_family') : 'unknown';

        let color = '#27272a';
        if (edge.suspicious) {
          color = ATTACK_FAMILIES[srcFamily]?.color || '#ef4444';
        } else if (edge.lateral_movement) {
          color = '#a855f760';
        }

        const thickness = Math.min(1 + (edge.rate || 0) / 600, 4.5);

        if (existing.length > 0) {
          existing.data({
            color, thickness,
            opacity: edge.suspicious ? 0.75 : 0.35,
            lastSeen: now,
            suspicious: edge.suspicious ? 1 : 0,
          });
        } else {
          if (cy.edges().length >= MAX_EDGES) return;
          if (cy.getElementById(edge.source).length === 0 || cy.getElementById(edge.target).length === 0) return;

          cy.add({
            group: 'edges',
            data: {
              id: edgeId,
              source: edge.source,
              target: edge.target,
              color, thickness,
              opacity: edge.suspicious ? 0.75 : 0.35,
              lastSeen: now,
              suspicious: edge.suspicious ? 1 : 0,
              protocol: edge.protocol || 'TCP',
            },
          });
          if (traceNodeId || expandedNodeId) cy.getElementById(edgeId).addClass('dimmed');
        }
      });
    });

    /* ── Layout triggers ──────────────────────────────────────────────── */
    newNodeCountRef.current += newNodesAdded;

    if (!initialLayoutDoneRef.current && cy.nodes().length >= INITIAL_LAYOUT_AT) {
      initialLayoutDoneRef.current = true;
      runLayout(true);
    } else if (initialLayoutDoneRef.current && newNodeCountRef.current >= RELAYOUT_BATCH) {
      runLayout(false);
    }
  }, [wsMessage, runLayout]);

  /* ── Lifecycle GC: edge fade + node eviction ─────────────────────────── */
  useEffect(() => {
    const interval = setInterval(() => {
      const cy = cyRef.current;
      if (!cy) return;

      const now = Date.now();
      cy.batch(() => {
        /* ── Edge lifecycle ────────────────────────────────────────────── */
        cy.edges().forEach(edge => {
          const lastSeen = edge.data('lastSeen') || now;
          const age = now - lastSeen;

          if (age > EDGE_REMOVE_MS) {
            cy.remove(edge);
          } else if (age > EDGE_FADE_MS) {
            const fade = Math.max(0.06, 0.35 * (1 - (age - EDGE_FADE_MS) / (EDGE_REMOVE_MS - EDGE_FADE_MS)));
            edge.data('opacity', fade);
          }
        });

        /* ── Node lifecycle: cap + evict ───────────────────────────────── */
        const nodeCount = cy.nodes().length;
        if (nodeCount > MAX_NODES) {
          const scored = cy.nodes().map(n => ({
            node: n,
            importance: computeImportance(n, now),
          }));
          scored.sort((a, b) => a.importance - b.importance);

          const toRemove = nodeCount - MAX_NODES + 10; // remove 10 extra for headroom
          for (let i = 0; i < toRemove && i < scored.length; i++) {
            const n = scored[i].node;
            // Don't remove manually positioned or infra nodes
            if (manualPositionsRef.current.has(n.id())) continue;
            if (INFRA_IPS.has(n.id())) continue;
            // Fade out then remove
            n.addClass('fading');
            setTimeout(() => {
              if (cyRef.current) cyRef.current.remove(n);
            }, 2000);
          }
        }

        /* ── Adaptive density: dim edges when graph is dense ──────────── */
        const edgeCount = cy.edges().length;
        if (edgeCount > 250) {
          const dimFactor = Math.max(0.1, 1 - (edgeCount - 250) / 400);
          cy.edges().forEach(e => {
            const base = e.data('suspicious') ? 0.75 : 0.35;
            e.data('opacity', Math.max(0.06, base * dimFactor));
          });
        }

        /* ── Size boost for hubs ──────────────────────────────────────── */
        cy.nodes().forEach(n => {
          const deg = n.degree(false);
          if (deg >= HUB_DEGREE_THRESHOLD) {
            const currentSize = n.data('size') || 16;
            const hubBoost = Math.min(deg * 2, 16);
            n.data('size', Math.max(currentSize, 16 + hubBoost));
            n.addClass('hub');
          }
        });
      });
    }, GC_INTERVAL_MS);

    return () => clearInterval(interval);
  }, []);

  /* ── Stats computation (throttled) ───────────────────────────────────── */
  useEffect(() => {
    const interval = setInterval(() => {
      const cy = cyRef.current;
      if (!cy) return;

      const familyCounts: Record<string, number> = {};
      let attackCount = 0;
      let suspiciousCount = 0;
      let totalPreds = 0;
      let correctPreds = 0;

      cy.nodes().forEach(n => {
        const fam = n.data('attack_family') || 'unknown';
        familyCounts[fam] = (familyCounts[fam] || 0) + 1;
        const st = n.data('status');
        if (st === 'attack' || st === 'critical') attackCount++;
        if (st === 'suspicious') suspiciousCount++;
        
        // Exclude infra nodes from ML accuracy as they are hardcoded
        if (!INFRA_IPS.has(n.id())) {
            totalPreds++;
            if (n.data('is_correct') !== false) correctPreds++;
        }
      });

      const entries = Object.entries(familyCounts);
      const dominant = entries.length > 0
        ? entries.sort((a, b) => b[1] - a[1])[0][0]
        : 'benign';

      setStats({
        totalNodes: cy.nodes().length,
        totalEdges: cy.edges().length,
        attackNodes: attackCount,
        suspiciousNodes: suspiciousCount,
        dominantFamily: dominant,
        familyCounts,
        totalPredictions: totalPreds,
        correctPredictions: correctPreds,
      });
    }, STATS_INTERVAL_MS);

    return () => clearInterval(interval);
  }, []);

  /* ── Attack Chain Highlighting & Expansion ───────────────────────────── */
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    if (dashAnimationRef.current) {
      clearInterval(dashAnimationRef.current);
      dashAnimationRef.current = null;
    }

    cy.batch(() => {
      // Reset classes
      cy.elements().removeClass('highlighted dimmed chain-edge');
      cy.edges().removeStyle('line-dash-offset');

      const focusId = traceNodeId || expandedNodeId;
      if (focusId) {
        const root = cy.getElementById(focusId);
        if (root.length > 0) {
          // BFS up to depth 4 to find connected subgraphs
          // For kill chain, we want both predecessors (sources) and successors (targets)
          const chain = root.successors().union(root.predecessors()).union(root);
          
          const nodes = chain.filter('node');
          const edges = chain.filter('edge');

          nodes.addClass('highlighted');
          edges.addClass('highlighted chain-edge');

          const others = cy.elements().difference(chain);
          others.addClass('dimmed');

          // Smooth animated zoom-out for kill chain
          if (expandedNodeId) {
            cy.animate({
              fit: {
                eles: chain,
                padding: 100
              },
              duration: 1000,
              easing: 'ease-out-quint'
            });
          } else {
            // Just center on traced node
            cy.animate({
              center: { eles: root },
              zoom: Math.max(cy.zoom(), 1.5),
              duration: 500
            });
          }

          // Animate edge dashes
          let offset = 24;
          dashAnimationRef.current = setInterval(() => {
            offset -= 1;
            edges.style('line-dash-offset', offset);
          }, 50) as unknown as number;
        }
      }
    });

    return () => {
      if (dashAnimationRef.current) clearInterval(dashAnimationRef.current);
    };
  }, [traceNodeId, expandedNodeId]);

  /* ── Render ──────────────────────────────────────────────────────────── */
  return (
    <div className="absolute inset-0 bg-[#0a0a0a]">
      <CytoscapeComponent
        elements={[]}
        stylesheet={cytoscapeStylesheet}
        style={{ width: '100%', height: '100%' }}
        minZoom={0.1}
        maxZoom={5.0}
        wheelSensitivity={0.12}
        cy={(cy) => {
          cyRef.current = cy;

          // ── Node click → inspector ────────────────────────────────
          cy.on('tap', 'node', (evt) => {
            const node = evt.target;
            const d = node.data();
            
            // Extract connected edges for side panel
            const connectedEdges = node.connectedEdges().map((e: any) => {
              const src = e.source().id();
              const tgt = e.target().id();
              const dir = src === d.id ? 'outbound' : 'inbound';
              const peerId = dir === 'outbound' ? tgt : src;
              return {
                id: e.id(),
                peerId,
                direction: dir,
                suspicious: e.data('suspicious'),
                protocol: e.data('protocol') || 'TCP',
              };
            });

            onNodeSelect({
              id: d.id,
              label: d.label,
              status: d.status,
              risk_score: d.anomaly_score || 0,
              anomaly_score: d.anomaly_score,
              confidence: d.confidence,
              attack_type: d.attack_type,
              true_label: d.true_label,
              is_correct: d.is_correct,
            }, connectedEdges);
          });

          cy.on('tap', (evt) => {
            if (evt.target === cy) onNodeSelect(null);
          });

          // ── Drag → persist position ───────────────────────────────
          cy.on('dragfree', 'node', (evt) => {
            const node = evt.target;
            manualPositionsRef.current.set(node.id(), { ...node.position() });
          });
        }}
      />

      {/* ── Attack Families Legend ───────────────────────────────────── */}
      <div 
        className="absolute bottom-4 left-4 z-20 bg-[#0a0a0a]/90 backdrop-blur-md border border-white/10 rounded-xl p-3.5 pointer-events-auto select-none"
        style={{ resize: 'both', overflow: 'hidden', minWidth: '220px', minHeight: '150px' }}
      >
        <h4 className="text-[9px] uppercase tracking-[0.2em] text-slate-600 font-semibold mb-2.5">
          Attack Families
        </h4>
        <div className="grid grid-cols-2 gap-x-5 gap-y-1">
          {Object.entries(ATTACK_FAMILIES).map(([key, fam]) => (
            <div key={key} className="flex items-center gap-1.5">
              <div
                className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ backgroundColor: fam.color, boxShadow: `0 0 4px ${fam.glow}` }}
              />
              <span className="text-[10px] text-slate-500 font-mono">{fam.label}</span>
              {stats.familyCounts[key] ? (
                <span className="text-[9px] text-slate-600 font-mono ml-auto tabular-nums">
                  {stats.familyCounts[key]}
                </span>
              ) : null}
            </div>
          ))}
        </div>
        <div className="mt-3 pt-2 border-t border-white/10 space-y-1.5">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-slate-400" />
            <span className="text-[9px] text-slate-500 font-mono">Stable Telemetry</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rotate-45 bg-[#eab308]" />
            <span className="text-[9px] text-slate-500 font-mono">Uncertain (&lt;60% Conf)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full border border-dashed border-[#ef4444]" />
            <span className="text-[9px] text-slate-500 font-mono">ML Mismatch (Eval)</span>
          </div>
        </div>
      </div>

      {/* ── Overlay Controls ─────────────────────────────────────────── */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-3">
        {(traceNodeId || expandedNodeId) && (
          <button
            onClick={onClearFocus}
            className="flex items-center gap-2 bg-slate-800/90 hover:bg-slate-700/90 backdrop-blur-md border border-white/10 rounded-full px-4 py-2 text-xs font-semibold text-slate-200 transition-colors shadow-xl animate-fade-in"
          >
            Clear Focus
          </button>
        )}
        <button
          onClick={() => runLayout(false)}
          className="p-2 bg-slate-800/90 hover:bg-slate-700/90 backdrop-blur-md border border-white/10 rounded-full text-slate-400 hover:text-slate-200 transition-colors"
          title="Re-layout graph"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
        <button
          onClick={() => { if (cyRef.current) cyRef.current.fit(undefined, 80); }}
          className="p-2 bg-slate-800/90 hover:bg-slate-700/90 backdrop-blur-md border border-white/10 rounded-full text-slate-400 hover:text-slate-200 transition-colors"
          title="Zoom to fit"
        >
          <Maximize2 className="h-4 w-4" />
        </button>
      </div>

      {/* ── Threat Intel HUD ─────────────────────────────────────────── */}
      <div 
        className="absolute bottom-4 right-4 z-20 bg-[#0a0a0a]/90 backdrop-blur-md border border-white/10 rounded-xl p-3.5 pointer-events-auto select-none"
        style={{ resize: 'both', overflow: 'hidden', minWidth: '190px', minHeight: '160px' }}
      >
        <h4 className="text-[9px] uppercase tracking-[0.2em] text-slate-600 font-semibold mb-2.5">
          Threat Intel
        </h4>
        <div className="space-y-1.5">
          <div className="flex justify-between text-[11px]">
            <span className="text-slate-500">Nodes</span>
            <span className="text-slate-300 font-mono tabular-nums">{stats.totalNodes}</span>
          </div>
          <div className="flex justify-between text-[11px]">
            <span className="text-slate-500">Edges</span>
            <span className="text-slate-300 font-mono tabular-nums">{stats.totalEdges}</span>
          </div>
          <div className="flex justify-between text-[11px]">
            <span className="text-red-400/80">Attacks</span>
            <span className="text-red-300 font-mono tabular-nums">{stats.attackNodes}</span>
          </div>
          <div className="flex justify-between text-[11px]">
            <span className="text-orange-400/80">Suspicious</span>
            <span className="text-orange-300 font-mono tabular-nums">{stats.suspiciousNodes}</span>
          </div>
          <div className="flex justify-between text-[11px] border-t border-white/5 pt-1.5 mt-1">
            <span className="text-slate-500">Live ML Acc</span>
            <span className="text-green-400 font-mono tabular-nums">
              {stats.totalPredictions > 0 
                ? `${((stats.correctPredictions / stats.totalPredictions) * 100).toFixed(1)}%` 
                : '100%'}
            </span>
          </div>
          <div className="flex justify-between text-[11px] border-t border-white/5 pt-1.5 mt-1">
            <span className="text-slate-500">Dominant</span>
            <span
              className="font-mono text-[11px]"
              style={{ color: ATTACK_FAMILIES[stats.dominantFamily]?.color || '#71717a' }}
            >
              {ATTACK_FAMILIES[stats.dominantFamily]?.label || 'Unknown'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
});

GraphView.displayName = 'GraphView';
