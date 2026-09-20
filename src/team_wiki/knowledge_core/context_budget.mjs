// Adapted from nashsu/llm_wiki@e8082119 src/lib/context-budget.ts (GPLv3).
// Pure computation only; no desktop/runtime dependencies.
const DEFAULT_MAX_CTX = 204800;
const RESPONSE_RESERVE_FRAC = 0.15;
const INDEX_BUDGET_FRAC = 0.05;
const PAGE_BUDGET_FRAC = 0.5;
const PER_PAGE_FRAC = 0.3;
const PER_PAGE_FLOOR = 5000;

export function computeContextBudget(maxContextSize) {
  const maxCtx = typeof maxContextSize === "number" && maxContextSize > 0
    ? maxContextSize : DEFAULT_MAX_CTX;
  const responseReserve = Math.floor(maxCtx * RESPONSE_RESERVE_FRAC);
  const indexBudget = Math.floor(maxCtx * INDEX_BUDGET_FRAC);
  const pageBudget = Math.floor(maxCtx * PAGE_BUDGET_FRAC);
  const maxPageSize = Math.min(
    pageBudget,
    Math.max(PER_PAGE_FLOOR, Math.floor(pageBudget * PER_PAGE_FRAC)),
  );
  return {maxCtx, responseReserve, indexBudget, pageBudget, maxPageSize, unit: "characters"};
}
