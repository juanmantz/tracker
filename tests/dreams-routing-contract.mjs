// Replay measured-hour publications through the actual deployed accounting code.
// Download authorized Worker modules privately; do not send test hours to Dreams.
// DREAMS_WORKER_DIR=/path node --test tests/dreams-routing-contract.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync,mkdtempSync,copyFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
const directory=process.env.DREAMS_WORKER_DIR;
if(!directory)throw Error('Set DREAMS_WORKER_DIR to privately downloaded deployment modules.');
const source=readFileSync(join(directory,process.env.DREAMS_WORKER_INDEX||'index.js'),'utf8');
assert.equal(createHash('sha256').update(source).digest('hex'),'0c9bd3db7fdba1177dd4a883ce7fcaae31be29a29280503d16f35a2f04efe44c','Review a changed Worker before updating this contract.');
const temporary=mkdtempSync(join(tmpdir(),'dreams-routing-'));
for(const name of ['auth.mjs','auth-ui.mjs'])copyFileSync(join(directory,name),join(temporary,name));
writeFileSync(join(temporary,'domain.mjs'),source.replace('import { WorkerEntrypoint } from "cloudflare:workers";','class WorkerEntrypoint {}')+'\nexport {createNode,applyCommands,applyDreamsTimeHourPolicy,timeCapacityDisplay,goalProgress};\n');
const domain=await import(pathToFileURL(join(temporary,'domain.mjs')));
test.after(()=>rmSync(temporary,{recursive:true,force:true}));
const period={kind:'Week',start:'2026-10-19',end:'2026-10-25'};
function fixture(roots=true){
 const node=(kind,id,fields={})=>({...domain.createNode(kind),id,name:id,fields:{...domain.createNode(kind).fields,...fields}});
 const edge=(id,source,target,relation,extra={})=>({id,source,target,relation,allocation:null,visible:false,display:{},revision:1,...extra});
 return {title:'Isolated automatic-hours test',revision:1,exchangeRates:[],nodes:[
  node('note','dreamstime-control',{notes:JSON.stringify({schema:'dreamstime/control/v1',sync_policy:{schema:'dreamstime/whole-hours/v1',minimum_hours:1,rounding:'floor',period:'Week'}})}),
  node('time','available',{meaning:'Available hours',amount:{value:40,unit:'hours'},period:'Week',basis:'Confirmed'}),
  ...['juan','studio','hey'].map(id=>node('project',id,{workPeriod:'Week',periodDate:period.start})),node('service','flank'),node('product','typefaces'),
  node('goal','hours',{goal:{value:20,unit:'hours'},measurement:'Worked hours',measurementBasis:'Worked',period:'Week',periodDate:period.start})
 ],edges:[edge('juan-budget','available','juan','Allocates',{allocation:34}),edge('studio-budget','available','studio','Allocates',{allocation:6}),
  edge('client-budget','available','flank','Allocates',{allocation:6,via:'juan'}),edge('hey-parent','hey','studio','Part of'),edge('type-parent','typefaces','studio','Part of'),
  ...['flank','hey',...(roots?['juan','studio']:[])].map(id=>edge(id+'-goal',id,'hours','Contributes to',{metric:'workedHours'}))]};
}
function record(id,hours,version=0){
 const digit={juan:'a',studio:'b',hey:'c',flank:'d',typefaces:'e'}[id];
 return {type:'record_measurement',id,measurement:{id:'dreamstime-'+digit.repeat(32),metric:'workedHours',amount:{value:hours,unit:'hours'},basis:'Worked',scope:'Own',period,
  source:'Dreams Time · isolated-fixture',observedAt:`2026-10-19T08:${String(version).padStart(2,'0')}:00Z`}};
}
const change=(s,c)=>domain.applyDreamsTimeHourPolicy(s,domain.applyCommands(s,c));
test('root and forwarded child hours reach parents and the weekly goal exactly once',()=>{
 const commands=[record('juan',1),record('studio',1),record('hey',1),record('flank',1)];
 assert.equal(domain.goalProgress(change(fixture(false),commands),'hours').value,2);
 const state=change(fixture(),commands);const capacity=id=>domain.timeCapacityDisplay(state.nodes.find(n=>n.id===id),state);
 assert.equal(capacity('juan').used,2);assert.equal(capacity('studio').used,2);
 const goal=domain.goalProgress(state,'hours');assert.equal(goal.value,4);assert.equal(new Set(goal.atoms.map(a=>a.id)).size,4);
 assert.equal(state.edges.find(e=>e.id==='juan-budget').allocation,34);assert.equal(state.edges.find(e=>e.id==='studio-budget').allocation,6);
});
test('new descendants contribute through the studio without needing another goal route',()=>{
 const state=change(fixture(),[record('typefaces',1)]);assert.equal(domain.goalProgress(state,'hours').value,1);
 assert.equal(domain.timeCapacityDisplay(state.nodes.find(n=>n.id==='studio'),state).used,1);
});
test('subhours stay out and bounded corrections replace stable weekly totals',()=>{
 const state=change(fixture(),[record('hey',1.8),record('flank',2.4)]);assert.equal(domain.goalProgress(state,'hours').value,3);
 const corrected=change(state,[record('hey',.9,1)]);assert.equal(domain.goalProgress(corrected,'hours').value,2);
 assert.equal(corrected.nodes.find(n=>n.id==='hey').measurements.length,0);
});
