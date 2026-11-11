"""Private HUD/Dot MCP Events adapter. Importing this module starts nothing.

Run only after the local HTTP endpoint and plugin connection are authorized.
No Bridge dependency. Platform-created subscriptions bind the receiving chat.
"""
import argparse
import sys
import base64
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
from functools import partial
import datetime as dt
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import ssl
import subprocess
import threading
import time
from urllib.parse import urlsplit, urlencode
import uuid

_data_home = Path.home() / 'Library/Application Support' if sys.platform == 'darwin' else Path(os.environ.get('LOCALAPPDATA', str(Path.home())))
ROOT = Path(os.environ.get('AGENTHUD_DOT_DATA', str(_data_home / 'AgentHUDPrivate' / 'dot-client')))
EVENT = 'hud.message.created'
MAILBOX = 'dot'
# Accepted only for existing tasks; both names bind the same single recipient.
LEGACY_MAILBOX = 'luo'
LIMIT = 256 * 1024
ADAPTER_VERSION = '0.3.0'


class Rejected(Exception):
    def __init__(self, message, code=-32602, reason=None, http_status=None):
        super().__init__(message)
        self.code = code
        self.reason = reason
        self.http_status = http_status


DIAGNOSTIC_METHODS = {'initialize', 'server/discover', 'ping', 'tools/list', 'tools/call',
                      'events/list', 'events/subscribe', 'events/unsubscribe',
                      'notifications/initialized'}
DIAGNOSTIC_REASONS = {'invalid_request', 'unknown_event', 'invalid_mailbox',
                      'delivery_mode', 'invalid_signing_secret', 'invalid_lifetime',
                      'mailbox_already_bound', 'callback_address_rejected',
                      'callback_timeout', 'callback_tls_error', 'callback_network_error',
                      'callback_http_error', 'callback_invalid_json',
                      'callback_challenge_mismatch', 'callback_failed', 'internal_error'}
DIAGNOSTIC_REASONS.update({'callback_invalid_url', 'callback_dns_error',
                           'callback_non_public_address', 'callback_fake_ip_address'})
_diagnostic_lock = threading.Lock()


def diagnostic_record(phase, role, method, code=None, reason=None, http_status=None):
    """Closed metadata vocabulary: never serialize caller strings or parameters."""
    record = {'time': timestamp(time.time()),
              'phase': phase if phase in {'received', 'completed', 'rejected', 'failed', 'http_rejected'} else 'unknown',
              'role': role if role in {'local', 'dot'} else 'unknown',
              'method': method if isinstance(method, str) and method in DIAGNOSTIC_METHODS else 'unknown'}
    if type(code) is int and code in {-32601, -32602, -32603, -32015}:
        record['code'] = code
    if reason in DIAGNOSTIC_REASONS:
        record['reason'] = reason
    if type(http_status) is int and 100 <= http_status <= 599:
        record['httpStatus'] = http_status
    return record


