"""Durable HUD return outbox and explicit recipient-confirmed delivery receipts."""
import json
import hashlib
import hmac
import secrets
import uuid
import base64


def migrate(db):
    from dot_sessions import migrate as migrate_sessions
    migrate_sessions(db)
    columns = {row[1] for row in db.execute('PRAGMA table_info(messages)')}
    for name, declaration in [('recipient_confirmed', 'REAL'),
                              ('receipt_state', 'TEXT'), ('receipt_event_id', 'TEXT'),
                              ('delivery_challenge_hash', 'TEXT'),
                              ('receipt_protocol', "TEXT NOT NULL DEFAULT 'legacy'")]:
        if name not in columns:
            db.execute('ALTER TABLE messages ADD COLUMN ' + name + ' ' + declaration)


def pending(adapter):
    with adapter.db() as db:
        rows = db.execute("SELECT * FROM messages WHERE reply_id IS NOT NULL AND json_extract(native_receipt,'$.state')='pending_hud' ORDER BY created LIMIT 8").fetchall()
    return [{'id': row['id'], 'replyId': row['reply_id'], 'source': row['source'], 'origin': row['origin'],
             'text': row['reply_text']} for row in rows
            if row['native_receipt'] and json.loads(row['native_receipt']).get('state') == 'pending_hud']


def native_challenge(adapter, row):
    from hud_dot import canonical
    binding = canonical(['agent-hud-native-receipt-v2', row['id'], row['reply_id'], row['source'],
                         hashlib.sha256(row['reply_text'].encode()).hexdigest()]).encode()
    return base64.urlsafe_b64encode(hmac.new(adapter.receipt_key, binding, hashlib.sha256).digest()).decode().rstrip('=')


def claim(adapter, message_id, protocol='legacy'):
    """Reserve before the native mutation. A crashed claim is never re-sent."""
    from hud_dot import canonical, Rejected
    if protocol not in ('legacy', 'native-v2'):
        raise Rejected('Unknown native receipt protocol')
    with adapter.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone()
        if not row or not row['native_receipt'] or json.loads(row['native_receipt']).get('state') != 'pending_hud':
            return {'claimed': False}
        challenge = native_challenge(adapter, row) if protocol == 'native-v2' else secrets.token_urlsafe(24)
        db.execute('UPDATE messages SET native_receipt=?,delivery_challenge_hash=?,receipt_protocol=? WHERE id=?',
                   (canonical({'state': 'reserved', 'actualReceiptConfirmed': False}),
                    hashlib.sha256(challenge.encode()).hexdigest(), protocol, message_id))
    result = {'claimed': True, 'id': row['id'], 'replyId': row['reply_id'],
              'source': row['source'], 'origin': row['origin'], 'text': row['reply_text'], 'receiptProtocol': protocol}
    if protocol == 'legacy':
        result['deliveryChallenge'] = challenge
    return result


def authorization(adapter, reply_id, source):
    """Private controller read after native proof; never exposed to Dot tools/events."""
    from hud_dot import Rejected
    with adapter.db() as db:
        row = db.execute('SELECT * FROM messages WHERE reply_id=?', (reply_id,)).fetchone()
    if (not row or row['source'] != source or row['receipt_protocol'] != 'native-v2'
            or json.loads(row['native_receipt'] or '{}').get('state') not in ('reserved', 'accepted', 'uncertain')):
        raise Rejected('Native receipt authorization unavailable for this recipient')
    challenge = native_challenge(adapter, row)
    if not hmac.compare_digest(hashlib.sha256(challenge.encode()).hexdigest(), row['delivery_challenge_hash'] or ''):
        raise Rejected('Native receipt authorization identity changed')
    return {'receiptProtocol': 'native-v2', 'deliveryChallenge': challenge}


def complete(adapter, message_id, native):
    from hud_dot import Rejected, canonical
    if not isinstance(native, dict) or native.get('state') not in ('accepted', 'refused', 'uncertain'):
        raise Rejected('Invalid native delivery result')
    # Never accept caller-supplied actual-delivery flags as proof.
    safe = {'state': native['state'], 'actualReceiptConfirmed': False}
    if isinstance(native.get('deliveryMode'), str):
        safe['deliveryMode'] = native['deliveryMode'][:40]
    if native.get('reasonCode') in {'pass_limit', 'permission_denied', 'recipient_unavailable'}:
        safe['reasonCode'] = native['reasonCode']
    with adapter.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT native_receipt FROM messages WHERE id=?', (message_id,)).fetchone()
        if not row or json.loads(row['native_receipt'] or '{}').get('state') != 'reserved':
            raise Rejected('Native delivery was not reserved or was already completed')
        db.execute('UPDATE messages SET native_receipt=? WHERE id=?', (canonical(safe), message_id))
    return adapter.receipt(message_id)


def confirm(adapter, reply_id, source, challenge):
    from hud_dot import Rejected, canonical, timestamp, headers_for, EVENT, MAILBOX, LEGACY_MAILBOX
    with adapter.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM messages WHERE reply_id=?', (reply_id,)).fetchone()
        if not row or row['source'] != source:
            raise Rejected('Only the original recipient can confirm this reply')
        if (not isinstance(challenge, str) or len(challenge) > 128
                or not hmac.compare_digest(hashlib.sha256(challenge.encode()).hexdigest(),
                                           row['delivery_challenge_hash'] or '')):
            raise Rejected('The delivery challenge from the actual incoming message is required')
        if row['recipient_confirmed'] is not None:
            return adapter.receipt(row['id'], source)
        if json.loads(row['native_receipt'] or '{}').get('state') in {'pending_hud', 'refused'}:
            raise Rejected('A reply not delivered by HUD cannot be confirmed')
        sub = db.execute('SELECT * FROM subscriptions WHERE mailbox IN (?,?)', (MAILBOX, LEGACY_MAILBOX)).fetchone()
        active = adapter._active_subscription(sub)
        event_id = 'receipt-' + uuid.uuid4().hex if active else None
        # Persist both proof and notification reservation before the network call.
        db.execute('UPDATE messages SET recipient_confirmed=?,receipt_state=?,receipt_event_id=? WHERE id=?',
                   (adapter.clock(), 'reserved' if active else 'notification_unavailable', event_id, row['id']))
    if not active:
        return adapter.receipt(row['id'], source)
    event = {'eventId': event_id, 'name': EVENT, 'timestamp': timestamp(adapter.clock()),
             'cursor': None, 'data': {'kind': 'delivery_receipt', 'mailbox': sub['mailbox'],
             'message_id': row['id'], 'source': source,
             'text': 'Recipient confirmed actual delivery of ' + ('message ' if row['origin'] == 'dot' else 'reply ') + reply_id}}
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
    if action == 'sessions':
        from dot_sessions import publish
        return publish(adapter, params)
    if action == 'pending':
        return {'messages': pending(adapter)}
    if action == 'claim':
        return claim(adapter, params.get('id'), params.get('receiptProtocol', 'legacy'))
    if action == 'receipt_authorization':
        return authorization(adapter, params.get('id'), params.get('source'))
    if action == 'complete':
        return complete(adapter, params.get('id'), params.get('native'))
    if action == 'confirm':
        return confirm(adapter, params.get('id'), params.get('source'), params.get('deliveryChallenge'))
    raise Rejected('Unknown internal HUD operation', -32601)
