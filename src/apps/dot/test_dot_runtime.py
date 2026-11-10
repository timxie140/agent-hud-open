import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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
