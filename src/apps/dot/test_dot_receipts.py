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

    def received(self):
        self.challenge = receipts.claim(self.adapter, 'm-fixture')['deliveryChallenge']
        receipts.complete(self.adapter, 'm-fixture', {'state': 'accepted'})

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
        self.received()
        result = receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE, getattr(self, 'challenge', 'not-from-input'))
        self.assertTrue(result['recipientConfirmed'])
        event = self.transport.calls[-1][1]
        self.assertEqual(event['data']['kind'], 'delivery_receipt')
        self.assertIn(self.reply['replyId'], event['data']['text'])
        before = len(self.transport.calls)
        receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE, getattr(self, 'challenge', 'not-from-input'))
        self.assertEqual(len(self.transport.calls), before)

    def test_other_thread_cannot_confirm(self):
        self.received()
        before = len(self.transport.calls)
        with self.assertRaises(hud.Rejected):
            receipts.confirm(self.adapter, self.reply['replyId'], fixtures.OTHER, getattr(self, 'challenge', 'not-from-input'))
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
        self.received()
        receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE, getattr(self, 'challenge', 'not-from-input'))
        event_id = self.transport.calls[-1][1]['eventId']
        with self.assertRaises(hud.Rejected):
            self.adapter.reply(event_id, 'no loop')

    def test_notification_failure_keeps_proof_without_automatic_retry(self):
        self.received()
        self.transport.timeout_event = True
        result = receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE, getattr(self, 'challenge', 'not-from-input'))
        self.assertTrue(result['recipientConfirmed'])
        self.assertEqual(result['deliveryReceiptState'], 'uncertain')
        before = len(self.transport.calls)
        receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE, getattr(self, 'challenge', 'not-from-input'))
        self.assertEqual(len(self.transport.calls), before)

    def test_confirmation_survives_expired_or_cancelled_subscription(self):
        for mode in ('expired', 'cancelled'):
            with self.subTest(mode=mode):
                # Reset the fixture between cases, including its isolated database.
                if mode == 'cancelled':
                    self.tearDown()
                    self.setUp()
                self.received()
                if mode == 'expired':
                    self.now += 3601
                else:
                    self.adapter.unsubscribe(self.subscription())
                before = len(self.transport.calls)
                for source, challenge in ((fixtures.OTHER, self.challenge),
                                          (fixtures.SOURCE, 'wrong-challenge')):
                    with self.assertRaises(hud.Rejected):
                        receipts.confirm(self.adapter, self.reply['replyId'], source, challenge)
                    self.assertFalse(self.adapter.receipt('m-fixture')['recipientConfirmed'])
                result = receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE, self.challenge)
                self.assertTrue(result['recipientConfirmed'])
                self.assertEqual(result['deliveryReceiptState'], 'notification_unavailable')
                self.assertTrue(self.adapter.receipt('m-fixture')['recipientConfirmed'])
                self.assertEqual(receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE, self.challenge), result)
                self.assertEqual(len(self.transport.calls), before)

    def test_completed_native_return_cannot_be_overwritten(self):
        receipts.claim(self.adapter, 'm-fixture')
        receipts.complete(self.adapter, 'm-fixture', {'state': 'refused'})
        with self.assertRaises(hud.Rejected):
            receipts.complete(self.adapter, 'm-fixture', {'state': 'accepted'})

    def test_explicit_no_expiration_survives_time_and_cannot_be_taken_over(self):
        result = self.adapter.subscribe(self.subscription(ttlMs=None))
        self.assertIsNone(result['refreshBefore'])
        self.now += 86400 * 365
        self.assertIsNotNone(self.adapter._subscription())
        with self.assertRaises(hud.Rejected):
            self.adapter.subscribe(self.subscription(url='https://callback.example.test/other'))

    def test_omitted_lifetime_keeps_finite_default(self):
        self.assertIsNotNone(self.adapter.subscribe(self.subscription())['refreshBefore'])
        for value in [0, -1, True, 'forever']:
            with self.subTest(value=value), self.assertRaises(hud.Rejected):
                self.adapter.subscribe(self.subscription(ttlMs=value))

    def test_query_cannot_confirm_a_reply_that_hud_has_not_sent_or_refused(self):
        with self.assertRaises(hud.Rejected):
            receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE, getattr(self, 'challenge', 'not-from-input'))
        receipts.claim(self.adapter, 'm-fixture')
        receipts.complete(self.adapter, 'm-fixture', {'state': 'refused', 'reasonCode':'pass_limit'})
        with self.assertRaises(hud.Rejected):
            receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE, getattr(self, 'challenge', 'not-from-input'))
        self.assertFalse(self.adapter.receipt('m-fixture')['recipientConfirmed'])


    def test_query_never_exposes_delivery_challenge_and_wrong_challenge_is_rejected(self):
        self.received()
        result = self.adapter.receipt('m-fixture')
        self.assertNotIn(self.challenge, json.dumps(result))
        self.assertNotIn('delivery_challenge_hash', result)
        with self.assertRaises(hud.Rejected):
            receipts.confirm(self.adapter, self.reply['replyId'], fixtures.SOURCE, 'not-from-input')
        self.assertFalse(self.adapter.receipt('m-fixture')['recipientConfirmed'])


if __name__ == '__main__':
    unittest.main()
