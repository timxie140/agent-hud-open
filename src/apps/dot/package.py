"""Freeze the native sidecar and bundle a pinned independent tunnel release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

RELEASES = {
    ('win32', 'amd64'): ('windows-amd64', '1d0ecc3a54f2a51e27a635ac155f40fbb95df58c52cdeddf6c75532cc0bbeb25'),
    ('darwin', 'arm64'): ('darwin-arm64', '2243d024b77af8ee4b4ab7a1447949e5fc8d82bcd2d51b178927f2da9e47ecfd'),
    ('darwin', 'amd64'): ('darwin-amd64', 'dff97674c77cac59e6ab3d901e6cff50fb17a5784c01d8959d1f4adb3afdf4bf'),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    machine = platform.machine().lower()
    arch = 'arm64' if machine in ('arm64', 'aarch64') else 'amd64' if machine in ('amd64', 'x86_64') else machine
    target, expected = RELEASES[(sys.platform, arch)]
    output = Path(args.out).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='agent-hud-dot-build-') as temporary:
        temporary = Path(temporary)
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
            '--name', 'agent-hud-dot', '--distpath', str(temporary / 'dist'), '--workpath', str(temporary / 'work'),
            '--specpath', str(temporary), str(source / 'dot_runtime.py')], check=True, cwd=source)
        shutil.copytree(temporary / 'dist/agent-hud-dot', output, dirs_exist_ok=True)
        url = 'https://github.com/openai/tunnel-client/releases/download/v0.0.19/tunnel-client-v0.0.19-' + target + '.zip'
        archive = temporary / 'tunnel.zip'
        urllib.request.urlretrieve(url, archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Independent tunnel archive checksum mismatch')
        selected = []
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                name = Path(entry.filename).name
                if name in {'tunnel-client', 'tunnel-client.exe', 'LICENSE', 'NOTICE',
                            'THIRD-PARTY-LICENSES.txt', 'SBOM.spdx.json'}:
                    with bundle.open(entry) as incoming, (output / name).open('wb') as destination:
                        shutil.copyfileobj(incoming, destination)
                    selected.append(name)
        executable = output / ('tunnel-client.exe' if sys.platform == 'win32' else 'tunnel-client')
        if not executable.is_file():
            raise RuntimeError('Independent tunnel executable missing from archive')
        if sys.platform == 'darwin':
            executable.chmod(0o755)
        (output / 'provenance.json').write_text(json.dumps({
            'tunnelVersion': '0.0.19', 'target': target, 'archive': url,
            'archiveSha256': expected, 'bridgeRequired': False,
            'files': {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in selected},
        }, indent=2) + '\n', encoding='utf-8')
    print('Packaged standalone Dot runtime for ' + target)


if __name__ == '__main__':
    main()
