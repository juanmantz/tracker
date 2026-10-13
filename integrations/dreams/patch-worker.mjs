import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

export const baselineHash = '28b89b063a388d45c47ffb56db90644ff466d2bcdf19b03ad7da4b536c24034c';
export const anchor = '  const next = applyCommands(before, commands);';
export const replacement = '  const next = applyDreamsTimeHourPolicy(before, applyCommands(before, commands));\n  if (next === before) return before;';
export const policy = readFileSync(new URL('./whole-hour-policy.mjs', import.meta.url), 'utf8')
  .replace('export function ', 'function ');

export function patchWorker(source) {
  if (createHash('sha256').update(source).digest('hex') !== baselineHash)
    throw new Error('Dreams Worker changed: review the new source before applying this patch.');
  if (source.split(anchor).length !== 2) throw new Error('Expected exactly one storage hook.');
  return source.replace(anchor, replacement) + '\n' + policy;
}
