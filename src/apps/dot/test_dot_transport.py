"""Bounded native feedback, using the existing receipt database off line."""
import json
import time
import unittest
from unittest.mock import patch

import hud_dot as hud
import dot_receipts as receipts
import test_hud_dot as fixtures


class NativeFeedbackTests(unittest.TestCase):
    setUp = fixtures.EventTests.setUp
    tearDown = fixtures.EventTests.tearDown
    subscription = fixtures.EventTests.subscription
    subscribe = fixtures.EventTests.subscribe
    send = fixtures.EventTests.send

    def test_reply_returns_native_queue_or_steer_without_confirming(self):
        for mode in ('queued', 'steered', 'started', 'uncertain', 'refused'):
            with self.subTest(mode=mode):
                self.subscribe()
                message_id = 'm-' + mode
                self.send(message_id)
                self.adapter.sink = hud.native_reply
                self.adapter.native_reply_wait = 0.2

                def native_worker(_delay):
                    receipts.claim(self.adapter, message_id)
                    receipts.complete(self.adapter, message_id, {
                        'state': mode if mode in ('uncertain', 'refused') else 'accepted',
                        'deliveryMode': mode})

                with patch.object(hud.time, 'sleep', side_effect=native_worker):
                    result = self.adapter.reply(message_id, 'ACK isolated fixture')
                self.assertEqual(result['transportState'], mode)
                self.assertFalse(result['recipientConfirmed'])
                self.assertNotIn('deliveryChallenge', json.dumps(result))
                self.assertEqual(self.adapter.reply(message_id, 'ACK isolated fixture'), result)

    def test_unavailable_worker_times_out_without_second_send(self):
        self.subscribe()
        self.send()
        calls = []

        def sink(*args):
            calls.append(args)
            return hud.native_reply(*args)

        self.adapter.sink = sink
        self.adapter.native_reply_wait = 0.03
        start = time.monotonic()
        result = self.adapter.reply('m-fixture', 'ACK isolated fixture')
        self.assertLess(time.monotonic() - start, 0.5)
        self.assertEqual(result['transportState'], 'pending_hud')
        self.assertFalse(result['recipientConfirmed'])
        self.adapter.reply('m-fixture', 'ACK isolated fixture')
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
