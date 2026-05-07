/* ═══════════════════════════════════════════════════════════════════════════
 *  cytoscapeConfig.ts — SOC-grade graph configuration for ChainBreaker NIDS
 *
 *  Features:
 *  - 10 attack family color palette for 34 CICIoT2023 classes
 *  - Cluster-based spatial positioning (IoT, External, Internal, Infra)
 *  - Zoom-aware label visibility
 *  - Glow/pulse effects for active threats
 *  - Organic fcose layout tuned for web-like topology
 * ═══════════════════════════════════════════════════════════════════════════ */

/* ── Attack Family System ──────────────────────────────────────────────── */

export interface AttackFamily {
  color: string;
  glow: string;
  label: string;
}

export const ATTACK_FAMILIES: Record<string, AttackFamily> = {
  ddos:       { color: '#ef4444', glow: '#ef444480', label: 'DDoS' },
  dos:        { color: '#f97316', glow: '#f9731680', label: 'DoS' },
  mirai:      { color: '#a855f7', glow: '#a855f780', label: 'Mirai / Botnet' },
  recon:      { color: '#eab308', glow: '#eab30880', label: 'Recon / Scanning' },
  bruteforce: { color: '#f43f5e', glow: '#f43f5e80', label: 'Brute Force' },
  spoofing:   { color: '#ec4899', glow: '#ec489980', label: 'Spoofing / MITM' },
  web:        { color: '#06b6d4', glow: '#06b6d480', label: 'Web Attacks' },
  malware:    { color: '#dc2626', glow: '#dc262680', label: 'Malware / Backdoor' },
  benign:     { color: '#22c55e', glow: '#22c55e40', label: 'Benign' },
  unknown:    { color: '#71717a', glow: '#71717a40', label: 'Unknown' },
};

export function getAttackFamily(attackType: string): string {
  const lbl = (attackType || '').toLowerCase();
  if (lbl.includes('benign'))                                       return 'benign';
  if (lbl.startsWith('ddos'))                                       return 'ddos';
  if (lbl.startsWith('dos'))                                        return 'dos';
  if (lbl.includes('mirai') || lbl.includes('botnet'))              return 'mirai';
  if (lbl.includes('recon') || lbl.includes('scan') || lbl.includes('ping')) return 'recon';
  if (lbl.includes('brute') || lbl.includes('dictionary'))          return 'bruteforce';
  if (lbl.includes('spoof') || lbl.includes('mitm') || lbl.includes('arp')) return 'spoofing';
  if (lbl.includes('xss') || lbl.includes('sql') || lbl.includes('injection') || lbl.includes('browser') || lbl.includes('upload')) return 'web';
  if (lbl.includes('backdoor') || lbl.includes('malware'))          return 'malware';
  return 'unknown';
}

export function getNodeColor(attackType: string): string {
  return ATTACK_FAMILIES[getAttackFamily(attackType)]?.color || ATTACK_FAMILIES.unknown.color;
}

export function getNodeGlow(attackType: string): string {
  return ATTACK_FAMILIES[getAttackFamily(attackType)]?.glow || ATTACK_FAMILIES.unknown.glow;
}

/* ── Cluster Spatial Positioning ───────────────────────────────────────── */
// Pre-positions nodes by subnet into spatial clusters for organic topology

interface ClusterZone {
  cx: number;
  cy: number;
  radius: number;
}

const CLUSTER_ZONES: Record<string, ClusterZone> = {
  iot:          { cx: -500, cy: -350, radius: 200 },   // top-left: IoT devices
  external_a:  { cx: -150, cy:  -50, radius: 250 },    // center-left: external attackers (203.x)
  external_b:  { cx:  -50, cy:  200, radius: 200 },    // center-bottom: external (198.x)
  external_c:  { cx: -350, cy:  100, radius: 150 },    // left: external (45.x)
  servers:     { cx:  450, cy: -200, radius: 200 },     // right-top: internal servers
  workstations:{ cx:  450, cy:  200, radius: 180 },     // right-bottom: workstations
  infra:       { cx:  200, cy:    0, radius: 100 },     // center-right: routers/gateways
  dmz:         { cx:  250, cy: -350, radius: 120 },     // top-right: DMZ
};

