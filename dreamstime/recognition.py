"""Explainable local project matching. Conversation text suggests; explicit identity assigns."""
import re
import unicodedata
from urllib.parse import unquote, urlsplit

WORK_KINDS = {'project', 'product', 'service', 'content', 'personal', 'inbound', 'outbound'}
GENERIC = {'app','apps','client','clients','design','project','projects','work','studio','chatgpt','figma','new tab','untitled'}


def normalize(text):
    text = ''.join(c for c in unicodedata.normalize('NFKD', str(text)).casefold() if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[a-z0-9]+', text))


def strong_name(name):
    normalized = normalize(name)
    return len(normalized) >= 5 and normalized not in GENERIC


def recognize(context, catalog, explicit=None, snippets=None):
    if context.get('excluded'):
        return {'project': None, 'confidence': 'none', 'reason': 'Excluded activity', 'candidates': []}
    if explicit:
        return {'project': explicit['project'], 'confidence': 'confirmed', 'reason': explicit['reason'], 'candidates': []}
    ident = context.get('identity', '')
    exact = [p for p in catalog if ident and ident in p.get('identities', [])]
    if len(exact) == 1:
        return {'project': exact[0]['id'], 'confidence': 'high', 'reason': 'File linked in Dreams', 'candidates': []}
    if len(exact) > 1:
        return {'project': None, 'confidence': 'ambiguous', 'reason': 'This file is linked to more than one project', 'candidates': [{'project':p['id'],'name':p['name'],'evidence':'Linked file'} for p in exact]}
    document = context.get('document', '')
    path = unquote(urlsplit(document).path) if document else ''
    title = normalize(context.get('title', '') + ' ' + path)
    matches = []
    for p in catalog:
        aliases = [p['name'], *p.get('aliases', [])]
        found = [normalize(a) for a in aliases if strong_name(a) and (' '+normalize(a)+' ') in (' '+title+' ')]
        if found:
            matches.append({'project':p['id'],'name':p['name'],'evidence':'Project name in document', 'alias':max(found,key=len)})
    # An exact narrower name (Atlas identity) wins over its broad prefix (Atlas).
    matches = [m for m in matches if not any(m['project'] != other['project'] and m['alias'] != other['alias'] and (' '+m['alias']+' ') in (' '+other['alias']+' ') for other in matches)]
    if len(matches) == 1:
        return {'project':matches[0]['project'],'confidence':'high','reason':'Project name in document','candidates':[]}
    if len(matches) > 1:
        return {'project':None,'confidence':'ambiguous','reason':'More than one project mentioned','candidates':matches}
    # Accessibility text can contain sidebar content, so never silently assign from it.
    hinted = {x.get('project') for x in context.get('project_hints', []) if isinstance(x,dict)}
    text = normalize(' '.join(snippets or []))
    candidates = []
    for p in catalog:
        aliases = [p['name'], *p.get('aliases', [])]
        if p['id'] in hinted or any(strong_name(a) and (' '+normalize(a)+' ') in (' '+text+' ') for a in aliases):
            candidates.append({'project':p['id'],'name':p['name'],'evidence':'Mentioned in conversation context'})
    return {'project':None,'confidence':'suggested' if candidates else 'none','reason':'Check the conversation match' if candidates else 'No project evidence yet','candidates':candidates}
