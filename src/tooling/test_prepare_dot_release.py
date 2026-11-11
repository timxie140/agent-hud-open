import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('prepare_dot_release', Path(__file__).with_name('prepare-dot-release.py'))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
REVISION = 'a' * 40


def artifact(path, mac=False, revision=REVISION, bad_hash=False, extra=()):
    packages = ({'Agent-HUD-macOS-arm64.zip': b'app', 'Agent-HUD_aarch64.dmg': b'dmg'} if mac else
                {'target/release/bundle/nsis/HUD-setup.exe': b'exe'})
    sums = ''.join(('0' * 64 if bad_hash else hashlib.sha256(data).hexdigest()) + '  ' +
                   ('dot-release/' if mac else '') + Path(name).name + '\n'
                   for name, data in packages.items())
    provenance = {'revision': revision, 'signed': False}
    if mac:
        provenance['architecture'] = 'arm64'
        provenance['platform'] = 'macOS'
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in packages.items():
            archive.writestr(name, data)
        prefix = '' if mac else 'target/release/bundle/nsis/'
        archive.writestr(prefix + 'provenance.json', json.dumps(provenance))
        archive.writestr(prefix + 'SHA256SUMS', sums)
        archive.writestr('docs/dot-setup.md', 'instructions')
        for name, data in extra:
            info = zipfile.ZipInfo('placeholder')
            info.filename = name
            archive.writestr(info, data)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.win, self.mac, self.out = (self.base / n for n in ('win.zip', 'mac.zip', 'out'))
        artifact(self.win)
        artifact(self.mac, mac=True)

    def prepare(self):
        release.prepare(self.win, self.mac, REVISION, self.out)

    def test_valid_and_checksums(self):
        self.prepare()
        self.assertEqual(json.loads((self.out / 'manifest.json').read_text())['revision'], REVISION)
        self.assertEqual({p.name for p in self.out.iterdir()}, {'HUD-setup.exe', 'Agent-HUD-macOS-arm64.zip',
            'Agent-HUD_aarch64.dmg', 'dot-setup.md', 'windows-provenance.json', 'macos-provenance.json', 'manifest.json', 'SHA256SUMS'})
        for line in (self.out / 'SHA256SUMS').read_text().splitlines():
            value, name = line.split('  ', 1)
            self.assertEqual(value, hashlib.sha256((self.out / name).read_bytes()).hexdigest())
        with self.assertRaises(ValueError):
            self.prepare()

    def test_wrong_revision_and_checksum(self):
        for options in ({'revision': 'b' * 40}, {'bad_hash': True}):
            with self.subTest(options=options):
                artifact(self.mac, mac=True, **options)
                with self.assertRaises(ValueError):
                    self.prepare()
                self.assertFalse(self.out.exists())

    def test_unsafe_paths_and_duplicate_basename(self):
        for name in ('../escape', '/absolute', 'C:/drive', 'ads:stream', 'nested\\evil', 'elsewhere/provenance.json'):
            with self.subTest(name=name):
                artifact(self.win, extra=[(name, b'bad')])
                with self.assertRaises(ValueError):
                    self.prepare()
                self.assertFalse(self.out.exists())

    def test_symlink_rejected(self):
        info = zipfile.ZipInfo('link')
        info.create_system = 3
        info.external_attr = (0o120777 << 16)
        with zipfile.ZipFile(self.win, 'a') as archive:
            archive.writestr(info, 'target')
        with self.assertRaises(ValueError):
            self.prepare()


if __name__ == '__main__':
    unittest.main()
