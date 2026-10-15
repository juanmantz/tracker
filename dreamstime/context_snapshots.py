"""Small, local, deduplicated UI evidence. Never transcripts, pixels or input events."""
from __future__ import annotations
import hashlib
import json
import math
import re
import zlib

SCHEMA = 'dreamstime/context/v1'
MAX_CARD_BYTES = 512
MAX_COMPRESSED_BYTES = 1024 * 1024
MAX_CARDS = 2048
RETENTION_SECONDS = 7 * 86400
CALL_APPS = frozenset({'net.whatsapp.WhatsApp', 'com.whatsapp.WhatsApp',
    'us.zoom.xos', 'com.apple.FaceTime', 'com.microsoft.teams', 'com.microsoft.teams2',
    'com.tinyspeck.slackmacgap'})
KINDS = {'document', 'conversation', 'call', 'window'}
SCOPES = {'window_metadata', 'document_header', 'conversation_header', 'call_controls'}

def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def short_text(value, limit=96):
    if not isinstance(value, str):
        return ''
    value = ' '.join(value[:1024].split())
    value = re.sub(r'(?:https?://|file://|/Users/|/home/)\S+', '[document]', value)
    value = re.sub(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b', '[contact]', value)
    value = re.sub(r'\b(?:sk-[A-Za-z0-9_-]+|[A-Za-z0-9_-]{48,})\b', '[redacted]', value)
    return value.encode('utf-8')[:limit].decode('utf-8', errors='ignore')

def compact_card(value):
    if not isinstance(value, dict) or value.get('schema') != SCHEMA:
        return None
    kind, scope = value.get('kind'), value.get('scope')
    if kind not in KINDS or scope not in SCOPES:
        return None
    labels = []
    supplied = value.get('labels')
    for label in supplied[:12] if isinstance(supplied, list) else []:
        label = short_text(label, 80)
        if label and label.casefold() not in {x.casefold() for x in labels}:
            labels.append(label)
        if len(labels) == 4:
            break
    if not labels and kind != 'call':
        return None
    result = {'kind': kind, 'scope': scope, 'source': 'accessibility', 'labels': labels}
    if kind == 'call':
        result['state'] = 'connected' if value.get('state') == 'connected' else 'uncertain'
    while len(encoded(result)) > MAX_CARD_BYTES and result['labels']:
        result['labels'].pop()
    return result

def verified_call(sample):
    session, observed, ts = sample.get('call_session'), sample.get('call_verified_at'), sample.get('ts')
    return (sample.get('app') in CALL_APPS and sample.get('call_active') is True
            and sample.get('call_proof') == 'end-control+duration'
            and sample.get('ax_trusted') is True
            and sample.get('window_access_status') == 'readable'
            and isinstance(session, str) and re.fullmatch(r'[a-f0-9-]{36}', session) is not None
            and isinstance(observed, (int, float)) and not isinstance(observed, bool)
            and isinstance(ts, (int, float)) and math.isfinite(observed)
            and 0 <= ts - observed <= 4)

class ContextSnapshots:
    def __init__(self, db, *, max_bytes=MAX_COMPRESSED_BYTES, max_cards=MAX_CARDS):
        self.db = db
        self.max_bytes = min(MAX_COMPRESSED_BYTES, max(512, max_bytes))
        self.max_cards = min(MAX_CARDS, max(1, max_cards))
        self.last_prune = 0
        db.executescript("""
            CREATE TABLE IF NOT EXISTS context_snapshots(
                id TEXT PRIMARY KEY, payload BLOB NOT NULL,
                first_seen REAL NOT NULL, last_seen REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS snapshot_age ON context_snapshots(last_seen);
        """)

    def put(self, value, now):
        card = compact_card(value)
        if not card:
            return None
        data = encoded(card)
        key = hashlib.sha256(data).hexdigest()
        with self.db:
            previous = self.db.execute('SELECT last_seen FROM context_snapshots WHERE id=?', (key,)).fetchone()
            if previous is None:
                self.db.execute('INSERT INTO context_snapshots VALUES(?,?,?,?)',
                                (key, zlib.compress(data, 9), now, now))
            elif now - previous[0] >= 60:
                self.db.execute('UPDATE context_snapshots SET last_seen=? WHERE id=?', (now, key))
            if previous is None or now - self.last_prune >= 60:
                self.prune(now)
        return key

    def prune(self, now):
        self.db.execute('DELETE FROM context_snapshots WHERE last_seen<?', (now - RETENTION_SECONDS,))
        rows = self.db.execute('SELECT id,length(payload)+64 AS size FROM context_snapshots ORDER BY last_seen DESC,id').fetchall()
        total = 0
        for index, row in enumerate(rows):
            if index >= self.max_cards or total + row['size'] > self.max_bytes:
                self.db.execute('DELETE FROM context_snapshots WHERE id=?', (row['id'],))
            else:
                total += row['size']
        self.last_prune = now

    def get(self, key):
        if not isinstance(key, str):
            return None
        row = self.db.execute('SELECT payload FROM context_snapshots WHERE id=?', (key,)).fetchone()
        if not row:
            return None
        try:
            data = zlib.decompressobj().decompress(row[0], MAX_CARD_BYTES + 1)
            return json.loads(data) if len(data) <= MAX_CARD_BYTES else None
        except (ValueError, zlib.error, UnicodeError):
            return None

    def stats(self, now):
        with self.db:
            self.prune(now)
        row = self.db.execute('SELECT count(*) AS count,coalesce(sum(length(payload)+64),0) AS bytes FROM context_snapshots').fetchone()
        return {'cards': row['count'], 'compressed_bytes': row['bytes'],
                'limit_bytes': self.max_bytes, 'retention_days': 7,
                'card_limit_bytes': MAX_CARD_BYTES, 'images_stored': False}
