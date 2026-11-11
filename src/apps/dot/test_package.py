import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('dot_package', Path(__file__).with_name('package.py'))
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class PackageOutputTests(unittest.TestCase):
    def test_repeat_build_replaces_tree_and_removes_stale_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'output'
            output.mkdir()
            (output / 'obsolete-library').write_text('old')
            for revision in ['one', 'two']:
                staged = root / ('staged-' + revision)
                staged.mkdir()
                (staged / 'runtime').write_text(revision)
                packager.replace_output(staged, output, root / ('backup-' + revision))
                self.assertEqual((output / 'runtime').read_text(), revision)
                self.assertFalse((output / 'obsolete-library').exists())

    def test_repeat_build_preserves_framework_aliases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'output'
            for revision in ['one', 'two']:
                staged = root / ('staged-' + revision)
                framework = staged / 'Python.framework'
                (framework / 'Versions/3.12').mkdir(parents=True)
                (framework / 'Versions/3.12/Python').write_text(revision)
                try:
                    (framework / 'Versions/Current').symlink_to('3.12', target_is_directory=True)
                    (framework / 'Python').symlink_to(Path('Versions/Current/Python'))
                except OSError:
                    self.skipTest('Host cannot create framework symlinks')
                packager.replace_output(staged, output, root / ('backup-' + revision))
                self.assertTrue((output / 'Python.framework/Python').is_symlink())
                self.assertEqual((output / 'Python.framework/Python').read_text(), revision)

    def test_publish_failure_restores_prior_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'output'
            output.mkdir()
            (output / 'runtime').write_text('original')
            # A missing staged tree models a failed final rename.
            with self.assertRaises(OSError):
                packager.replace_output(root / 'missing', output, root / 'previous')
            self.assertEqual((output / 'runtime').read_text(), 'original')