def write_diagnostic(record):
    try:
        with _diagnostic_lock:
            path = ROOT / 'diagnostics.jsonl'
            if not path.exists() or path.stat().st_size < 1024 * 1024:
                with path.open('a', encoding='utf-8') as stream:
                    stream.write(canonical(record) + '\n')
    except OSError:
        pass  # Diagnostics must never change the result or retry a request.


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def timestamp(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat()


def protect(value, decrypt=False):
    """Current-user DPAPI; neither cleartext nor ciphertext is logged."""
    if sys.platform == 'darwin':
        try:
            from dot_storage import mac_blob
            return mac_blob(value, decrypt, ROOT)
        except Exception:
            raise Rejected('Protected subscription Keychain unavailable', -32603)
    if sys.platform != 'win32':
        raise Rejected('No supported secure credential store on this platform', -32603)
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    raw = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(raw, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise Rejected('Protected subscription storage unavailable', -32603)
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def signing_key(secret):
    if not isinstance(secret, str) or not secret.startswith('whsec_'):
        raise Rejected('Invalid webhook signing secret', reason='invalid_signing_secret')
    try:
        raw = base64.b64decode(secret[6:], validate=True)
    except Exception:
        raise Rejected('Invalid webhook signing secret', reason='invalid_signing_secret')
    if not 24 <= len(raw) <= 64:
        raise Rejected('Invalid webhook signing secret', reason='invalid_signing_secret')
    return raw


def headers_for(key, subscription, event_id, body, now):
    signed_at = str(int(now))
    signature = base64.b64encode(hmac.new(
        key, event_id.encode() + b'.' + signed_at.encode() + b'.' + body, hashlib.sha256
    ).digest()).decode()
    return {'Content-Type': 'application/json', 'webhook-id': event_id,
            'webhook-timestamp': signed_at, 'webhook-signature': 'v1,' + signature,
            'X-MCP-Subscription-Id': subscription}


def public_callback(url, resolver=socket.getaddrinfo):
    try:
        parts = urlsplit(url)
        if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
                or parts.fragment or parts.port not in (None, 443) or len(url) > 4096):
            raise ValueError()
    except Exception:
        raise Rejected('Callback URL is invalid', -32015, reason='callback_invalid_url')
    try:
        addresses = list(dict.fromkeys(x[4][0] for x in resolver(
            parts.hostname, 443, type=socket.SOCK_STREAM)))
    except Exception:
        raise Rejected('Callback DNS resolution failed', -32015, reason='callback_dns_error')
    try:
        ips = [ipaddress.ip_address(address) for address in addresses]
        if any(ip.version == 4 and ip in ipaddress.ip_network('198.18.0.0/15') for ip in ips):
            raise Rejected('Callback resolved to a benchmark address', -32015,
                           reason='callback_fake_ip_address')
        if not ips or any(not ip.is_global or ip.is_multicast or ip.is_reserved for ip in ips):
            raise ValueError()
    except Rejected:
        raise
    except Exception:
        raise Rejected('Callback must resolve exclusively to public HTTPS addresses', -32015,
                       reason='callback_non_public_address')
    return parts, addresses[0]


def loopback_proxy(value):
    """Only an explicitly configured, credential-free loopback HTTP proxy."""
    try:
        parts = urlsplit(value)
        if (parts.scheme != 'http' or not parts.hostname or parts.username or parts.password
                or not ipaddress.ip_address(parts.hostname).is_loopback
                or parts.path not in ('', '/') or parts.query or parts.fragment
                or parts.port is None or not 1 <= parts.port <= 65535):
            raise ValueError()
        return parts.hostname, parts.port
    except Exception:
        raise Rejected('A credential-free loopback HTTP CONNECT proxy is required')


def dns_name(value):
    name = value.rstrip('.').encode('idna').decode('ascii').lower()
    if (len(name) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                                  for label in name.split('.'))):
        raise ValueError()
    return name


def doh_addresses(host, proxy):
    """Only the callback hostname goes to a fixed TLS-authenticated public resolver.

    No callback URL/path, signatures, secret or event content leaves via DNS.
    The returned addresses are still checked by public_callback before use.
    """
    connection = None
    try:
        host = dns_name(host)
        connection = http.client.HTTPSConnection(*loopback_proxy(proxy), timeout=10,
                                                  context=ssl.create_default_context())
        connection.set_tunnel('cloudflare-dns.com', 443)
        connection.request('GET', '/dns-query?' + urlencode({'name': host, 'type': 'A'}),
                           headers={'Accept': 'application/dns-json'})
        response = connection.getresponse()
        body = response.read(16385)
        if response.status != 200 or len(body) > 16384:
            raise ValueError()
        data = json.loads(body)
        questions = data.get('Question', [])
        if (data.get('Status') != 0 or data.get('TC', False)
                or len(questions) != 1 or questions[0].get('type') != 1
                or dns_name(questions[0].get('name', '')) != host):
            raise ValueError()
        answers = data.get('Answer', [])
        if not isinstance(answers, list) or len(answers) > 64:
            raise ValueError()
        reachable = {host}
        for _ in range(10):
            added = {dns_name(a['data']) for a in answers
                     if a.get('type') == 5 and dns_name(a.get('name', '')) in reachable}
            if added <= reachable:
                break
            reachable.update(added)
        addresses = list(dict.fromkeys(a['data'] for a in answers
                         if a.get('type') == 1 and dns_name(a.get('name', '')) in reachable))
        if not addresses:
            raise ValueError()
        # A query must yield literal IPv4 records, not another hostname to resolve.
        if any(ipaddress.ip_address(a).version != 4 for a in addresses):
            raise ValueError()
        return addresses
    except Exception:
        raise Rejected('Callback public DNS lookup failed', -32015, reason='callback_dns_error')
    finally:
        if connection:
            connection.close()