/** Hash a string to a stable number (0–1) */
function hashStr(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return Math.abs(h % 10000) / 10000;
}

/** Deterministic angle from IP for placement around cluster center */
function ipToAngle(ip: string): number {
  const octets = ip.split('.').map(Number);
  return (hashStr(ip) * Math.PI * 2);
}

/** Get initial position for a node based on its IP subnet */
export function getClusterPosition(ip: string): { x: number; y: number } {
  const octets = ip.split('.').map(Number);
  const angle = ipToAngle(ip);
  const jitter = hashStr(ip + 'jit');

  let zone: ClusterZone;

  // IoT
  if (octets[0] === 192 && octets[1] === 168 && octets[2] === 10) {
    zone = CLUSTER_ZONES.iot;
  }
  // Internal servers (192.168.1.10-49)
  else if (octets[0] === 192 && octets[1] === 168 && octets[2] === 1 && octets[3] < 50) {
    zone = CLUSTER_ZONES.servers;
  }
  // Workstations (192.168.1.50-89)
  else if (octets[0] === 192 && octets[1] === 168 && octets[2] === 1 && octets[3] >= 50 && octets[3] < 100) {
    zone = CLUSTER_ZONES.workstations;
  }
  // Infrastructure
  else if (octets[0] === 192 && octets[1] === 168 && octets[2] === 1 && octets[3] < 10) {
    zone = CLUSTER_ZONES.infra;
  }
  // DMZ (10.0.x)
  else if (octets[0] === 10) {
    zone = CLUSTER_ZONES.dmz;
  }
  // External 203.x
  else if (octets[0] === 203) {
    zone = CLUSTER_ZONES.external_a;
  }
  // External 198.x
  else if (octets[0] === 198) {
    zone = CLUSTER_ZONES.external_b;
  }
  // External 45.x
  else if (octets[0] === 45) {
    zone = CLUSTER_ZONES.external_c;
  }
  else {
    zone = CLUSTER_ZONES.external_a;
  }

  const r = zone.radius * (0.1 + jitter * 0.9) + (Math.random() * 40 - 20); // break grid completely
  const noisy_angle = angle + (Math.random() * 0.4 - 0.2); // radial offset noise

  return {
    x: zone.cx + Math.cos(noisy_angle) * r,
    y: zone.cy + Math.sin(noisy_angle) * r,
  };
}

/* ── Dark theme ────────────────────────────────────────────────────────── */

export const darkThemeColors = {
  background: '#0a0a0a',
  nodeLabel: '#e4e4e7',
  edgeBase: '#3f3f46',
};

/* ── Cytoscape Stylesheet ──────────────────────────────────────────────── */

