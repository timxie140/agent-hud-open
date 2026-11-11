import json
import unittest
from pathlib import Path
from unittest.mock import patch
import hud_dot as hud
import dot_sessions as sessions
import dot_receipts as receipts
import test_hud_dot as fixtures

TARGET = fixtures.SOURCE.removeprefix('codex:')
OTHER = fixtures.OTHER.removeprefix('codex:')


class SessionTests(unittest.TestCase):
    tearDown = fixtures.EventTests.tearDown
    subscription = fixtures.EventTests.subscription
    subscribe = fixtures.EventTests.subscribe

    def setUp(self):
        fixtures.EventTests.setUp(self)
        self.subscribe()
        self.publish()
        self.host = sessions.inventory(self.adapter)['host']['id']

    def publish(self, enabled=True):
        return sessions.publish(self.adapter, {'enabled': enabled, 'platform': sessions.PLATFORM,
            'sessions': [{'id': TARGET, 'client': 'codex', 'title': 'Existing chat', 'state': 'running',
                          'cwd': '/private-fixture-path', 'runtimeApiKey': 'fixture-private-key'}]})

    def send(self, **patch):
        args = {'target': TARGET, 'text': 'isolated proactive marker',
                'request_id': 'isolated-request-0001', 'host': self.host}
        return sessions.send(self.adapter, **dict(args, **patch))

    def test_inventory_reports_platform_instance_and_exact_link_without_private_fields(self):
        value = sessions.inventory(self.adapter)
        self.assertEqual(value['host']['platform'], sessions.PLATFORM)
        self.assertIn(value['host']['label'], ('Mac', 'Windows'))
        self.assertEqual(value['sessions'][0]['url'], 'codex://threads/' + TARGET)
        self.assertNotIn('private', json.dumps(value))
        second = hud.Adapter(self.adapter.database, post=self.transport, clock=lambda: self.now,
                             encrypt=lambda x: x, decrypt=lambda x: x)
        self.assertEqual(sessions.host_id(second), self.host)

    def test_selected_link_is_bound_to_existing_session_and_this_machine(self):
        result = self.send(target='codex://threads/' + TARGET)
        self.assertEqual(result['origin'], 'dot')
        self.assertIsNone(result['replyId'])
        self.assertEqual(result['transportState'], 'pending_hud')
        self.assertFalse(result['recipientConfirmed'])
        pending = receipts.pending(self.adapter)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['origin'], 'dot')
        self.assertEqual(pending[0]['source'], fixtures.SOURCE)
        for patch in [{'host': 'another-host'}, {'target': OTHER}, {'target': 'codex://threads/' + TARGET + '?wrong=1'}]:
            with self.subTest(patch=patch), self.assertRaises(hud.Rejected):
                self.send(request_id='another-request-0002', **patch)

    def test_mac_and_windows_can_offer_the_same_chat_but_cannot_cross_route(self):
        other_platform = 'windows' if sessions.PLATFORM == 'macos' else 'macos'
        with patch.object(sessions, 'PLATFORM', other_platform):
            second = hud.Adapter(Path(self.directory.name) / 'other-machine.sqlite', post=self.transport,
                clock=lambda: self.now, encrypt=lambda x: x, decrypt=lambda x: x)
            second.subscribe(self.subscription())
            sessions.publish(second, {'enabled': True, 'platform': other_platform,
                'sessions': [{'id': TARGET, 'client': 'codex', 'title': 'same chat on other host'}]})
        other = sessions.inventory(second)['host']
        self.assertNotEqual(other['id'], self.host)
        self.assertEqual(other['platform'], other_platform)
        with self.assertRaises(hud.Rejected):
            sessions.send(second, TARGET, 'isolated marker', 'stable-request-001', self.host)
        own = self.send(request_id='stable-request-001', text='isolated marker')
        theirs = sessions.send(second, TARGET, 'isolated marker', 'stable-request-001', other['id'])
        self.assertNotEqual(own['id'], theirs['id'])
        with self.assertRaises(hud.Rejected):
            second.receipt(own['id'])

    def test_retry_is_receipt_only_after_claim_restart_and_uncertain_result(self):
        first = self.send()
        identifier = first['id']
        claim = receipts.claim(self.adapter, identifier)
        self.assertTrue(claim['claimed'])
        self.assertEqual(claim['origin'], 'dot')
        receipts.complete(self.adapter, identifier, {'state': 'uncertain'})
        for _ in range(2):
            self.assertEqual(self.send()['id'], identifier)
            self.assertEqual(self.send()['transportState'], 'uncertain')
            self.assertFalse(receipts.claim(self.adapter, identifier)['claimed'])
        with self.assertRaises(hud.Rejected):
            self.send(text='different payload')
        self.assertEqual(receipts.pending(self.adapter), [])

    def test_stale_or_disabled_inventory_and_guessed_or_child_sessions_cannot_send(self):
        self.now += sessions.REGISTRY_TTL + 1
        with self.assertRaises(hud.Rejected):
            self.send()
        self.publish(False)
        with self.assertRaises(hud.Rejected):
            self.send()
        self.publish()
        with self.assertRaises(hud.Rejected):
            self.send(target=OTHER)
        self.assertEqual(receipts.pending(self.adapter), [])

    def test_permission_revocation_rejects_unclaimed_proactive_requests_without_later_resend(self):
        sent = self.send()
        self.publish(False)
        self.assertEqual(self.adapter.receipt(sent['id'])['transportState'], 'refused')
        self.assertFalse(receipts.claim(self.adapter, sent['id'])['claimed'])
        self.publish(True)
        self.assertEqual(self.send()['transportState'], 'refused')
        self.assertEqual(receipts.pending(self.adapter), [])

    def test_only_local_owner_can_publish_and_dot_can_only_use_its_role_tools(self):
        for request in [
            {'method': 'hud/internal/sessions', 'params': {'enabled': True, 'sessions': []}},
            {'method': 'tools/call', 'params': {'name': 'hud_send_to_dot', 'arguments': {'id': 'm-spoof', 'text': 'x'}}},
        ]:
            with self.assertRaises(hud.Rejected):
                self.adapter.rpc('dot', request)
        with self.assertRaises(hud.Rejected):
            self.adapter.rpc('local', {'method': 'tools/call', 'params': {'name': 'hud_list_sessions'}})
        with self.assertRaises(hud.Rejected):
            sessions.publish(self.adapter, {'enabled': True, 'platform': sessions.PLATFORM,
                'sessions': [{'id': TARGET, 'client': 'claude'}]})
        with self.assertRaises(hud.Rejected):
            sessions.publish(self.adapter, {'enabled': True, 'platform': 'wrong-platform', 'sessions': []})

    def test_proactive_tools_require_host_and_match_an_offered_url(self):
        tools = self.adapter.rpc('dot', {'method': 'tools/list'})['tools']
        send_tool = next(tool for tool in tools if tool['name'] == 'hud_send_message')
        self.assertEqual(set(send_tool['inputSchema']['required']), {'host_id', 'session_id', 'text', 'request_id'})
        value = self.adapter.rpc('dot', {'method': 'tools/call', 'params': {'name': 'hud_send_message',
            'arguments': {'host_id': self.host, 'session_id': 'codex://threads/' + TARGET,
                          'text': 'isolated marker', 'request_id': 'rpc-send-0001'}}})
        result = json.loads(value['content'][0]['text'])
        self.assertEqual(result['origin'], 'dot')
        self.assertIsNone(result['replyText'])
        self.assertEqual(result['messageText'], 'isolated marker')

    def test_native_steer_feedback_is_separate_from_actual_receipt_and_does_not_ack_loop(self):
        sent = self.send()
        claim = receipts.claim(self.adapter, sent['id'])
        result = receipts.complete(self.adapter, sent['id'], {'state': 'accepted', 'deliveryMode': 'steered'})
        self.assertEqual(result['transportState'], 'steered')
        self.assertFalse(result['recipientConfirmed'])
        with self.assertRaises(hud.Rejected):
            receipts.confirm(self.adapter, sent['deliveryId'], fixtures.OTHER, claim['deliveryChallenge'])
        result = receipts.confirm(self.adapter, sent['deliveryId'], fixtures.SOURCE, claim['deliveryChallenge'])
        self.assertTrue(result['recipientConfirmed'])
        self.assertEqual(self.transport.calls[-1][1]['data']['kind'], 'delivery_receipt')
        before = len(self.transport.calls)
        self.send()
        receipts.confirm(self.adapter, sent['deliveryId'], fixtures.SOURCE, claim['deliveryChallenge'])
        self.assertEqual(len(self.transport.calls), before)
        with self.assertRaises(hud.Rejected):
            self.adapter.ack(sent['id'])
        with self.assertRaises(hud.Rejected):
            self.adapter.reply(sent['id'], 'no self reply')


if __name__ == '__main__':
    unittest.main()
