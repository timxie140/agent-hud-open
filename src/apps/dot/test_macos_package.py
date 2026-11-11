import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('mac_sign',
    Path(__file__).resolve().parents[2] / 'tooling/macos/sign-bundle.py')
signer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signer)


class SigningTests(unittest.TestCase):
    def test_resource_restore_repairs_flattened_framework_aliases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'frozen'
            (source / 'Python.framework/Versions/3.12/Resources').mkdir(parents=True)
            (source / 'Python.framework/Versions/3.12/Python').write_text('runtime')
            try:
                (source / 'Python.framework/Versions/Current').symlink_to('3.12', target_is_directory=True)
                # Path emits native separators in Windows reparse-point targets.
                (source / 'Python.framework/Python').symlink_to(Path('Versions/Current/Python'))
                (source / 'Python.framework/Resources').symlink_to(Path('Versions/Current/Resources'), target_is_directory=True)
            except OSError:
                self.skipTest('Host cannot create framework symlinks')
            app = root / 'Agent HUD.app'
            old = app / 'Contents/Resources/dot/Python.framework'
            old.mkdir(parents=True)
            (old / 'Python').write_text('flattened old runtime')
            (old / 'stale-library').write_text('stale')
            signer.restore_dot_runtime(app, source)
            self.assertTrue((old / 'Python').is_symlink())
            self.assertTrue((old / 'Resources').is_symlink())
            self.assertEqual((old / 'Python').read_text(), 'runtime')
            self.assertFalse((old / 'stale-library').exists())

    def test_macho_detection_uses_content_not_extension(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / 'extensionless'
            binary.write_bytes(bytes.fromhex('cffaedfe') + b'fixture')
            text = root / 'fake.dylib'
            text.write_text('not executable')
            self.assertTrue(signer.is_macho(binary))
            self.assertFalse(signer.is_macho(text))

    def test_aliases_are_not_signed_twice_and_cannot_escape_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / 'app'
            app.mkdir()
            binary = app / 'binary'
            binary.write_bytes(bytes.fromhex('cffaedfe'))
            try:
                (app / 'alias').symlink_to('binary')
            except OSError:
                self.skipTest('Host cannot create symlinks')
            self.assertEqual(signer.inventory(app)[0], [binary.resolve()])
            (root / 'outside').write_text('outside')
            (app / 'escape').symlink_to(root / 'outside')
            with self.assertRaisesRegex(RuntimeError, 'escapes'):
                signer.inventory(app)

    def test_libraries_and_frameworks_do_not_receive_app_entitlements(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(signer, 'run') as run:
                signer.sign(root / 'Python.framework', 'fixture', root)
                command = run.call_args.args[0]
                self.assertNotIn('--entitlements', command)
                self.assertNotIn('--options', command)
                self.assertNotIn('--deep', command)
                signer.sign(root / 'relay', 'fixture', root, {signer.JIT: True}, True)
                command = run.call_args.args[0]
                self.assertIn('runtime', command)
                self.assertIn('--entitlements', command)
                self.assertNotIn('--deep', command)
                self.assertEqual(plistlib.loads((root / 'entitlements.plist').read_bytes()),
                                 {signer.JIT: True})

    def test_unsigned_inputs_have_no_entitlements_but_inspection_errors_fail(self):
        from subprocess import CompletedProcess
        unsigned = CompletedProcess([], 1, b'', b'code object is not signed at all')
        denied = CompletedProcess([], 1, b'', b'permission denied')
        with patch.object(signer.subprocess, 'run', return_value=unsigned):
            self.assertEqual(signer.entitlements(Path('fixture')), {})
        with patch.object(signer.subprocess, 'run', return_value=denied):
            with self.assertRaises(RuntimeError):
                signer.entitlements(Path('fixture'))
