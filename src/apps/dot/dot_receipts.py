"""Durable HUD return outbox and explicit recipient-confirmed delivery receipts."""
import json
import uuid


def migrate(db):
    columns = {row[1] for row in db.execute('PRAGMA table_info(messages)')}
    for name, declaration in [('recipient_confirmed', 'REAL'),
                              ('receipt_state', 'TEXT'), ('receipt_event_id', 'TEXT')]:
        if name not in columns:
            db.execute('ALTER TABLE messages ADD COLUMN ' + name + ' ' + declaration)


def pending(adapter):
    with adapter.db() as db:
        rows = db.execute("SELECT * FROM messages WHERE reply_id IS NOT NULL AND json_extract(native_receipt,'$.state')='pending_hud' ORDER BY created LIMIT 8").fetchall()
    return [{'id': row['id'], 'replyId': row['reply_id'], 'source': row['source'],
             'text': row['reply_text']} for row in rows
            if row['native_receipt'] and json.loads(row['native_receipt']).get('state') == 'pending_hud']


def claim(adapter, message_id):
    """Reserve before the native mutation. A crashed claim is never re-sent."""
    from hud_dot import canonical
    with adapter.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone()
        if not row or not row['native_receipt'] or json.loads(row['native_receipt']).get('state') != 'pending_hud':
            return {'claimed': False}
        db.execute('UPDATE messages SET native_receipt=? WHERE id=?',
                   (canonical({'state': 'reserved', 'actualReceiptConfirmed': False}), message_id))
    return {'claimed': True, 'id': row['id'], 'replyId': row['reply_id'],
            'source': row['source'], 'text': row['reply_text']}


def complete(adapter, message_id, native):
    from hud_dot import Rejected, canonical
    if not isinstance(native, dict) or native.get('state') not in ('accepted', 'refused', 'uncertain'):
        raise Rejected('Invalid native delivery result')
    # Never accept caller-supplied actual-delivery flags as proof.
    safe = {'state': native['state'], 'actualReceiptConfirmed': False}
    if isinstance(native.get('deliveryMode'), str):
        safe['deliveryMode'] = native['deliveryMode'][:40]
    with adapter.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT native_receipt FROM messages WHERE id=?', (message_id,)).fetchone()
        if not row or json.loads(row['native_receipt'] or '{}').get('state') != 'reserved':
            raise Rejected('Native delivery was not reserved or was already completed')
        db.execute('UPDATE messages SET native_receipt=? WHERE id=?', (canonical(safe), message_id))
    return adapter.receipt(message_id)


def confirm(adapter, reply_id, source):
    from hud_dot import Rejected, canonical, timestamp, headers_for, EVENT, MAILBOX
    with adapter.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM messages WHERE reply_id=?', (reply_id,)).fetchone()
        if not row or row['source'] != source:
            raise Rejected('Only the original recipient can confirm this reply')
        if row['recipient_confirmed'] is not None:
            return adapter.receipt(row['id'], source)
        sub = adapter._subscription()
        event_id = 'receipt-' + uuid.uuid4().hex
        # Persist both proof and notification reservation before the network call.
        db.execute('UPDATE messages SET recipient_confirmed=?,receipt_state=?,receipt_event_id=? WHERE id=?',
                   (adapter.clock(), 'reserved', event_id, row['id']))
    event = {'eventId': event_id, 'name': EVENT, 'timestamp': timestamp(adapter.clock()),
             'cursor': None, 'data': {'kind': 'delivery_receipt', 'mailbox': MAILBOX,
             'message_id': row['id'], 'source': source,
             'text': 'Recipient confirmed actual delivery of reply ' + reply_id}}
    body = canonical(event).encode()
    state = 'uncertain'
    try:
        status, _ = adapter.post(sub['callback'], body, headers_for(
            adapter.decrypt(sub['secret']), sub['id'], event_id, body, adapter.clock()))
        state = 'webhook_accepted' if 200 <= status < 300 else 'webhook_refused'
    except Exception:
        pass
    with adapter.db() as db:
        db.execute('UPDATE messages SET receipt_state=? WHERE id=?', (state, row['id']))
    return adapter.receipt(row['id'], source)


def internal(adapter, action, params):
    from hud_dot import Rejected
    if action == 'pending':
        return {'messages': pending(adapter)}
    if action == 'claim':
        return claim(adapter, params.get('id'))
    if action == 'complete':
        return complete(adapter, params.get('id'), params.get('native'))
    if action == 'confirm':
        return confirm(adapter, params.get('id'), params.get('source'))
    raise Rejected('Unknown internal HUD operation', -32601)
