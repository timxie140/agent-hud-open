"""Sign a newly built Tauri app inside out; never drive Finder or clear xattrs."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile

MACHO_MAGIC = {bytes.fromhex(value) for value in (
    'feedface', 'cefaedfe', 'feedfacf', 'cffaedfe',
    'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}
JIT = 'com.apple.security.cs.allow-jit'


def run(command):
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        identity = os.environ.get('APPLE_SIGNING_IDENTITY', '')
        error = result.stderr.decode(errors='replace')
        if identity:
            error = error.replace(identity, '<local signing identity>')
        raise RuntimeError(Path(command[0]).name + ' failed: ' + error.strip())
    return result.stdout


def is_macho(path):
    if path.is_symlink() or not path.is_file():
        return False
    with path.open('rb') as source:
        return source.read(4) in MACHO_MAGIC


def inventory(app):
    """Do not follow aliases twice or permit code outside the new bundle."""
    app = app.resolve(strict=True)
    files, frameworks = [], []
    for path in app.rglob('*'):
        if path.is_symlink():
            if not path.resolve(strict=True).is_relative_to(app):
                raise RuntimeError('Bundle symlink escapes app: ' + str(path))
        elif path.is_dir() and path.suffix == '.framework':
            frameworks.append(path)
        elif is_macho(path):
            files.append(path)
    return sorted(files), sorted(frameworks, key=lambda p: (-len(p.parts), str(p)))


def entitlements(path):
    result = subprocess.run(['codesign', '-d', '--entitlements', ':-', str(path)],
                            capture_output=True)
    if result.returncode:
        # An unsigned input has no entitlements to preserve.
        if b'code object is not signed at all' in result.stderr:
            return {}
        raise RuntimeError('Cannot read input entitlements: ' + str(path))
    return plistlib.loads(result.stdout) if result.stdout.strip() else {}


def restore_dot_runtime(app, source):
    """Tauri's resource copier dereferences file aliases and drops directory aliases.

    Restore the frozen tree before any signing, preserving framework metadata.
    """
    source = source.resolve(strict=True)
    inventory(source)
    destination = app / 'Contents/Resources/dot'
    with tempfile.TemporaryDirectory(prefix='agent-hud-dot-layout-', dir=app.parent) as temporary:
        temporary = Path(temporary)
        staged, backup = temporary / 'dot', temporary / 'previous'
        shutil.copytree(source, staged, symlinks=True)
        destination.rename(backup)
        try:
            staged.rename(destination)
        except OSError:
            backup.rename(destination)
            raise


def sign(path, identity, temporary, values=None, executable=False):
    command = ['codesign', '--force', '--sign', identity, '--timestamp=none']
    if executable:
        command += ['--options', 'runtime']
    if values:
        profile = temporary / 'entitlements.plist'
        profile.write_bytes(plistlib.dumps(values))
        command += ['--entitlements', str(profile), '--generate-entitlement-der']
    run(command + [str(path)])


def sign_app(app, identity):
    app = app.resolve(strict=True)
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    main = app / 'Contents/MacOS' / info['CFBundleExecutable']
    files, frameworks = inventory(app)
    expected = set(run(['lipo', '-archs', str(main)]).decode().split())
    if not expected or main not in files:
        raise RuntimeError('Missing main Mach-O executable')
    required = ['agent-hud-engine', 'agent-hud-mcp', 'dot/agent-hud-dot', 'dot/tunnel-client']
    for relative in required:
        if app / 'Contents/Resources' / relative not in files:
            raise RuntimeError('Missing packaged component: ' + relative)
    # Validate all architectures and capture executable entitlements before mutation.
    records = []
    values = {}
    for path in files:
        arches = set(run(['lipo', '-archs', str(path)]).decode().split())
        if not expected.issubset(arches):
            raise RuntimeError('Incompatible nested architecture: ' + str(path))
        header = run(['otool', '-hv', str(path)]).decode()
        executable = bool(re.search(r'\bEXECUTE\b', header))
        values[path] = entitlements(path) if executable else {}
        if path == app / 'Contents/Resources/agent-hud-mcp':
            values[path][JIT] = True
        records.append({'path': str(path.relative_to(app)),
                        'architectures': sorted(arches), 'executable': executable})
    with tempfile.TemporaryDirectory(prefix='agent-hud-entitlements-') as temporary:
        temporary = Path(temporary)
        # Most deeply nested code first. The framework wrapper seals its libraries.
        targets = [(p, False) for p in files if p != main] + [(p, True) for p in frameworks]
        for path, framework in sorted(targets, key=lambda pair: (-len(pair[0].parts), str(pair[0]))):
            executable = next((r['executable'] for r in records
                               if r['path'] == str(path.relative_to(app))), False)
            sign(path, identity, temporary, None if framework else values[path], executable)
        sign(app, identity, temporary, values[main], executable=True)
    authority = None
    identity_type = None
    for path in [app] + files + frameworks:
        run(['codesign', '--verify', '--strict', str(path)])
        details = subprocess.run(['codesign', '-d', '--verbose=4', str(path)],
                                 capture_output=True, text=True)
        chain = [line for line in details.stderr.splitlines()
                 if line.startswith(('Authority=', 'TeamIdentifier='))]
        if path == app:
            authority = chain
            identity_type = next((line.removeprefix('Authority=').split(':', 1)[0]
                                  for line in chain if line.startswith('Authority=')), None)
        if details.returncode or not authority or chain != authority or 'Signature=adhoc' in details.stderr:
            raise RuntimeError('Component does not use requested identity: ' + str(path))
    if not entitlements(app / 'Contents/Resources/agent-hud-mcp').get(JIT):
        raise RuntimeError('MCP relay is missing JIT entitlement')
    for framework in frameworks:
        if entitlements(framework):
            raise RuntimeError('Framework must not carry executable entitlements')
    run(['codesign', '--verify', '--deep', '--strict', str(app)])
    return {'architecture': sorted(expected), 'machO': records,
            'frameworks': [str(p.relative_to(app)) for p in frameworks],
            'identityType': identity_type, 'strictDeepVerified': True,
            'notarized': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--dmg-dir', type=Path, required=True)
    parser.add_argument('--dot-resources', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise RuntimeError('Native macOS signing is required')
    identity = os.environ.get('APPLE_SIGNING_IDENTITY', '').strip()
    if not identity or identity == '-':
        raise RuntimeError('A real local signing identity is required; no ad-hoc fallback')
    app = args.app.resolve(strict=True)
    if app.parent.name != 'macos' or app.parent.parent.name != 'bundle':
        raise RuntimeError('Sign only the newly generated Tauri bundle output')
    restore_dot_runtime(app, args.dot_resources)
    result = sign_app(app, identity)
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    architecture = {'arm64': 'aarch64', 'x86_64': 'x64'}.get(
        ','.join(result['architecture']), 'universal')
    args.dmg_dir.mkdir(parents=True, exist_ok=True)
    dmg = args.dmg_dir / (f"Agent HUD_{info['CFBundleShortVersionString']}_{architecture}.dmg")
    # hdiutil packages the already signed app; no Finder, xattr or app mutation.
    with tempfile.TemporaryDirectory(prefix='agent-hud-dmg-') as temporary:
        staging = Path(temporary) / 'volume'
        staging.mkdir()
        run(['ditto', str(app), str(staging / app.name)])
        (staging / 'Applications').symlink_to('/Applications')
        run(['hdiutil', 'create', '-ov', '-format', 'UDZO', '-volname', 'Agent HUD',
             '-srcfolder', str(staging), str(dmg)])
        sign(dmg, identity, Path(temporary))
    run(['hdiutil', 'verify', str(dmg)])
    run(['codesign', '--verify', '--strict', str(dmg)])
    result.update(app=str(app), dmg=str(dmg))
    # Keep signing evidence outside the sealed bundle.
    (args.dmg_dir / 'local-signature.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Signed app and DMG; all nested Mach-O signatures verified (' + str(len(result['machO'])) + ' files).')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