def pinned_https(host, address, proxy=None):
    """Connect to the already validated address; TLS always authenticates host."""
    raw = None
    connection = http.client.HTTPSConnection(host, 443, timeout=10)
    try:
        if proxy:
            transport = http.client.HTTPConnection(*loopback_proxy(proxy), timeout=10)
            try:
                transport.set_tunnel(address, 443)
                transport.connect()
                raw = transport.sock
                transport.sock = None
            finally:
                transport.close()
        else:
            raw = socket.create_connection((address, 443), timeout=10)
        connection.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        raw = None
        return connection
    except Exception:
        connection.close()
        if raw:
            raw.close()
        raise


def webhook_post(url, body, headers, proxy=None):
    """Resolve on each request, pin the validated address, preserve TLS SNI."""
    if proxy:
        # Resolve literals locally only to subject them to the same rejection rules.
        def resolver(host, port, **_):
            try:
                ipaddress.ip_address(host)
                addresses = [host]
            except ValueError:
                addresses = doh_addresses(host, proxy)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (a, port)) for a in addresses]
        parts, address = public_callback(url, resolver)
    else:
        parts, address = public_callback(url)
    connection = pinned_https(parts.hostname, address, proxy)
    try:
        path = parts.path or '/'
        if parts.query:
            path += '?' + parts.query
        connection.request('POST', path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise Rejected('Webhook response too large', -32015)
        # http.client does not follow redirects.
        return response.status, data
    finally:
        connection.close()


def native_reply(source, message_id, reply_id, text):
    # The existing HUD delivery owner drains this durable outbox. Never start
    # a replacement app-server, impersonate a Codex caller, or retry a send.
    return {'state': 'pending_hud', 'actualReceiptConfirmed': False}


class Adapter:
    def __init__(self, database, post=webhook_post, clock=time.time,
                 encrypt=protect, decrypt=lambda x: protect(x, True), sink=native_reply,
                 native_reply_wait=0, receipt_key=None):
        self.database, self.post, self.clock = str(database), post, clock
        self.encrypt, self.decrypt, self.sink = encrypt, decrypt, sink
        self.native_reply_wait = max(0, min(float(native_reply_wait), 6))
        self.receipt_key = receipt_key if receipt_key is not None else secrets.token_bytes(32)
        if not isinstance(self.receipt_key, bytes) or len(self.receipt_key) < 32:
            raise Rejected('Protected native receipt key unavailable')
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS subscriptions ('
                       'id TEXT PRIMARY KEY, mailbox TEXT UNIQUE, callback TEXT, secret BLOB, expires REAL)')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_dot_subscription ON subscriptions "
                       "((CASE WHEN mailbox IN ('dot','luo') THEN 'dot' ELSE mailbox END))")
            db.execute('CREATE TABLE IF NOT EXISTS messages ('
                       'id TEXT PRIMARY KEY, source TEXT, text TEXT, state TEXT, created REAL, '
                       'acknowledged REAL, reply_id TEXT, reply_text TEXT, native_receipt TEXT)')
            from dot_receipts import migrate
            migrate(db)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.database, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _mailbox(self, arguments):
        if arguments not in ({'mailbox': MAILBOX}, {'mailbox': LEGACY_MAILBOX}):
            raise Rejected('Only the explicitly configured Dot mailbox is available', reason='invalid_mailbox')

    def _subscription(self):
        with self.db() as db:
            row = db.execute('SELECT * FROM subscriptions WHERE mailbox IN (?,?)', (MAILBOX, LEGACY_MAILBOX)).fetchone()
        if not self._active_subscription(row):
            raise Rejected('Dot has no active verified subscription')
        return row

    def _active_subscription(self, row):
        return row is not None and (row['expires'] is None or row['expires'] > self.clock())

    def subscribe(self, params):
        if params.get('name') != EVENT:
            raise Rejected('Unknown event', reason='unknown_event')
        self._mailbox(params.get('arguments'))
        delivery = params.get('delivery', {})
        if delivery.get('mode') != 'webhook':
            raise Rejected('Only webhook subscriptions are supported', reason='delivery_mode')
        url = delivery.get('url')
        # URL syntax/DNS checks also run inside the production sender at connect time.
        if not isinstance(url, str) or not url.startswith('https://'):
            raise Rejected('HTTPS callback required', -32015, reason='callback_address_rejected')
        key = signing_key(delivery.get('secret'))
        identity = canonical(['dot:luo', url, EVENT, {'mailbox': LEGACY_MAILBOX}])
        sub_id = 'sub_' + hashlib.sha256(identity.encode()).hexdigest()[:32]
        with self.db() as db:
            existing = db.execute('SELECT * FROM subscriptions WHERE mailbox IN (?,?)', (MAILBOX, LEGACY_MAILBOX)).fetchone()
        if existing and existing['id'] != sub_id and self._active_subscription(existing):
            raise Rejected('Dot mailbox already bound; unsubscribe the existing chat first', reason='mailbox_already_bound')
        ttl = params.get('ttlMs', 3600000)
        if ttl is None:
            # Grant no expiration only when the authenticated platform explicitly
            # requested it. An omitted lifetime keeps the bounded default.
            expires = None
        else:
            if not isinstance(ttl, (int, float)) or isinstance(ttl, bool) or ttl <= 0:
                raise Rejected('Invalid subscription lifetime', reason='invalid_lifetime')
            expires = self.clock() + min(ttl / 1000, 3600)
        challenge = secrets.token_urlsafe(24)
        body = canonical({'type': 'verification', 'challenge': challenge}).encode()
        event_id = 'verify_' + uuid.uuid4().hex
        try:
            status, reply = self.post(url, body, headers_for(key, sub_id, event_id, body, self.clock()))
            if not 200 <= status < 300:
                raise Rejected('Callback verification failed', -32015,
                               reason='callback_http_error', http_status=status)
            try:
                returned = json.loads(reply).get('challenge')
            except (ValueError, AttributeError):
                raise Rejected('Callback verification failed', -32015, reason='callback_invalid_json')
            if not isinstance(returned, str) or not hmac.compare_digest(returned, challenge):
                raise Rejected('Callback verification failed', -32015, reason='callback_challenge_mismatch')
        except Rejected:
            raise
        except TimeoutError:
            raise Rejected('Callback verification failed', -32015, reason='callback_timeout')
        except ssl.SSLError:
            raise Rejected('Callback verification failed', -32015, reason='callback_tls_error')
        except OSError:
            raise Rejected('Callback verification failed', -32015, reason='callback_network_error')
        except Exception:
            raise Rejected('Callback verification failed', -32015, reason='callback_failed')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # UNIQUE mailbox prevents a second concurrent callback from taking over.
            current = db.execute('SELECT id,expires FROM subscriptions WHERE mailbox IN (?,?)', (MAILBOX, LEGACY_MAILBOX)).fetchone()
            if current and current['id'] != sub_id and self._active_subscription(current):
                raise Rejected('Dot mailbox binding changed during verification')
            db.execute('INSERT OR REPLACE INTO subscriptions VALUES(?,?,?,?,?)',
                       (sub_id, params['arguments']['mailbox'], url, self.encrypt(key), expires))
        return {'id': sub_id, 'refreshBefore': timestamp(expires) if expires is not None else None, 'cursor': None, 'truncated': False}

    def unsubscribe(self, params):
        if params.get('name') != EVENT:
            raise Rejected('Unknown event')
        self._mailbox(params.get('arguments'))
        url = params.get('delivery', {}).get('url')
        with self.db() as db:
            db.execute('DELETE FROM subscriptions WHERE mailbox IN (?,?) AND callback=?', (MAILBOX, LEGACY_MAILBOX, url))
        return {}

    def send(self, message_id, source, text):
        try:
            uuid.UUID(source.removeprefix('codex:'))
        except (ValueError, AttributeError):
            raise Rejected('Executor-supplied Codex identity required')
        if not source.startswith('codex:') or not isinstance(text, str) or not text or len(text) > 32000:
            raise Rejected('Invalid message')
        if not isinstance(message_id, str) or not re.fullmatch(r'm-[A-Za-z0-9-]{1,96}', message_id):
            raise Rejected('Stable message ID required')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone()
            if existing:
                if existing['origin'] != 'codex' or existing['source'] != source or existing['text'] != text:
                    raise Rejected('Message ID already belongs to different content')
                return self.receipt(message_id, source)
            sub = self._subscription()
            db.execute('INSERT INTO messages(id,source,text,state,created) VALUES(?,?,?,?,?)',
                       (message_id, source, text, 'reserved', self.clock()))
        event = {'eventId': message_id, 'name': EVENT, 'timestamp': timestamp(self.clock()),
                 'data': {'mailbox': sub['mailbox'], 'message_id': message_id, 'source': source, 'text': text, 'kind': 'message'},
                 'cursor': None}
        body = canonical(event).encode()
        state = 'uncertain'
        try:
            status, _ = self.post(sub['callback'], body, headers_for(
                self.decrypt(sub['secret']), sub['id'], message_id, body, self.clock()))
            state = 'webhook_accepted' if 200 <= status < 300 else 'webhook_refused'
        except Exception:
            pass
        with self.db() as db:
            # A fast Dot ACK/reply must not be overwritten by this HTTP completion.
            db.execute('UPDATE messages SET state=? WHERE id=? AND state=?', (state, message_id, 'reserved'))
        return self.receipt(message_id, source)

    def receipt(self, message_id, source=None):
        with self.db() as db:
            row = db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone()
        if not row or (source is not None and row['source'] != source):
            raise Rejected('Message unavailable to this sender')
        native = json.loads(row['native_receipt']) if row['native_receipt'] else None
        if native is not None and row['recipient_confirmed'] is not None:
            native['actualReceiptConfirmed'] = True
        transport = native.get('deliveryMode', native.get('state')) if native else None
        if transport == 'reserved':
            transport = 'pending_hud'
        return {'id': row['id'], 'state': row['state'], 'source': row['source'],
                'origin': row['origin'], 'deliveryId': row['reply_id'],
                'dotAcknowledged': row['acknowledged'] is not None if row['origin'] != 'dot' else None,
                'replyId': row['reply_id'] if row['origin'] != 'dot' else None,
                'replyText': row['reply_text'] if row['origin'] != 'dot' else None,
                'messageText': row['text'] if row['origin'] == 'dot' else None,
                'nativeReceipt': native,
                'transportState': transport,
                'recipientConfirmed': row['recipient_confirmed'] is not None,
                'deliveryReceiptState': row['receipt_state']}

    def ack(self, message_id):
        self._subscription()
        if self.receipt(message_id)['origin'] != 'codex':
            raise Rejected('Only an incoming message event can be acknowledged')
        with self.db() as db:
            db.execute('UPDATE messages SET acknowledged=COALESCE(acknowledged,?), '
                       'state=CASE WHEN reply_id IS NULL THEN ? ELSE state END WHERE id=?',
                       (self.clock(), 'dot_received', message_id))
        return self.receipt(message_id)

    def reply(self, message_id, text):
        self._subscription()
        if not isinstance(text, str) or not text or len(text) > 32000:
            raise Rejected('Invalid reply')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone()
            if not row:
                raise Rejected('Reply must name an actual received HUD message')
            if row['origin'] == 'dot':
                raise Rejected('hud_reply is Dot-to-Codex only. To answer a Dot-initiated message from Codex, use the local Agent HUD send_message tool with reply_to set to the received message ID. Reload the local Agent HUD MCP tools if send_message is missing; do not retry through Dot-HUD hud_reply.')
            if row['reply_id']:
                if row['reply_text'] != text:
                    raise Rejected('Message already has a different reply')
                return self.receipt(message_id)
            reply_id = 'm-' + uuid.uuid4().hex
            db.execute('UPDATE messages SET reply_id=?,reply_text=?,acknowledged=?,state=? WHERE id=?',
                       (reply_id, text, self.clock(), 'reply_reserved', message_id))
        try:
            native = self.sink(row['source'], message_id, reply_id, text)
        except Exception:
            native = {'state': 'uncertain', 'reason': 'Reply receipt unavailable; no retry'}
        with self.db() as db:
            db.execute('UPDATE messages SET state=?,native_receipt=? WHERE id=?',
                       ('dot_replied', canonical(native), message_id))
        return self.wait_native(message_id)

    def wait_native(self, message_id):
        # The HUD's existing worker owns native delivery. Wait only for its
        # acknowledgement; never reserve, deliver or retry from this HTTP thread.
        deadline = time.monotonic() + self.native_reply_wait
        while self.native_reply_wait:
            current = self.receipt(message_id)
            state = (current.get('nativeReceipt') or {}).get('state')
            if state not in {'pending_hud', 'reserved'} or time.monotonic() >= deadline:
                return current
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        return self.receipt(message_id)

    def rpc(self, role, request):
        method, params = request.get('method'), request.get('params', {})
        if method == 'initialize':
            return {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {}, 'events': {}},
                    'serverInfo': {'name': 'hud-dot', 'version': ADAPTER_VERSION},
                    'instructions': 'These remote tools are for Dot. hud_reply is Dot-to-Codex only; hud_list_sessions lists Codex targets, not DSH. Codex/DSH must use local Agent HUD list_sessions/send_message/get_message. Codex replies to a received Dot message via local send_message(reply_to=received_id). Missing native tools require client MCP reload, never a wrong-direction retry. delivery_receipt events are recorded without ACK or reply.'}
        if method == 'ping':
            return {}
        if method == 'events/list':
            if role != 'dot':
                raise Rejected('Dot connection required')
            fields = {x: {'type': 'string'} for x in ['mailbox', 'message_id', 'source', 'text', 'kind']}
            fields['kind']['enum'] = ['message', 'delivery_receipt']
            return {'events': [{'name': EVENT, 'description': 'A new HUD message addressed to Dot.',
                    'delivery': ['webhook'], 'inputSchema': {'type': 'object',
                    'properties': {'mailbox': {'type': 'string', 'enum': [MAILBOX, LEGACY_MAILBOX], 'description': 'Use dot for new subscriptions; luo is a compatibility alias for existing tasks.'}},
                    'required': ['mailbox'], 'additionalProperties': False},
                    'payloadSchema': {'type': 'object', 'properties': fields,
                                      'required': list(fields), 'additionalProperties': False}}]}
        if method in ('events/subscribe', 'events/unsubscribe'):
            if role != 'dot':
                raise Rejected('Dot connection required')
            return self.subscribe(params) if method.endswith('/subscribe') else self.unsubscribe(params)
        if method == 'tools/list':
            definitions = [('hud_ack_message', ['id'], 'Dot only: acknowledge an incoming Codex message event actually received by Dot. Not for Codex receipts or delivery_receipt events.'),
                           ('hud_list_sessions', [], 'Dot only: list fresh existing Codex sessions on this entry’s machine. This is not the local Agent HUD list_sessions and never lists DSH/Claude. Codex/DSH agents must use local Agent HUD list_sessions. Never guess IDs or create replacement chats.'),
                           ('hud_send_message', ['host_id', 'session_id', 'text', 'request_id'], 'Dot-to-Codex only: choose this entry’s Mac/Windows host.id and existing session from hud_list_sessions. session_id accepts a UUID or exact codex://threads/<UUID> URL. Use one new stable request_id per intended send; identical calls only read its receipt, never resend. Active Desktop steers; idle/no owner queues. Never use a new request_id to retry uncertain/refused sends. Await delivery_receipt.'),
                           ('hud_reply', ['id', 'text'], 'Dot-to-Codex only: reply once to an incoming Codex message with origin=codex. Codex answering a Dot-initiated message must use local Agent HUD send_message(reply_to=received_id), not this tool. transportState reports native queued/steered/started, or pending_hud while awaiting HUD. Never resend on pending/uncertain; recipientConfirmed is separate. Await delivery_receipt or query hud_get_delivery_status.'),
                           ('hud_get_delivery_status', ['id'], 'Read whether the actual recipient confirmed your reply. Read-only; never acknowledges delivery.')]
            if role == 'local':
                definitions = [('hud_dot_status', [], 'Check whether Dot has a verified event subscription.'),
                               ('hud_send_to_dot', ['id', 'text'], 'Send one HUD message to subscribed Dot.'),
                               ('hud_get_message', ['id'], 'Read a message receipt; this is not an actual chat input.')]
            return {'tools': [{'name': name, 'description': description, 'inputSchema': {
                'type': 'object', 'properties': {x: {'type': 'string'} for x in fields},
                'required': fields, 'additionalProperties': False}, 'annotations': {
                    'readOnlyHint': name in ('hud_get_message', 'hud_dot_status', 'hud_get_delivery_status', 'hud_list_sessions'), 'destructiveHint': False,
                    'openWorldHint': name not in ('hud_get_message', 'hud_dot_status')}} for name, fields, description in definitions]}
        if method.startswith('hud/internal/'):
            if role != 'local':
                raise Rejected('Local HUD owner required')
            from dot_receipts import internal
            return internal(self, method.removeprefix('hud/internal/'), params)
        if method == 'tools/call':
            name, args = params.get('name'), params.get('arguments', {})
            if role == 'dot' and name == 'hud_get_delivery_status':
                result = self.receipt(args.get('id'))
            elif role == 'dot' and name == 'hud_list_sessions':
                from dot_sessions import inventory
                result = inventory(self)
            elif role == 'dot' and name == 'hud_send_message':
                from dot_sessions import send
                result = send(self, args.get('session_id'), args.get('text'), args.get('request_id'), args.get('host_id'))
            elif role == 'dot' and name == 'hud_ack_message':
                result = self.ack(args.get('id'))
            elif role == 'dot' and name == 'hud_reply':
                result = self.reply(args.get('id'), args.get('text'))
            elif role == 'local' and name == 'hud_dot_status':
                try:
                    sub = self._subscription()
                    result = {'mailbox': sub['mailbox'], 'subscribed': True, 'expires': timestamp(sub['expires']) if sub['expires'] is not None else None}
                except Rejected:
                    result = {'mailbox': MAILBOX, 'subscribed': False}
                result['adapterVersion'] = ADAPTER_VERSION
                with self.db() as db:
                    confirmed = db.execute('SELECT reply_id,recipient_confirmed FROM messages WHERE recipient_confirmed IS NOT NULL ORDER BY recipient_confirmed DESC LIMIT 1').fetchone()
                    result['confirmedReplies'] = db.execute('SELECT COUNT(*) FROM messages WHERE recipient_confirmed IS NOT NULL').fetchone()[0]
                    result['lastConfirmedReplyId'] = confirmed['reply_id'] if confirmed else None
                    result['lastConfirmedAt'] = timestamp(confirmed['recipient_confirmed']) if confirmed else None
            elif role == 'local' and name in ('hud_send_to_dot', 'hud_get_message'):
                meta = params.get('_meta', {})
                identity = meta.get('threadId') or meta.get('x-codex-turn-metadata', {}).get('thread_id')
                if not isinstance(identity, str):
                    raise Rejected('Executor thread metadata required')
                source = 'codex:' + identity
                result = (self.send(args.get('id'), source, args.get('text')) if name == 'hud_send_to_dot'
                          else self.receipt(args.get('id'), source))
            else:
                raise Rejected('Tool unavailable to this connection')
            return {'content': [{'type': 'text', 'text': canonical(result)}], 'isError': False}
        raise Rejected('Method not supported', -32601)


