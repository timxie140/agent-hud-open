import json
import unittest
import hud_dot as hud
import dot_receipts as receipts
import test_hud_dot as fixtures


class ReceiptTests(unittest.TestCase):
    subscription = fixtures.EventTests.subscription
    subscribe = fixtures.EventTests.subscribe
    send = fixtures.EventTests.send
    tearDown = fixtures.EventTests.tearDown

    def setUp(self):
        fixtures.EventTests.setUp(self)
        self.adapter.sink = hud.native_reply
        self.subscribe()
        self.send()
        self.reply = self.adapter.reply('m-fixture', 'ACK fixture')

    def test_return_is_pending_until_existing_hud_delivery_owner_claims(self):
        self.assertEqual(self.reply['nativeReceipt']['state'], 'pending_hud')
        self.assertFalse(self.reply['recipientConfirmed'])
        pending = receipts.pending(self.adapter)
        self.assertEqual(pending[0]['replyId'], self.reply['replyId'])

    def test_native_send_claim_is_durable_and_never_retried(self):
        first = receipts.claim(self.adapter, 'm-fixture')
        self.assertTrue(first['claimed'])
        self.assertFalse(receipts.claim(self.adapter, 'm-fixture')['claimed'])
        self.assertEqual(receipts.pending(self.adapter), [])

    def test_native_acceptance_does_not_confirm_actual_receipt(self):
        receipts.claim(self.adapter, 'm-fixture')
        result = receipts.complete(self.adapter, 'm-fixture',
                                   {'state': 'accepted', 'actualReceiptConfirmed': True})
        self.assertFalse(result['recipientConfirmed'])
        self.assertFalse(result['nativeReceipt']['actualReceiptConfirmed'])

    def test_explicit_receiver_confirmation_posts_one_non_chat_receipt(self):
        result = receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE)
        self.assertTrue(result['recipientConfirmed'])
        event = self.transport.calls[-1][1]
        self.assertEqual(event['data']['kind'], 'delivery_receipt')
        self.assertIn(self.reply['replyId'], event['data']['text'])
        before = len(self.transport.calls)
        receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE)
        self.assertEqual(len(self.transport.calls), before)

    def test_other_thread_cannot_confirm(self):
        before = len(self.transport.calls)
        with self.assertRaises(hud.Rejected):
            receipts.confirm(self.adapter, self.reply['replyId'], fixtures.OTHER)
        self.assertEqual(len(self.transport.calls), before)
        self.assertFalse(self.adapter.receipt('m-fixture')['recipientConfirmed'])

    def test_query_never_confirms_receipt_or_sends_notification(self):
        before = len(self.transport.calls)
        result = self.adapter.rpc('dot', {'method': 'tools/call', 'params': {
            'name': 'hud_get_delivery_status', 'arguments': {'id': 'm-fixture'}}})
        self.assertFalse(json.loads(result['content'][0]['text'])['recipientConfirmed'])
        self.assertEqual(len(self.transport.calls), before)

    def test_dot_cannot_call_internal_confirmation(self):
        with self.assertRaises(hud.Rejected):
            self.adapter.rpc('dot', {'method': 'hud/internal/confirm', 'params': {
                'id': self.reply['replyId'], 'source': fixtures.SOURCE}})

    def test_receipt_is_not_a_message_that_can_be_acknowledged_or_replied(self):
        receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE)
        event_id = self.transport.calls[-1][1]['eventId']
        with self.assertRaises(hud.Rejected):
            self.adapter.reply(event_id, 'no loop')

    def test_notification_failure_keeps_proof_without_automatic_retry(self):
        self.transport.timeout_event = True
        result = receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE)
        self.assertTrue(result['recipientConfirmed'])
        self.assertEqual(result['deliveryReceiptState'], 'uncertain')
        before = len(self.transport.calls)
        receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE)
        self.assertEqual(len(self.transport.calls), before)

    def test_completed_native_return_cannot_be_overwritten(self):
        receipts.claim(self.adapter, 'm-fixture')
        receipts.complete(self.adapter, 'm-fixture', {'state': 'refused'})
        with self.assertRaises(hud.Rejected):
            receipts.complete(self.adapter, 'm-fixture', {'state': 'accepted'})


if __name__ == '__main__':
    unittest.main()
