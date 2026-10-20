// Device summaries are evidence only. Never render activity titles or follow links.
function dreamsTimeMapStatus(state, now = Date.now() / 1000) {
  const reports = (state.nodes || []).flatMap(node => {
    if (node.kind !== 'note' || typeof node.fields?.notes !== 'string' || node.fields.notes.length > 20000) return [];
    try {
      const report = JSON.parse(node.fields.notes);
      return report?.schema === 'dreamstime/review/v1' && typeof report.device === 'string' &&
        Number.isFinite(report.updated_at) && report.updated_at <= now + 300 ? [report] : [];
    } catch { return []; }
  });
  const latest = new Map();
  for (const report of reports) if (!latest.has(report.device) || latest.get(report.device).updated_at < report.updated_at) latest.set(report.device, report);
  if (!latest.size) return null;
  const devices = [...latest.values()];
  const at = Math.max(...devices.map(d => d.updated_at));
  const fresh = devices.filter(d => now - d.updated_at <= 3600);
  const finiteSeconds = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
  const totals = devices.map(d => {
    const source = d.publication && typeof d.publication === 'object' ? d.publication : d.last_save;
    return {device:d.device, at:source?.at, week:source?.week, assigned:finiteSeconds(source?.seconds), unassigned:finiteSeconds(source?.unassigned_seconds)};
  });
  const latestWeek = totals.map(t => t.week).filter(w => /^\d{4}-\d{2}-\d{2}$/.test(w || '')).sort().at(-1);
  const known = totals.filter(t => t.week === latestWeek && t.assigned !== null && t.unassigned !== null);
  const assigned = known.reduce((s,t) => s+t.assigned,0), unassigned = known.reduce((s,t) => s+t.unassigned,0);
  const total = assigned + unassigned;
  const recentDenied = fresh.some(d => d.sensor?.collector?.ax_trusted === false && d.sensor?.accessibility !== true);
  const failed = fresh.some(d => typeof d.sync_error === 'string' && d.sync_error.length > 0);
  const paused = fresh.length > 0 && fresh.every(d => d.paused === true);
  const matched = total > 0 ? Math.floor(100*assigned/total) : null;
  const label = !fresh.length ? 'Last report received' : recentDenied ? 'Project detection needs access' : failed ? 'Transfer needs attention' : paused ? 'Paused' : total > 0 && unassigned > assigned ? 'Most activity has no project' : 'Activity report received';
  const published = (state.nodes || []).filter(n => !n.archived).flatMap(n => (n.measurements || []).filter(m =>
    m.metric === 'workedHours' && m.basis === 'Worked' && /^Dreams Time · /.test(m.source || '') &&
    m.period?.start === latestWeek && m.amount?.unit === 'hours' && Number.isInteger(m.amount.value) && m.amount.value >= 1));
  return {label, at, assigned, unassigned, matched, week:latestWeek, totalsAt:Math.min(...known.map(t=>Number.isFinite(t.at)?t.at:at)), published:published.reduce((s,m)=>s+m.amount.value,0), hasTotals:known.length>0,
    partial:devices.some(d => Number(d.omitted_groups)>0), fresh:!!fresh.length,
    access:fresh.length && fresh.every(d => d.sensor?.accessibility === true) ? 'Document access enabled' : null};
}
function dreamsTimeDuration(seconds) {
  const minutes = Math.floor(seconds/60);
  return minutes >= 60 ? `${Math.floor(minutes/60)}h ${minutes%60}m` : `${minutes}m`;
}
function DreamsTimeMapStatus({state}) {
  const status = dreamsTimeMapStatus(state);
  if (!status) return null;
  const muted = {fontSize:12,color:'var(--muted, #aaa)',margin:'6px 0',lineHeight:1.5};
  return p.jsxs('details', {className:'dreamstime-map-status',style:{position:'relative',maxWidth:280},children:[
    p.jsx('summary',{style:{cursor:'pointer',fontSize:12,padding:'7px 10px',border:'1px solid #68604e',borderRadius:8,color:'#e8c999'},children:status.label==='Most activity has no project'&&status.hasTotals?`Dreams Time · ${status.matched}% matched · ${dreamsTimeDuration(status.unassigned)} unassigned`:`Dreams Time · ${status.label}`}),
    p.jsxs('div',{style:{position:'absolute',right:0,top:'calc(100% + 8px)',zIndex:1000,width:320,maxWidth:'80vw',padding:16,border:'1px solid #555',borderRadius:12,background:'#292929',boxShadow:'0 8px 32px #0008'},children:[
      p.jsx('strong',{children:status.label}),
      status.hasTotals && p.jsxs(p.Fragment,{children:[
        p.jsx('p',{style:muted,children:`${dreamsTimeDuration(status.assigned)} matched to projects · ${status.matched}% of recorded activity.`}),
        p.jsx('p',{style:muted,children:`${dreamsTimeDuration(status.unassigned)} unassigned activity. This is not counted as project work.`}),
        p.jsx('p',{style:muted,children:`${status.published} completed hours saved to projects for the week of ${status.week}.`})
      ]}),
      p.jsx('p',{style:muted,children:'Each project publishes completed whole hours only. Partial time stays on your Mac.'}),
      status.access && p.jsx('p',{style:muted,children:status.access+'; project recognition is assessed separately.'}),
      status.partial && p.jsx('p',{style:muted,children:'The review report covers part of the recorded activity. Ambiguous time remains unassigned.'}),
      p.jsx('p',{style:muted,children:'Last device report: '+new Date(status.at*1000).toLocaleString()}),
      status.hasTotals && p.jsx('p',{style:muted,children:'Totals last calculated: '+new Date(status.totalsAt*1000).toLocaleString()})
    ]})
  ]});
}
