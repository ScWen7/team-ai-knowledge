import fs from "node:fs";
import {computeContextBudget} from "./context_budget.mjs";
import {getRelatedNodes} from "./graph_relevance.mjs";

const [cmd] = process.argv.slice(2);
const input = JSON.parse(fs.readFileSync(0, "utf8") || "{}");
let result;
if (cmd === "budget") result = computeContextBudget(input.maxContextSize);
else if (cmd === "related") result = getRelatedNodes(input.nodeId, input.nodes || [], input.limit || 5);
else throw new Error(`unknown command: ${cmd}`);
process.stdout.write(JSON.stringify(result));
