/** Server-side compatibility policy for already-installed Dreams Time clients.
 * Precise activity remains in the Mac database; Dreams receives completed hours.
 * Opt-in is per map, through the existing private control note.
 */
export function applyDreamsTimeHourPolicy(before, next) {
  const note = next.nodes.find(n => n.id === 'dreamstime-control' && n.kind === 'note');
  let control;
  try { control = JSON.parse(note?.fields?.notes || '{}'); } catch { return next; }
  if (control.schema !== 'dreamstime/control/v1' ||
      control.sync_policy?.schema !== 'dreamstime/whole-hours/v1') return next;

  const tracked = m => /^dreamstime-[a-f0-9]{32}$/.test(m.id) &&
    /^Dreams Time · .+/.test(m.source || '') && m.metric === 'workedHours' &&
    m.basis === 'Worked' && m.scope === 'Own' && m.amount.unit === 'hours' &&
    typeof m.amount.value === 'number' && Number.isFinite(m.amount.value);
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  for (const node of next.nodes) {
    const previous = before.nodes.find(n => n.id === node.id);
    const measurements = [];
    for (const item of node.measurements || []) {
      if (!tracked(item)) { measurements.push(item); continue; }
      // Never round unworked time up. A correction below one hour removes the
      // published snapshot, while the tracker retains all underlying seconds.
      const hours = Math.floor(item.amount.value);
      if (hours < 1) continue;
      const measurement = { ...item, amount: { ...item.amount, value: hours } };
      const start = new Date(item.period.start + 'T12:00:00Z');
      const end = new Date(start.getTime() + 6 * 86400000);
      if (item.period.kind === 'Custom' && Number.isFinite(start.getTime()) &&
          start.getUTCDay() === 1 && end.toISOString().slice(0, 10) === item.period.end) {
        measurement.period = { ...item.period, kind: 'Week' };
      }
      const old = previous?.measurements?.find(m => m.id === item.id);
      // Older clients resend fractional snapshots every five minutes. Retain
      // the previous observation if its published value did not change.
      measurements.push(old && same({ ...measurement, observedAt: old.observedAt }, old)
        ? old : measurement);
    }
    if (!same(measurements, node.measurements || [])) {
      node.measurements = measurements;
      if (previous && node.revision === previous.revision) node.revision++;
    }
    if (previous && same({ ...node, revision: previous.revision }, previous))
      node.revision = previous.revision;
  }
  // Suppressed and unchanged snapshots must not create revisions/audit noise.
  return same({ ...next, revision: before.revision }, before) ? before : next;
}
