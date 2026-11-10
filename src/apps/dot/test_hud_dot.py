import base64
import hashlib
import hmac
import io
import json
from email.message import Message
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import hud_dot as hud

SOURCE = 'codex:00000000-0000-4000-8000-000000000001'
OTHER = 'codex:00000000-0000-4000-8000-000000000002'
KEY = b'fixture-signing-key-with-32bytes!!'


class Transport:
    def __init__(self):
        self.calls = []
        self.event_status = 202
        self.fail_verification = False
        self.timeout_event = False
        self.on_event = None

    def __call__(self, url, body, headers):
        data = json.loads(body)
        self.calls.append((url, data, headers, body))
        if data.get('type') == 'verification':
            return (200, b'{}') if self.fail_verification else (200, body)
        if self.on_event:
            self.on_event(data)
        if self.timeout_event:
            raise TimeoutError('fixture timeout')
        return self.event_status, b'{}'


class EventTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.now = 1794300000
        self.transport = Transport()
        self.replies = []

        def sink(*args):
            self.replies.append(args)
            return {'state': 'accepted', 'actualReceiptConfirmed': False}

        self.adapter = hud.Adapter(Path(self.directory.name) / 'state.sqlite',
                                   post=self.transport, clock=lambda: self.now,
                                   encrypt=lambda x: b'encrypted:' + x,
                                   decrypt=lambda x: x.removeprefix(b'encrypted:'), sink=sink)

    def tearDown(self):
        self.directory.cleanup()

    def subscription(self, url='https://callback.example.test/one', **extra):
        return dict({'name': hud.EVENT, 'arguments': {'mailbox': 'luo'},
                     'delivery': {'mode': 'webhook', 'url': url,
                                  'secret': 'whsec_' + base64.b64encode(KEY).decode()}}, **extra)

    def subscribe(self):
        return self.adapter.subscribe(self.subscription())

    def send(self, message='m-fixture', source=SOURCE, text='fixture marker'):
        return self.adapter.send(message, source, text)

    def test_callback_verified_before_subscription_activated(self):
        result = self.subscribe()
        self.assertTrue(result['id'].startswith('sub_'))
        self.assertEqual(self.transport.calls[0][1]['type'], 'verification')
        self.assertNotIn('secret', result)
        self.assertNotIn('callback', result)

    def test_secret_is_protected_at_rest(self):
        self.subscribe()
        with self.adapter.db() as db:
            stored = db.execute('SELECT secret FROM subscriptions').fetchone()[0]
        self.assertNotEqual(stored, KEY)

    def test_failed_challenge_does_not_bind(self):
        self.transport.fail_verification = True
        with self.assertRaises(hud.Rejected):
            self.subscribe()
        with self.assertRaises(hud.Rejected):
            self.send()

    def test_callback_failure_is_classified_without_logging_exception_text(self):
        for error, reason in [(TimeoutError('private callback URL'), 'callback_timeout'),
                              (hud.ssl.SSLError('private TLS detail'), 'callback_tls_error'),
                              (ConnectionError('private network detail'), 'callback_network_error')]:
            with self.subTest(reason=reason), patch.object(self.adapter, 'post', side_effect=error):
                with self.assertRaises(hud.Rejected) as caught:
                    self.subscribe()
                self.assertEqual(caught.exception.code, -32015)
                self.assertEqual(caught.exception.reason, reason)
                self.assertNotIn('private', str(caught.exception))
                with self.assertRaises(hud.Rejected):
                    self.adapter._subscription()

    def test_callback_http_rejection_records_status_without_response_body(self):
        with patch.object(self.adapter, 'post', return_value=(403, b'private body')):
            with self.assertRaises(hud.Rejected) as caught:
                self.subscribe()
        self.assertEqual(caught.exception.reason, 'callback_http_error')
        self.assertEqual(caught.exception.http_status, 403)
        self.assertNotIn('private', str(caught.exception))

    def test_callback_challenge_mismatch_has_explicit_reason(self):
        self.transport.fail_verification = True
        with self.assertRaises(hud.Rejected) as caught:
            self.subscribe()
        self.assertEqual(caught.exception.reason, 'callback_challenge_mismatch')

    def test_refresh_is_idempotent(self):
        first = self.subscribe()
        second = self.subscribe()
        self.assertEqual(first['id'], second['id'])
        with self.adapter.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM subscriptions').fetchone()[0], 1)

    def test_active_mailbox_cannot_switch_to_another_chat(self):
        self.subscribe()
        before = len(self.transport.calls)
        with self.assertRaises(hud.Rejected):
            self.adapter.subscribe(self.subscription(url='https://callback.example.test/other'))
        self.assertEqual(len(self.transport.calls), before)

    def test_subscribe_scope_is_exact(self):
        params = self.subscription()
        params['arguments'] = {'mailbox': 'someone-else'}
        with self.assertRaises(hud.Rejected):
            self.adapter.subscribe(params)
        self.assertEqual(self.transport.calls, [])

    def test_unsubscribe_needs_original_callback(self):
        self.subscribe()
        self.adapter.unsubscribe(self.subscription(url='https://callback.example.test/other'))
        self.send()
        self.adapter.unsubscribe(self.subscription())
        with self.assertRaises(hud.Rejected):
            self.send('m-after-unsubscribe')

    def test_expiration_prevents_delivery(self):
        self.subscribe()
        self.now += 3601
        before = len(self.transport.calls)
        with self.assertRaises(hud.Rejected):
            self.send()
        self.assertEqual(len(self.transport.calls), before)

    def test_webhook_success_is_not_dot_receipt(self):
        self.subscribe()
        result = self.send()
        self.assertEqual(result['state'], 'webhook_accepted')
        self.assertFalse(result['dotAcknowledged'])
        self.assertIsNone(result['replyId'])
        event = self.transport.calls[-1][1]
        self.assertEqual(event['data']['source'], SOURCE)
        self.assertNotIn('instructions', event['data'])

    def test_signature_covers_exact_event_bytes(self):
        self.subscribe()
        self.send()
        _, _, headers, body = self.transport.calls[-1]
        signed = b'm-fixture.' + str(self.now).encode() + b'.' + body
        expected = 'v1,' + base64.b64encode(hmac.new(KEY, signed, hashlib.sha256).digest()).decode()
        self.assertTrue(hmac.compare_digest(headers['webhook-signature'], expected))

    def test_repeated_send_never_posts_again(self):
        self.subscribe()
        self.send()
        before = len(self.transport.calls)
        self.send()
        self.assertEqual(len(self.transport.calls), before)

    def test_duplicate_id_with_different_text_rejected(self):
        self.subscribe()
        self.send()
        with self.assertRaises(hud.Rejected):
            self.send(text='changed')

    def test_uncertain_send_is_not_retried(self):
        self.subscribe()
        self.transport.timeout_event = True
        self.assertEqual(self.send()['state'], 'uncertain')
        before = len(self.transport.calls)
        self.assertEqual(self.send()['state'], 'uncertain')
        self.assertEqual(len(self.transport.calls), before)

    def test_explicit_webhook_refusal_is_not_retried(self):
        self.subscribe()
        self.transport.event_status = 410
        self.assertEqual(self.send()['state'], 'webhook_refused')
        before = len(self.transport.calls)
        self.send()
        self.assertEqual(len(self.transport.calls), before)

    def test_ack_is_distinct_from_webhook_receipt(self):
        self.subscribe()
        self.send()
        result = self.adapter.ack('m-fixture')
        self.assertTrue(result['dotAcknowledged'])
        self.assertEqual(result['state'], 'dot_received')

    def test_fast_ack_is_not_overwritten(self):
        self.subscribe()
        self.transport.on_event = lambda _: self.adapter.ack('m-fixture')
        self.assertEqual(self.send()['state'], 'dot_received')

    def test_reply_is_correlated_and_delivered_only_once(self):
        self.subscribe()
        self.send()
        first = self.adapter.reply('m-fixture', 'ACK fixture marker')
        second = self.adapter.reply('m-fixture', 'ACK fixture marker')
        self.assertEqual(first['replyId'], second['replyId'])
        self.assertEqual(len(self.replies), 1)
        self.assertEqual(self.replies[0][0], SOURCE)
        self.assertFalse(first['nativeReceipt']['actualReceiptConfirmed'])

    def test_crash_reserved_reply_cannot_be_sent_twice(self):
        self.subscribe()
        self.send()
        with self.adapter.db() as db:
            db.execute('UPDATE messages SET reply_id=?,reply_text=?,state=? WHERE id=?',
                       ('m-reserved', 'ACK', 'reply_reserved', 'm-fixture'))
        result = self.adapter.reply('m-fixture', 'ACK')
        self.assertEqual(result['state'], 'reply_reserved')
        self.assertEqual(self.replies, [])

    def test_message_is_private_to_original_sender(self):
        self.subscribe()
        self.send()
        with self.assertRaises(hud.Rejected):
            self.adapter.receipt('m-fixture', OTHER)

    def test_local_role_cannot_act_as_dot(self):
        for method, params in [('events/subscribe', self.subscription()),
                               ('tools/call', {'name': 'hud_reply', 'arguments': {'id': 'x', 'text': 'x'}})]:
            with self.assertRaises(hud.Rejected):
                self.adapter.rpc('local', {'method': method, 'params': params})

    def test_dot_role_cannot_choose_codex_sender(self):
        with self.assertRaises(hud.Rejected):
            self.adapter.rpc('dot', {'method': 'tools/call', 'params': {
                'name': 'hud_send_to_dot', 'arguments': {'id': 'm-1', 'text': 'x'},
                '_meta': {'threadId': SOURCE[6:]}}})

    def test_catalog_and_initialize_advertise_events(self):
        result = self.adapter.rpc('dot', {'method': 'initialize'})
        self.assertIn('events', result['capabilities'])
        event = self.adapter.rpc('dot', {'method': 'events/list'})['events'][0]
        self.assertEqual(event['delivery'], ['webhook'])
        self.assertEqual(event['name'], hud.EVENT)

    def test_status_exposes_no_callback_or_secret(self):
        request = {'method': 'tools/call', 'params': {'name': 'hud_dot_status', 'arguments': {}}}
        before = json.loads(self.adapter.rpc('local', request)['content'][0]['text'])
        self.assertFalse(before['subscribed'])
        self.subscribe()
        after = json.loads(self.adapter.rpc('local', request)['content'][0]['text'])
        self.assertTrue(after['subscribed'])
        self.assertNotIn('callback', after)
        self.assertNotIn('secret', after)

    def test_message_id_cannot_inject_headers(self):
        self.subscribe()
        before = len(self.transport.calls)
        with self.assertRaises(hud.Rejected):
            self.send(message='m-bad\r\nInjected: header')
        self.assertEqual(len(self.transport.calls), before)


