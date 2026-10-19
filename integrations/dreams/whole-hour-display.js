// A zero here means zero completed hours published, never zero activity worked.
// Keep missing/failed transfers unknown; do not create measurement records.
function dreamsTimeTrackingDay(state, now = new Date()) {
  const reports = (state.nodes || []).flatMap(n => {
    if (n.kind !== 'note' || typeof n.fields?.notes !== 'string' || n.fields.notes.length > 20000) return [];
    try { const r=JSON.parse(n.fields.notes); return r.schema === 'dreamstime/review/v1' &&
      Number.isFinite(r.updated_at) && typeof r.timezone === 'string' && r.timezone.length <= 64 ? [r] : []; } catch { return []; }
  }).sort((a,b)=>b.updated_at-a.updated_at);
  for (const r of reports) {
    try {
      const parts = new Intl.DateTimeFormat('en-CA',{timeZone:r.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now);
      const get=type=>parts.find(p=>p.type===type)?.value;
      return get('year')+'-'+get('month')+'-'+get('day');
    } catch { /* An invalid device zone must not break the map. */ }
  }
  return now.toISOString().slice(0,10);
}
function dreamsTimeWorkPeriods(state) {
  const day = dreamsTimeTrackingDay(state);
  return {...state,nodes:state.nodes.map(n=>n.kind==='goal' && n.fields.measurement==='Worked hours' && !n.fields.periodDate
    ? {...n,fields:{...n.fields,periodDate:day}} : n)};
}
function dreamsTimeWaitingForWholeHour(state, period) {
  if (!period || period.kind !== 'Week') return false;
  const records = (state.nodes || []).flatMap(n => {
    if (n.kind !== 'note' || typeof n.fields?.notes !== 'string' || n.fields.notes.length > 20000) return [];
    try { return [JSON.parse(n.fields.notes)]; } catch { return []; }
  });
  const policy = records.find(r => r.schema === 'dreamstime/control/v1')?.sync_policy;
  if (policy?.schema !== 'dreamstime/whole-hours/v1' || policy.minimum_hours !== 1 || policy.rounding !== 'floor' || policy.period !== 'Week') return false;
  const devices = new Map();
  for (const r of records.filter(r => r.schema === 'dreamstime/review/v1' && typeof r.device === 'string' && Number.isFinite(r.updated_at))) {
    if (!devices.has(r.device) || r.updated_at > devices.get(r.device).updated_at) devices.set(r.device, r);
  }
  return devices.size > 0 && [...devices.values()].every(r => {
    const p = r.publication;
    if (r.sync_error || p?.week !== period.start || !Number.isInteger(p.published_hours) || p.published_hours < 0) return false;
    const waiting = ['waiting_for_hour', 'unassigned'].includes(p.state) && p.published_hours === 0 &&
      typeof p.seconds === 'number' && Number.isFinite(p.seconds) && p.seconds >= 0 && p.seconds < 3600;
    const verified = p.state === 'verified' && p.verification === 'dreamstime/published/v1';
    const saved = (state.nodes || []).filter(n => !n.archived).flatMap(n => n.measurements || [])
      .filter(m => m.metric === 'workedHours' && m.basis === 'Worked' && m.scope === 'Own' &&
        m.source === 'Dreams Time · '+r.device && m.period?.start === period.start &&
        ['Week', 'Custom'].includes(m.period.kind));
    return (waiting || verified) && saved.every(m => m.amount?.unit === 'hours' && Number.isInteger(m.amount.value) && m.amount.value >= 1) &&
      saved.reduce((sum,m) => sum+m.amount.value,0) === p.published_hours;
  });
}
function dreamsTimeDisplayCapacity(node, state, result) {
  return result.used == null && result.hasCapacity && dreamsTimeWaitingForWholeHour(state, result.workPeriod)
    ? {...result, used:0, usedDots:0, over:0, awaitingWholeHour:true} : result;
}
function dreamsTimeDisplayGoal(node, state, result) {
  return node.fields.measurement === 'Worked hours' && result.value == null && dreamsTimeWaitingForWholeHour(state, result.period)
    ? {...result, value:0, percentage:0, partial:true, over:null, withinLimit:null, awaitingWholeHour:true} : result;
}
