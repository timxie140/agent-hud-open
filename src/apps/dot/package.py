"""Freeze the native sidecar and bundle a pinned independent tunnel release."""
import argparse
import hashlib
import importlib.metadata
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


def copy_runtime_licenses(output):
    licenses = output / 'licenses'
    licenses.mkdir(exist_ok=True)
    python_license = next((path for path in (
        Path(sys.base_prefix) / 'LICENSE.txt', Path(sys.base_prefix) / 'LICENSE',
        Path(sys.base_prefix) / 'Resources/LICENSE.txt') if path.is_file()), None)
    if python_license is None:
        raise RuntimeError('Python runtime license missing')
    shutil.copyfile(python_license, licenses / 'Python-LICENSE.txt')
    # Include installed packager/dependency notices; no environment values or secrets.
    distributions = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata['Name']
        destination = licenses / name
        for entry in distribution.files or []:
            if Path(entry).name.lower().startswith(('license', 'copying', 'notice')):
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    destination.mkdir(exist_ok=True)
                    shutil.copyfile(source, destination / Path(entry).name)
        distributions.append({'name': name, 'version': distribution.version})
    (licenses / 'build-distributions.json').write_text(
        json.dumps(distributions, indent=2) + '\n', encoding='utf-8')


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
        copy_runtime_licenses(output)
        # Exercise the frozen executable with empty, isolated data. Never start listeners.
        helper = output / ('agent-hud-dot.exe' if sys.platform == 'win32' else 'agent-hud-dot')
        environment = dict(os.environ, AGENTHUD_DOT_DATA=str(temporary / 'smoke-data'))
        smoke = subprocess.run([str(helper), '--control-stdin'],
            input='{"action":"status","arguments":{}}', text=True, encoding='utf-8',
            capture_output=True, timeout=25, env=environment, check=True)
        result = json.loads(smoke.stdout).get('result', {})
        if result.get('enabled') is not False or result.get('running') is not False:
            raise RuntimeError('Frozen Dot runtime smoke check failed')
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
