// Run against a private downloaded deployment, not a substitute accounting model:
// DREAMS_WORKER_DIR=/path/to/modules node --test tests/dreams-worker-integration.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, writeFileSync, mkdtempSync, cpSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {patchWorker} from '../integrations/dreams/patch-worker.mjs';

const directory = process.env.DREAMS_WORKER_DIR;
if (!directory) throw new Error('Set DREAMS_WORKER_DIR to the verified deployment modules.');
const temporary = mkdtempSync(join(tmpdir(), 'dreams-policy-'));
cpSync(directory, temporary, {recursive: true});
const source = patchWorker(readFileSync(join(directory, 'index.js'), 'utf8'));
// The SDK entrypoint is not exercised by domain/storage tests. All accounting,
// validation, period selection and storage orchestration remain deployed code.
writeFileSync(join(temporary, 'test-domain.js'), source.replace(
  'import { WorkerEntrypoint } from "cloudflare:workers";', 'class WorkerEntrypoint {}') +
  '\nexport {applyCommands, createNode, timeCapacityDisplay, recordedWorkedHours, goalProgress, execute, applyDreamsTimeHourPolicy};');
const d = await import(pathToFileURL(join(temporary, 'test-domain.js')));
test.after(() => rmSync(temporary, {recursive: true, force: true}));
function fixture() {
  const node = (kind, id, fields={}) => ({...d.createNode(kind), id, name:id, fields:{...d.createNode(kind).fields,...fields}});
  return {title:'Test map', revision:1, exchangeRates:[], nodes:[
    node('note','dreamstime-control',{notes:JSON.stringify({schema:'dreamstime/control/v1',sync_policy:{schema:'dreamstime/whole-hours/v1'}})}),
    node('project','juan',{workPeriod:'Week',periodDate:'2026-10-13'}),
    node('project','studio',{workPeriod:'Week',periodDate:'2026-10-13'}),
    node('project','hey',{workPeriod:'Week',periodDate:'2026-10-13'}),
    node('service','client'),
    node('goal','goal',{goal:{value:20,unit:'hours'},measurement:'Worked hours',measurementBasis:'Worked',period:'Week',periodDate:'2026-10-13'}),
  ],edges:[
    {id:'hey-studio',source:'hey',target:'studio',relation:'Part of',allocation:null,revision:1},
    {id:'client-juan',source:'client',target:'juan',relation:'Part of',allocation:null,revision:1},
    ...['client','hey'].map(id=>({id:id+'-goal',source:id,target:'goal',relation:'Contributes to',metric:'workedHours',contribution:{mode:'Percentage',percentage:100},allocation:null,revision:1})),
  ]};
}
function command(id,hours,observedAt='2026-10-13T11:00:00Z') {
  return {type:'record_measurement',id,measurement:{id:'dreamstime-'+(id==='hey'?'a':'b').repeat(32),metric:'workedHours',amount:{value:hours,unit:'hours'},basis:'Worked',scope:'Own',source:'Dreams Time · fixture',period:{kind:'Custom',start:'2026-10-12',end:'2026-10-18'},observedAt}};
}
function change(before,commands) {return d.applyDreamsTimeHourPolicy(before,d.applyCommands(before,commands));}
test('legacy 0.7 clients feed weekly parent totals and the goal without duplicate hours',()=>{
  const state=change(fixture(),[command('hey',2.5),command('client',3.8)]);
  const capacity=id=>d.timeCapacityDisplay(state.nodes.find(n=>n.id===id),state);
  assert.equal(capacity('studio').used,2);
  assert.equal(capacity('juan').used,3);
  assert.equal(capacity('hey').used,2);
  assert.equal(d.goalProgress(state,'goal').value,5);
  const corrected=change(state,[command('hey',0.9,'2026-10-13T12:00:00Z')]);
  assert.equal(d.timeCapacityDisplay(corrected.nodes.find(n=>n.id==='studio'),corrected).used,null);
  assert.equal(d.goalProgress(corrected,'goal').value,3);
});
test('stale snapshots still fail before policy can remove a newer hour record',()=>{
  const state=change(fixture(),[command('hey',2.5)]);
  assert.throws(()=>change(state,[command('hey',0.1,'2026-10-13T10:00:00Z')]),/newer snapshot/);
});
test('invalid input still goes through the original Dreams validator',()=>{
  for(const hours of [-1,Infinity,NaN]) assert.throws(()=>change(fixture(),[command('hey',hours)]));
});
test('parent and child paths do not duplicate their recorded hours',()=>{
  const state=fixture();
  state.edges.push({id:'studio-goal',source:'studio',target:'goal',relation:'Contributes to',metric:'workedHours',contribution:{mode:'Percentage',percentage:100},allocation:null,revision:1});
  assert.equal(d.goalProgress(change(state,[command('hey',2.5)]),'goal').value,2);
});
test('the real storage entrypoint accepts subhour sync without any database writes',async()=>{
  const state=fixture(); let writes=0;
  const row=n=>({...n,fields:JSON.stringify(n.fields),visible:JSON.stringify(n.visible),position:JSON.stringify(n.position),checklist:JSON.stringify(n.checklist),measurement_records:JSON.stringify(n.measurements),activities:JSON.stringify(n.activities),archived:0});
  const rows=e=>({...e,display:JSON.stringify(e.display||{}),contribution:e.contribution?JSON.stringify(e.contribution):null,visible:0});
  const map={title:state.title,revision:state.revision,exchange_rates:'[]',viewport:null};
  const DB={prepare(sql){return {sql,bind(){return this},async first(){return sql.includes('changes')?null:map},async run(){writes++}}},async batch(statements){
    if(statements.every(s=>s.sql.startsWith('SELECT')))return [{results:[map]},{results:state.nodes.map(row)},{results:state.edges.map(rows)}];
    writes++;throw new Error('Unexpected write for suppressed time');
  }};
  const result=await d.execute({DB},'owner',[command('hey',0.75)],1,'test-noop');
  assert.equal(result.revision,1); assert.equal(writes,0);
  await assert.rejects(d.execute({DB},'owner',[command('hey',0.75)],0,'stale'),/map changed/);
});
