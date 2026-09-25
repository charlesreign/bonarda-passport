// Bundle budgets (spec §7.8, NFR-1.3): the freelancer's /passport must load
// at most 150 KB of gzipped JS on a first visit. Follows the Vite manifest
// from the entry through each route's lazy chunk and everything it imports.
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";

const manifest = JSON.parse(readFileSync("dist/.vite/manifest.json", "utf8"));
const BUDGETS_KB = {
  "src/pages/Passport.tsx": 150,
  "src/pages/ProjectPage.tsx": 250,
  "src/pages/Ops.tsx": 250,
};

function closure(key, seen = new Set()) {
  if (seen.has(key)) return seen;
  seen.add(key);
  for (const dep of manifest[key]?.imports ?? []) closure(dep, seen);
  return seen;
}

const entry = Object.keys(manifest).find((key) => manifest[key].isEntry);
let failed = false;
for (const [route, budget] of Object.entries(BUDGETS_KB)) {
  const chunks = new Set([...closure(entry), ...closure(route)]);
  const bytes = [...chunks].reduce(
    (sum, key) => sum + gzipSync(readFileSync(`dist/${manifest[key].file}`)).length,
    0,
  );
  const kb = bytes / 1024;
  const ok = kb <= budget;
  failed ||= !ok;
  console.log(`${ok ? "ok  " : "FAIL"} ${route.padEnd(28)} ${kb.toFixed(1).padStart(6)} KB gzip (budget ${budget} KB)`);
}
process.exit(failed ? 1 : 0);
