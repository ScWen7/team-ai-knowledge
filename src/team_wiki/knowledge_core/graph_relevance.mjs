// Adapted from nashsu/llm_wiki@e8082119 src/lib/graph-relevance.ts (GPLv3).
// Filesystem, basename identity, UI types and module-level cache are intentionally removed.
const WEIGHTS = { directLink: 3.0, sourceOverlap: 4.0, commonNeighbor: 1.5, typeAffinity: 1.0 };

const TYPE_AFFINITY = {
  rule: { rule: 0.8, guide: 1.2, analysis: 1.0, concept: 1.0, decision: 1.0 },
  guide: { rule: 1.2, guide: 0.8, analysis: 1.0, concept: 1.0, pitfall: 1.2 },
  concept: { rule: 1.0, guide: 1.0, analysis: 1.2, concept: 0.8, process: 1.0 },
  decision: { rule: 1.0, guide: 1.0, analysis: 1.2, decision: 0.8 },
  pitfall: { guide: 1.2, rule: 1.0, pitfall: 0.8, analysis: 1.0 },
  process: { rule: 1.0, guide: 1.0, process: 0.8, concept: 1.0 },
  analysis: { rule: 1.0, guide: 1.0, concept: 1.2, decision: 1.2, analysis: 0.8 },
};

function neighbors(node) {
  return new Set([...(node.outLinks || []), ...(node.inLinks || [])]);
}
function degree(node) { return (node.outLinks || []).length + (node.inLinks || []).length; }

export function calculateRelevance(a, b, nodesById) {
  if (a.id === b.id) return 0;
  const forward = (a.outLinks || []).includes(b.id) ? 1 : 0;
  const backward = (b.outLinks || []).includes(a.id) ? 1 : 0;
  const direct = (forward + backward) * WEIGHTS.directLink;

  const sourcesA = new Set(a.sources || []);
  let shared = 0;
  for (const src of (b.sources || [])) if (sourcesA.has(src)) shared += 1;
  const sourceOverlap = shared * WEIGHTS.sourceOverlap;

  const na = neighbors(a); const nb = neighbors(b);
  let aa = 0;
  for (const id of na) {
    if (!nb.has(id)) continue;
    const n = nodesById.get(id);
    if (!n) continue;
    aa += 1 / Math.log(Math.max(degree(n), 2));
  }
  const commonNeighbor = aa * WEIGHTS.commonNeighbor;
  const affinity = (TYPE_AFFINITY[a.type]?.[b.type] ?? 0.5) * WEIGHTS.typeAffinity;
  return direct + sourceOverlap + commonNeighbor + affinity;
}

export function getRelatedNodes(nodeId, nodes, limit = 5) {
  const map = new Map(nodes.map(n => [n.id, n]));
  const source = map.get(nodeId);
  if (!source) return [];
  return nodes
    .filter(n => n.id !== nodeId)
    .map(n => ({node: n, relevance: calculateRelevance(source, n, map)}))
    .filter(x => x.relevance > 0)
    .sort((a, b) => b.relevance - a.relevance)
    .slice(0, limit);
}
