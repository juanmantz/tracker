// Patch the deployed Dreams asset module without changing accounting or auth.
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
const hash = text => createHash('sha256').update(text).digest('hex');
export const baselineAssetsHash = 'd721c36bacf88e3d5cce1f8dbe2a9ae9baf3da3c0fda5dace06997eb27042ce6';
export const testedBundleHash = '79adf43f2e6fca3ad2876c535c482fc80c55e33298a1a36813a7b8ba092f4785';
const source = readFileSync(new URL('./map-tracker-status.js', import.meta.url), 'utf8');
const replacements = [
  ['l.details.length?"Set contribution amounts":"Add contributors"',
   'l.details.length?(n.fields.measurement==="Worked hours"&&l.details.every(x=>x.status==="incompatible"&&x.message==="no saved value for the selected goal period.")?"Waiting for recorded hours":"Set contribution amounts"):"Add contributors"'],
  ['l.partial&&p.jsx("div",{className:"measurement-state",children:"Some contributions need an amount"})',
   'l.partial&&p.jsx("div",{className:"measurement-state",children:n.fields.measurement==="Worked hours"&&l.details.every(x=>x.status==="compatible"||x.message==="no saved value for the selected goal period.")?"Some projects have no completed hours this week":"Some contributions need an amount"})'],
  ['className:"header-tools",children:[', 'className:"header-tools",children:[p.jsx(DreamsTimeMapStatus,{state:m}),']
];
export function patchDreamsAssets(moduleSource) {
  if (hash(moduleSource) !== baselineAssetsHash) throw new Error('Dreams assets changed; review and merge the current deployment.');
  const assets = JSON.parse(moduleSource.replace(/^export default /,'').replace(/;\s*$/,''));
  const original = '/assets/index-62d771d64e71.js';
  let bundle = assets[original].body;
  for (const [before,after] of replacements) {
    if (bundle.split(before).length !== 2) throw new Error('Expected one UI anchor.');
    bundle = bundle.replace(before,after);
  }
  bundle = source + '\n' + bundle;
  if (hash(bundle) !== testedBundleHash) throw new Error('Bundle differs from the browser-tested deployment.');
  const destination = '/assets/index-' + testedBundleHash.slice(0,12) + '.js';
  assets[destination] = {...assets[original], body:bundle, hash:testedBundleHash};
  assets['/index.html'].body = assets['/index.html'].body.replace(original,destination);
  assets['/index.html'].hash = hash(assets['/index.html'].body);
  // Keep the previous immutable URL valid for already-open browser tabs.
  return 'export default ' + JSON.stringify(assets) + ';\n';
}
