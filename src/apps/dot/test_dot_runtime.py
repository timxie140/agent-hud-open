import json
from pathlib import Path
import tempfile
import subprocess
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

import hud_dot as hud
import dot_runtime as runtime
import dot_storage as storage


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = patch.object(hud, 'ROOT', Path(self.directory.name))
        self.root.start()

    def tearDown(self):
        self.root.stop()
        self.directory.cleanup()

    def configure(self, **extra):
        return runtime.save_config(dict({'enabled': True, 'tunnelId': 'tunnel_fixture',
                                         'runtimeApiKey': 'fixture-runtime-key-not-a-credential',
                                         'proxy': 'http://127.0.0.1:7890'}, **extra))

    @unittest.skipUnless(runtime.sys.platform == 'win32', 'Windows DPAPI integration')
    def test_config_is_dpapi_encrypted_and_recovered_for_current_user(self):
        value = self.configure()
        raw = runtime.config_path().read_bytes()
        self.assertNotIn(value['runtimeApiKey'].encode(), raw)
        self.assertNotIn(value['localToken'].encode(), raw)
        self.assertEqual(runtime.load_config(), value)

    @unittest.skipUnless(runtime.sys.platform == 'win32', 'Windows DPAPI integration')
    def test_blank_key_preserves_existing_key_and_local_role_tokens(self):
        first = self.configure()
        second = self.configure(runtimeApiKey='')
        for name in ['runtimeApiKey', 'localToken', 'dotToken', 'instance']:
            self.assertEqual(first[name], second[name])

    def test_enabled_connection_requires_a_runtime_credential(self):
        with self.assertRaises(hud.Rejected):
            self.configure(runtimeApiKey='')

    def test_remote_proxy_or_embedded_proxy_credentials_rejected(self):
        for proxy in ['http://other.example:7890', 'http://user:password@127.0.0.1:7890']:
            with self.subTest(proxy=proxy), self.assertRaises(hud.Rejected):
                self.configure(proxy=proxy)

    def test_status_does_not_disclose_secrets_even_when_listener_is_down(self):
        value = {'enabled': True, 'tunnelId': 'tunnel_fixture', 'runtimeApiKey': 'private-runtime',
                 'localToken': 'private-local', 'dotToken': 'private-dot', 'proxy': ''}
        with patch.object(runtime, 'rpc', side_effect=OSError('private network details')):
            result = runtime.status(value)
        serialized = json.dumps(result)
        for secret in ['private-runtime', 'private-local', 'private-dot', 'private network details']:
            self.assertNotIn(secret, serialized)

    def test_readiness_does_not_claim_connection_while_control_plane_is_failing(self):
        (hud.ROOT / 'tunnel-health.url').write_text('http://127.0.0.1:1234')
        config = {'enabled': True, 'runtimeApiKey': 'fixture-only', 'proxy': ''}
        ready = MagicMock(status=200)
        health = MagicMock()
        health.read.return_value = b'{"components":{"control-plane":{"status":"degraded","state":"backing_off"}}}'
        connection = MagicMock()
        connection.getresponse.side_effect = [ready, health]
        with patch.object(runtime, 'rpc', return_value={'content':[{'text':'{"subscribed":true}'}]}), \
                patch.object(runtime.http.client, 'HTTPConnection', return_value=connection):
            result = runtime.status(config)
        self.assertTrue(result['running'])
        self.assertFalse(result['ready'])

    def test_macos_suggests_only_existing_loopback_system_proxy(self):
        output = 'HTTPEnable : 1\nHTTPProxy : 127.0.0.1\nHTTPPort : 7897\n'
        with patch.object(runtime.sys, 'platform', 'darwin'), \
                patch.dict(runtime.os.environ, {'HTTP_PROXY':'', 'HTTPS_PROXY':''}), \
                patch.object(runtime.subprocess, 'run', return_value=MagicMock(stdout=output)):
            self.assertEqual(runtime.suggested_proxy(), 'http://127.0.0.1:7897')

    @unittest.skipUnless(sys.platform in ('win32', 'darwin'), 'Native process-exit registration')
    def test_supervisor_watches_exact_owner_and_exits_without_starting_disabled_service(self):
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        with subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1.5)'],
                              creationflags=flags) as owner:
            started = time.monotonic()
            with patch.object(runtime.subprocess, 'Popen', side_effect=AssertionError('No service when disabled')):
                runtime.supervise(owner.pid)
            self.assertLess(time.monotonic() - started, 5)


class FakeKeychain:
    def __init__(self):
        self.values = {}

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, value):
        self.values[(service, account)] = value


class KeychainTests(unittest.TestCase):
    def test_keychain_configuration_and_blob_reference_never_write_plaintext(self):
        keychain = FakeKeychain()
        with tempfile.TemporaryDirectory() as folder, patch.object(storage, 'mac_keychain', return_value=keychain), \
                patch.object(storage.sys, 'platform', 'darwin'):
            root = Path(folder)
            secret = b'fixture-signing-material'
            reference = storage.mac_blob(secret, False, root)
            self.assertNotIn(secret, reference)
            self.assertEqual(storage.mac_blob(reference, True, root), secret)
            payload = b'{"runtimeApiKey":"fixture-runtime"}'
            storage.write_configuration(root, payload, lambda *_: self.fail('No DPAPI fallback on macOS'))
            self.assertEqual(storage.read_configuration(root, None), payload.decode())
            self.assertEqual([p.name for p in root.iterdir()], ['configured'])
            self.assertEqual((root / 'configured').read_bytes(), b'')

    def test_keychain_denial_has_no_file_fallback(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(storage, 'mac_keychain', side_effect=PermissionError()), \
                patch.object(storage.sys, 'platform', 'darwin'):
            root = Path(folder)
            with self.assertRaises(PermissionError):
                storage.write_configuration(root, b'not-to-disk', lambda *_: self.fail('No plaintext fallback'))
            self.assertEqual(list(root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
