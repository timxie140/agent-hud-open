"""Authenticated Dot's proactive messages to a fresh HUD-provided Codex inventory."""
import hashlib
import json
import re
import sys
import uuid
from urllib.parse import urlsplit

REGISTRY_TTL = 15
PLATFORM = {'darwin': 'macos', 'win32': 'windows'}.get(sys.platform, 'unsupported')


def migrate(db):
    db.execute('CREATE TABLE IF NOT EXISTS dot_sessions (singleton INTEGER PRIMARY KEY CHECK(singleton=1), '
               'enabled INTEGER NOT NULL, checked REAL NOT NULL, sessions TEXT NOT NULL, platform TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS dot_host (singleton INTEGER PRIMARY KEY CHECK(singleton=1), instance_id TEXT NOT NULL)')
    db.execute('INSERT OR IGNORE INTO dot_host(singleton,instance_id) VALUES(1,?)', ('hud-dot-' + PLATFORM + '-' + uuid.uuid4().hex,))
    columns = {row[1] for row in db.execute('PRAGMA table_info(messages)')}
    if 'origin' not in columns:
        db.execute("ALTER TABLE messages ADD COLUMN origin TEXT NOT NULL DEFAULT 'codex'")


def publish(adapter, params):
    """Only the local authenticated HUD controller may call this operation."""
    from hud_dot import Rejected, canonical
    enabled = params.get('enabled') is True
    platform = params.get('platform')
    if platform not in ('macos', 'windows') or platform != PLATFORM:
        raise Rejected('Unknown HUD host platform')
    rows = params.get('sessions', [])
    if not isinstance(rows, list) or len(rows) > 100:
        raise Rejected('Invalid Codex session inventory')
    safe, seen = [], set()
    for row in rows if enabled else []:
        if not isinstance(row, dict) or row.get('client') != 'codex':
            raise Rejected('Only existing Codex sessions may be published')
        identifier = row.get('id')
        try:
            if str(uuid.UUID(identifier)) != identifier.lower():
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise Rejected('Invalid Codex session identity')
        if identifier in seen:
            raise Rejected('Duplicate Codex session identity')
        seen.add(identifier)
        safe.append({'id': identifier, 'client': 'codex',
                     'title': str(row.get('title') or 'Codex')[:200],
                     'state': row.get('state') if row.get('state') in ('running', 'waiting', 'idle') else 'idle'})
    with adapter.db() as db:
        db.execute('INSERT INTO dot_sessions(singleton,enabled,checked,sessions,platform) VALUES(1,?,?,?,?) '
                   'ON CONFLICT(singleton) DO UPDATE SET enabled=excluded.enabled,checked=excluded.checked,sessions=excluded.sessions,platform=excluded.platform',
                   (int(enabled), adapter.clock(), canonical(safe), platform))
        if not enabled:
            # Revoke unclaimed proactive requests together with the inventory.
            # A claimed native mutation is never recalled or automatically retried.
            db.execute("UPDATE messages SET native_receipt=? WHERE origin='dot' "
                       "AND json_extract(native_receipt,'$.state')='pending_hud'",
                       (canonical({'state': 'refused', 'actualReceiptConfirmed': False,
                                   'reasonCode': 'permission_denied'}),))
    return {'published': len(safe), 'enabled': enabled}


def host_id(adapter):
    with adapter.db() as db:
        return db.execute('SELECT instance_id FROM dot_host WHERE singleton=1').fetchone()[0]


def session_id(value):
    from hud_dot import Rejected
    if isinstance(value, str) and value.startswith('codex:'):
        link = urlsplit(value)
        if (link.scheme != 'codex' or link.netloc != 'threads' or link.query or link.fragment
                or not link.path.startswith('/') or link.path.count('/') != 1):
            raise Rejected('Use an exact codex://threads/<session UUID> link')
        value = link.path[1:]
    try:
        identifier = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise Rejected('Use a session UUID or codex://threads/<session UUID> link')
    return identifier


def inventory(adapter):
    from hud_dot import Rejected
    adapter._subscription()
    with adapter.db() as db:
        row = db.execute('SELECT * FROM dot_sessions WHERE singleton=1').fetchone()
    if (not row or not row['enabled'] or not 0 <= adapter.clock() - row['checked'] <= REGISTRY_TTL):
        raise Rejected('HUD session inventory is unavailable or permission is off; do not guess a target')
    rows = json.loads(row['sessions'])
    for session in rows:
        session['url'] = 'codex://threads/' + session['id']
    return {'host': {'id':host_id(adapter), 'platform':row['platform'], 'label':'Mac' if row['platform'] == 'macos' else 'Windows'},
            'sessions': rows, 'deliveryPolicy': 'active Desktop steer; otherwise queued',
            'freshForSeconds': max(0, REGISTRY_TTL - (adapter.clock() - row['checked']))}


def message_id(request_id, host):
    from hud_dot import Rejected
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,96}', request_id):
        raise Rejected('Use one stable request_id (8-96 letters, digits, underscore or hyphen) per intended send')
    return 'm-dot-' + hashlib.sha256((host + ':' + request_id).encode()).hexdigest()[:32]


def send(adapter, target, text, request_id, host):
    from hud_dot import Rejected, canonical, native_reply
    if not isinstance(host, str) or host != host_id(adapter):
        raise Rejected('Wrong HUD host; use the host.id returned by this MCP entry')
    target = session_id(target)
    identifier = message_id(request_id, host)
    if not isinstance(text, str) or not text or len(text) > 32000:
        raise Rejected('Invalid message')
    source = 'codex:' + target
    with adapter.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM messages WHERE id=?', (identifier,)).fetchone()
        if row:
            if row['origin'] != 'dot' or row['source'] != source or row['text'] != text:
                raise Rejected('request_id already belongs to different content or recipient')
            # A duplicate is receipt-only, including after restart, refusal or timeout.
            return adapter.receipt(identifier)
        offered = inventory(adapter)['sessions']
        if not any(row['id'] == target for row in offered):
            raise Rejected('Choose an existing session returned by hud_list_sessions')
        db.execute('INSERT INTO messages(id,source,text,state,created,reply_id,reply_text,native_receipt,origin) '
                   'VALUES(?,?,?,?,?,?,?,?,?)',
                   (identifier, source, text, 'dot_initiated', adapter.clock(), identifier, text,
                    canonical(native_reply(source, identifier, identifier, text)), 'dot'))
    return adapter.wait_native(identifier)