class AddressTests(unittest.TestCase):
    def resolver(self, address):
        return lambda *_, **__: [(2, 1, 6, '', (address, 443))]

    def test_private_and_special_addresses_rejected(self):
        for address in ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '224.0.0.1']:
            with self.subTest(address=address), self.assertRaises(hud.Rejected):
                hud.public_callback('https://example.test/callback', self.resolver(address))

    def test_public_address_pinned(self):
        parts, address = hud.public_callback('https://example.test/callback', self.resolver('93.184.216.34'))
        self.assertEqual(parts.hostname, 'example.test')
        self.assertEqual(address, '93.184.216.34')

    def test_fake_ip_rejected_with_specific_safe_reason(self):
        with self.assertRaises(hud.Rejected) as caught:
            hud.public_callback('https://example.test/private-path', self.resolver('198.18.0.7'))
        self.assertEqual(caught.exception.reason, 'callback_fake_ip_address')
        self.assertNotIn('private-path', str(caught.exception))

    def test_dns_failure_is_distinct_from_non_public_address(self):
        def unavailable(*_, **__):
            raise OSError('private resolver details')
        with self.assertRaises(hud.Rejected) as caught:
            hud.public_callback('https://example.test/private-path', unavailable)
        self.assertEqual(caught.exception.reason, 'callback_dns_error')
        self.assertNotIn('private', str(caught.exception))

    def test_insecure_urls_rejected(self):
        for url in ['http://example.test', 'https://user:password@example.test',
                    'https://example.test:8443', 'https://example.test/#fragment']:
            with self.subTest(url=url), self.assertRaises(hud.Rejected):
                hud.public_callback(url, self.resolver('93.184.216.34'))

    def test_invalid_secret_rejected(self):
        for value in ['', 'whsec_bad', 'whsec_' + base64.b64encode(b'short').decode()]:
            with self.assertRaises(hud.Rejected):
                hud.signing_key(value)