def make_handler(adapter, local_token, dot_token, audit=None):
    if min(len(local_token), len(dot_token)) < 32 or hmac.compare_digest(local_token, dot_token):
        raise Rejected('Two distinct access tokens of at least 32 characters are required')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # No request paths, payloads, callbacks or authorization headers in logs.

        def do_POST(self):
            if self.path != '/mcp':
                if audit:
                    audit(diagnostic_record('http_rejected', None, None, http_status=404))
                self.send_error(404)
                return
            if self.headers.get('Origin'):
                if audit:
                    audit(diagnostic_record('http_rejected', None, None, http_status=403))
                self.send_error(403)
                return
            authorization = self.headers.get('Authorization', '')
            role = None
            for candidate, token in [('local', local_token), ('dot', dot_token)]:
                if hmac.compare_digest(authorization, 'Bearer ' + token):
                    role = candidate
            if role is None:
                if audit:
                    audit(diagnostic_record('http_rejected', None, None, http_status=401))
                self.send_error(401)
                return
            request = None
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= LIMIT:
                    raise Rejected('Invalid request size')
                if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                    raise Rejected('application/json required')
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict) or request.get('jsonrpc') != '2.0':
                    raise Rejected('Invalid JSON-RPC request')
                if audit:
                    audit(diagnostic_record('received', role, request.get('method')))
                if 'id' not in request:
                    self.send_response(202)
                    self.end_headers()
                    return
                result = adapter.rpc(role, request)
                if audit:
                    audit(diagnostic_record('completed', role, request.get('method')))
                response = {'jsonrpc': '2.0', 'id': request['id'], 'result': result}
            except Rejected as error:
                if audit:
                    audit(diagnostic_record('rejected', role, request.get('method') if isinstance(request, dict) else None,
                                            error.code, error.reason or 'invalid_request', error.http_status))
                response = {'jsonrpc': '2.0', 'id': request.get('id') if isinstance(request, dict) else None,
                            'error': {'code': error.code, 'message': str(error)}}
                if error.code == -32015 and error.reason in DIAGNOSTIC_REASONS:
                    response['error']['data'] = {'reason': error.reason}
            except Exception:
                if audit:
                    audit(diagnostic_record('failed', role, request.get('method') if isinstance(request, dict) else None,
                                            -32603, 'internal_error'))
                response = {'jsonrpc': '2.0', 'id': request.get('id') if isinstance(request, dict) else None,
                            'error': {'code': -32603, 'message': 'HUD Dot request failed'}}
            body = canonical(response).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            # This adapter uses private-tunnel bearer authentication, not OAuth.
            # Tunnel discovery treats absent metadata (404) as optional; a 405
            # here is a hard startup-catalog failure. Only /mcp is a resource
            # whose GET method is deliberately unsupported.
            if self.path != '/mcp':
                self.send_error(404)
                return
            self.send_response(405)
            self.send_header('Allow', 'POST')
            self.end_headers()

    return Handler


def serve(adapter, port, local_token, dot_token):
    server = ThreadingHTTPServer(('127.0.0.1', port), make_handler(adapter, local_token, dot_token, write_diagnostic))
    print('HUD Dot MCP listening on loopback; no Bridge dependency.', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    from dot_runtime import main
    main()
