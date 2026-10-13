import test from 'node:test';
import assert from 'node:assert/strict';
import { applyDreamsTimeHourPolicy as apply } from '../integrations/dreams/whole-hour-policy.mjs';

const measurement = (hours, changes = {}) => ({
  id: 'dreamstime-' + 'a'.repeat(32), metric: 'workedHours',
  amount: { value: hours, unit: 'hours' }, basis: 'Worked', scope: 'Own',
  period: { kind: 'Custom', start: '2026-10-12', end: '2026-10-18' },
  observedAt: '2026-10-13T11:00:00Z', source: 'Dreams Time · mac', ...changes,
});
const state = (measurements = []) => ({revision: 1, edges: [], nodes: [
  {id: 'dreamstime-control', kind: 'note', revision: 1, fields: {notes: JSON.stringify({
    schema: 'dreamstime/control/v1', sync_policy: {schema: 'dreamstime/whole-hours/v1'},
  })}},
  {id: 'project', revision: 1, measurements},
]});
const publish = (before, item) => {
  const next = structuredClone(before); next.revision++;
  next.nodes[1].measurements = [item]; next.nodes[1].revision++;
  return apply(before, next);
};
for (const hours of [0, 0.002777, 0.75, 0.999999]) {
  test(`${hours} hours produces no visible record or map revision`, () => {
    const before = state(); assert.equal(publish(before, measurement(hours)), before);
  });
}
for (const [input, expected] of [[1, 1], [1.333333, 1], [1.999999, 1], [2, 2], [34.6, 34]]) {
  test(`${input} hours publishes ${expected} completed hours with the weekly period`, () => {
    const after = publish(state(), measurement(input));
    assert.equal(after.nodes[1].measurements[0].amount.value, expected);
    assert.equal(after.nodes[1].measurements[0].period.kind, 'Week');
  });
}
test('minutes accumulate across repeated syncs without revision noise', () => {
  const first = publish(state(), measurement(1.1));
  assert.equal(publish(first, measurement(1.9, {observedAt: '2026-10-13T12:00:00Z'})), first);
  const second = publish(first, measurement(2.1));
  assert.equal(second.nodes[1].measurements[0].amount.value, 2);
});
test('reassignment below one hour removes an earlier published snapshot', () => {
  const first = publish(state(), measurement(2.1));
  const after = publish(first, measurement(0.5));
  assert.deepEqual(after.nodes[1].measurements, []);
  assert.equal(after.revision, first.revision + 1);
});
test('fractional measurements already in Dreams are cleaned when policy is enabled', () => {
  const before = state([measurement(0.002777)]);
  const after = apply(before, structuredClone(before));
  assert.equal(after.nodes[1].measurements.length, 0);
  assert.equal(after.nodes[1].revision, before.nodes[1].revision + 1);
});
test('manual history, estimated hours and other-device sources remain untouched', () => {
  for (const changes of [{source: 'Manual edit'}, {basis: 'Estimated'}, {id: 'manual'},
    {scope: 'Includes children'}, {metric: 'income', amount: {value: 0.5, unit: 'EUR'}}]) {
    const item = measurement(0.5, changes);
    assert.deepEqual(publish(state(), item).nodes[1].measurements, [item]);
  }
});
test('maps without the explicit policy remain unchanged', () => {
  for (const notes of ['{}', 'invalid JSON', JSON.stringify({sync_policy: {schema: 'dreamstime/whole-hours/v1'}})]) {
    const before = state(); before.nodes[0].fields.notes = notes;
    const item = measurement(0.5);
    assert.deepEqual(publish(before, item).nodes[1].measurements, [item]);
  }
});
test('only complete Monday–Sunday custom periods are converted to Week', () => {
  const item = measurement(2.5, {period: {kind: 'Custom', start: '2026-10-13', end: '2026-10-19'}});
  assert.equal(publish(state(), item).nodes[1].measurements[0].period.kind, 'Custom');
});
test('configuration or hierarchy changes are retained alongside suppressed snapshots', () => {
  const before = state(); const next = structuredClone(before); next.revision++;
  next.nodes[1].measurements = [measurement(0.5)];
  next.edges.push({source: 'child', target: 'studio', relation: 'Part of'});
  const after = apply(before, next);
  assert.equal(after.edges.length, 1); assert.equal(after.nodes[1].measurements.length, 0);
  assert.equal(after.revision, 2);
});