class ProxyTransportTests(unittest.TestCase):
    proxy = 'http://127.0.0.1:7890'

    def dns_response(self, **extra):
        return dict({'Status': 0, 'Question': [{'name': 'callback.example.test.', 'type': 1}],
                     'Answer': [{'name': 'callback.example.test.', 'type': 5, 'data': 'target.example.test.'},
                                {'name': 'target.example.test.', 'type': 1, 'data': '93.184.216.34'}]}, **extra)

    def lookup(self, data, status=200):
        response = MagicMock(status=status)
        response.read.return_value = json.dumps(data).encode()
        connection = MagicMock()
        connection.getresponse.return_value = response
        with patch.object(hud.http.client, 'HTTPSConnection', return_value=connection):
            result = hud.doh_addresses('callback.example.test', self.proxy)
        return result, connection

    def test_only_explicit_loopback_proxy_without_credentials_allowed(self):
        self.assertEqual(hud.loopback_proxy(self.proxy), ('127.0.0.1', 7890))
        for value in ['http://remote.example:7890', 'http://10.0.0.1:7890',
                      'http://user:password@127.0.0.1:7890', 'https://127.0.0.1:7890',
                      'http://127.0.0.1:7890/private-path']:
            with self.subTest(value=value), self.assertRaises(hud.Rejected):
                hud.loopback_proxy(value)

    def test_trusted_dns_request_contains_only_hostname(self):
        result, connection = self.lookup(self.dns_response())
        self.assertEqual(result, ['93.184.216.34'])
        connection.set_tunnel.assert_called_once_with('cloudflare-dns.com', 443)
        args, kwargs = connection.request.call_args
        self.assertEqual(args[0], 'GET')
        self.assertIn('name=callback.example.test', args[1])
        self.assertEqual(kwargs, {'headers': {'Accept': 'application/dns-json'}})
        connection.close.assert_called_once()

    def test_unrelated_dns_answer_cannot_choose_callback_target(self):
        answer = [{'name': 'unrelated.example.test.', 'type': 1, 'data': '93.184.216.34'}]
        with self.assertRaises(hud.Rejected):
            self.lookup(self.dns_response(Answer=answer))

    def test_bad_dns_status_question_and_truncated_response_fail_closed(self):
        for data in [self.dns_response(Status=3), self.dns_response(TC=True),
                     self.dns_response(Question=[{'name': 'other.test.', 'type': 1}])]:
            with self.subTest(data=data), self.assertRaises(hud.Rejected):
                self.lookup(data)

    def test_public_dns_results_still_reject_fake_and_private_ips_before_connect(self):
        for address in ['198.18.0.7', '127.0.0.1', '10.0.0.1', '169.254.169.254']:
            with self.subTest(address=address), patch.object(hud, 'doh_addresses', return_value=[address]), \
                    patch.object(hud, 'pinned_https') as connect:
                with self.assertRaises(hud.Rejected):
                    hud.webhook_post('https://callback.example.test/private', b'private-body',
                                     {'webhook-signature': 'private-signature'}, proxy=self.proxy)
                connect.assert_not_called()

    def test_proxy_callback_uses_pinned_public_ip_without_system_dns(self):
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status, response.read.return_value = 202, b'{}'
        with patch.object(hud, 'doh_addresses', return_value=['93.184.216.34']), \
                patch.object(hud, 'pinned_https', return_value=connection) as connect, \
                patch.object(hud.socket, 'getaddrinfo', side_effect=AssertionError('system DNS not allowed')):
            result = hud.webhook_post('https://callback.example.test/private?cap=private', b'private-body',
                                     {'webhook-signature': 'private-signature'}, proxy=self.proxy)
        self.assertEqual(result, (202, b'{}'))
        connect.assert_called_once_with('callback.example.test', '93.184.216.34', self.proxy)
        connection.request.assert_called_once_with('POST', '/private?cap=private', body=b'private-body',
                                                   headers={'webhook-signature': 'private-signature'})

    def test_connect_uses_public_ip_and_tls_authenticates_original_host(self):
        transport, connection, raw, context = [MagicMock() for _ in range(4)]
        transport.sock = raw
        with patch.object(hud.http.client, 'HTTPConnection', return_value=transport) as proxy_connection, \
                patch.object(hud.http.client, 'HTTPSConnection', return_value=connection), \
                patch.object(hud.ssl, 'create_default_context', return_value=context):
            self.assertIs(hud.pinned_https('callback.example.test', '93.184.216.34', self.proxy), connection)
        proxy_connection.assert_called_once_with('127.0.0.1', 7890, timeout=10)
        transport.set_tunnel.assert_called_once_with('93.184.216.34', 443)
        context.wrap_socket.assert_called_once_with(raw, server_hostname='callback.example.test')
        self.assertIsNone(transport.sock)


class HttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        class StubAdapter:
            def rpc(self, role, request):
                return {'role': role, 'method': request.get('method')}
        self.audit = []
        self.adapter = StubAdapter()
        handler = hud.make_handler(self.adapter, 'L' * 32, 'D' * 32, self.audit.append)

        class OfflineHandler(handler):
            def send_response(self, status):
                self.status = status

            def send_header(self, *args):
                pass

            def end_headers(self):
                pass

            def send_error(self, status):
                self.status = status

        self.handler = object.__new__(OfflineHandler)
        self.handler.path = '/mcp'
        self.handler.headers = Message()
        self.handler.headers['Content-Type'] = 'application/json'
        self.handler.wfile = io.BytesIO()

    def request(self, token, value=None):
        self.handler.headers['Authorization'] = 'Bearer ' + token
        raw = json.dumps(value or {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'}).encode()
        self.handler.headers['Content-Length'] = str(len(raw))
        self.handler.rfile = io.BytesIO(raw)
        self.handler.do_POST()
        return self.handler.status

    def test_unknown_credential_rejected(self):
        self.assertEqual(self.request('X' * 32), 401)
        self.assertEqual(self.handler.wfile.getvalue(), b'')
        self.assertEqual(self.audit[-1]['httpStatus'], 401)
        self.assertEqual(self.audit[-1]['phase'], 'http_rejected')

    def test_dot_credential_has_dot_role(self):
        self.assertEqual(self.request('D' * 32), 200)
        result = json.loads(self.handler.wfile.getvalue())
        self.assertEqual(result['result']['role'], 'dot')

    def test_local_credential_has_local_role(self):
        self.assertEqual(self.request('L' * 32), 200)
        result = json.loads(self.handler.wfile.getvalue())
        self.assertEqual(result['result']['role'], 'local')

    def test_browser_origin_rejected(self):
        self.handler.headers['Origin'] = 'https://unrelated.example'
        self.assertEqual(self.request('D' * 32), 403)

    def test_unsafe_token_configuration_rejected(self):
        with self.assertRaises(hud.Rejected):
            hud.make_handler(None, 'same' * 8, 'same' * 8)

    def test_notifications_have_no_json_response(self):
        self.assertEqual(self.request('D' * 32, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}), 202)
        self.assertEqual(self.handler.wfile.getvalue(), b'')

    def test_absent_oauth_metadata_is_not_found_for_both_tunnel_candidates(self):
        for path in ('/.well-known/oauth-protected-resource/mcp',
                     '/.well-known/oauth-protected-resource'):
            with self.subTest(path=path):
                self.handler.path = path
                self.handler.do_GET()
                self.assertEqual(self.handler.status, 404)
                self.assertEqual(self.handler.wfile.getvalue(), b'')

    def test_mcp_get_still_does_not_open_event_stream(self):
        self.handler.do_GET()
        self.assertEqual(self.handler.status, 405)

    def test_unknown_get_is_not_found(self):
        self.handler.path = '/unrelated'
        self.handler.do_GET()
        self.assertEqual(self.handler.status, 404)

    def test_diagnostic_cannot_serialize_caller_content(self):
        value = {'jsonrpc': '2.0', 'id': 'private-id', 'method': 'tools/call',
                 'params': {'text': 'private-message', 'secret': 'private-secret',
                            'url': 'https://private-callback.invalid/secret'}}
        self.request('D' * 32, value)
        self.assertEqual([r['phase'] for r in self.audit], ['received', 'completed'])
        serialized = json.dumps(self.audit)
        self.assertNotIn('private', serialized)
        self.assertNotIn('params', serialized)
        self.assertNotIn('Authorization', serialized)

    def test_unknown_method_does_not_enter_diagnostic_verbatim(self):
        self.request('D' * 32, {'jsonrpc': '2.0', 'id': 1, 'method': 'private-sensitive-method'})
        self.assertEqual(self.audit[0]['method'], 'unknown')
        self.assertNotIn('private', json.dumps(self.audit))

    def test_callback_error_data_and_audit_are_categorized(self):
        with patch.object(self.adapter, 'rpc', side_effect=hud.Rejected(
                'Callback verification failed', -32015, reason='callback_timeout')):
            self.request('D' * 32, {'jsonrpc': '2.0', 'id': 1, 'method': 'events/subscribe'})
        result = json.loads(self.handler.wfile.getvalue())
        self.assertEqual(result['error']['data'], {'reason': 'callback_timeout'})
        self.assertEqual(self.audit[-1]['reason'], 'callback_timeout')
        self.assertEqual(self.audit[-1]['phase'], 'rejected')


if __name__ == '__main__':
    unittest.main(verbosity=2)