export const cytoscapeStylesheet: any[] = [
  // ── Base nodes ─────────────────────────────────────────────────────
  {
    selector: 'node',
    style: {
      'width': 'data(size)',
      'height': 'data(size)',
      'background-color': 'data(color)',
      'background-opacity': 0.9,
      'label': 'data(label)',
      'color': '#a1a1aa',
      'font-size': '9px',
      'font-family': '"JetBrains Mono", "Fira Code", monospace',
      'font-weight': 500,
      'text-valign': 'bottom',
      'text-halign': 'center',
      'text-margin-y': 5,
      'text-background-color': '#0a0a0a',
      'text-background-opacity': 0.8,
      'text-background-padding': '2px',
      'text-background-shape': 'roundrectangle',
      'min-zoomed-font-size': 12,  // Hide labels at low zoom
      'border-width': 2,
      'border-color': 'data(borderColor)',
      'border-opacity': 0.9,
      'overlay-opacity': 0,
      'transition-property': 'background-color, width, height, border-color, border-width, background-opacity',
      'transition-duration': 400 as any,
    }
  },
  // ── Selected node ──────────────────────────────────────────────────
  {
    selector: 'node:selected',
    style: {
      'border-width': 3,
      'border-color': '#ffffff',
      'border-opacity': 1,
      'shadow-blur': 25,
      'shadow-color': 'data(color)',
      'shadow-opacity': 1,
      'text-opacity': 1,
      'z-index': 999,
    }
  },
  // ── Active threat pulse ────────────────────────────────────────────
  {
    selector: '.pulse',
    style: {
      'border-width': 4,
      'border-color': 'data(color)',
      'border-opacity': 0.85,
      'shadow-blur': 35,
      'shadow-color': 'data(glowColor)',
      'shadow-opacity': 0.7,
      'background-opacity': 1,
    }
  },
  // ── Important/hub node ─────────────────────────────────────────────
  {
    selector: '.hub',
    style: {
      'font-size': '10px',
      'color': '#e4e4e7',
      'font-weight': 700,
      'min-zoomed-font-size': 8,
      'text-background-opacity': 0.9,
    }
  },
  // ── Infrastructure (diamond) ───────────────────────────────────────
  {
    selector: '.infra',
    style: {
      'shape': 'diamond',
      'border-width': 2,
      'border-color': '#3b82f6',
      'border-opacity': 0.8,
    }
  },
  // ── Fading out nodes (lifecycle) ───────────────────────────────────
  {
    selector: '.fading',
    style: {
      'opacity': 0.3,
      'text-opacity': 0,
      'transition-property': 'opacity',
      'transition-duration': 2000 as any,
    }
  },
  // ── Edges ──────────────────────────────────────────────────────────
  {
    selector: 'edge',
    style: {
      'width': 'data(thickness)',
      'line-color': 'data(color)',
      'curve-style': 'unbundled-bezier',
      'control-point-distances': [20],
      'control-point-weights': [0.5],
      'target-arrow-shape': 'triangle',
      'target-arrow-color': 'data(color)',
      'arrow-scale': 0.8,
      'opacity': 'data(opacity)',
      'overlay-opacity': 0,
      'transition-property': 'line-color, width, opacity',
      'transition-duration': 600 as any,
    }
  },
  // ── Suspicious edge glow ───────────────────────────────────────────
  {
    selector: 'edge[suspicious]',
    style: {
      // shadow not supported on edges in cytoscape, use higher opacity
      'opacity': 0.85,
    }
  },
  {
    selector: 'edge:selected',
    style: {
      'opacity': 1,
      'width': 4,
      'line-color': '#ffffff',
      'target-arrow-color': '#ffffff',
    }
  },
];

/* ── Layout Config ─────────────────────────────────────────────────────── */
// Tuned for organic web-like topology, NOT grid patterns

export const layoutConfig = {
  name: 'fcose',
  quality: 'proof',           // highest quality
  randomize: false,           // we pre-position by cluster
  animate: true,
  animationDuration: 1200,
  animationEasing: 'ease-out-quint',
  fit: true,
  padding: 80,
  nodeDimensionsIncludeLabels: false,
  uniformNodeDimensions: false,
  packComponents: false,       // don't pack — let clusters breathe
  step: 'all',

  // ── Physics tuning for organic web ──
  idealEdgeLength: () => 220,            // long edges → spread
  edgeElasticity: () => 0.1,             // low elasticity → less pull
  nodeRepulsion: () => 8_000_000,        // extreme repulsion → no overlap
  gravity: 0.02,                         // very low gravity → spread out
  gravityRange: 10,
  gravityCompound: 1.0,
  gravityRangeCompound: 1.5,
  numIter: 5000,                         // more iterations → better convergence
  initialEnergyOnIncremental: 0.2,

  // Nesting
  nestingFactor: 0.1,
  tile: true,
  tilingPaddingVertical: 40,
  tilingPaddingHorizontal: 40,
};
