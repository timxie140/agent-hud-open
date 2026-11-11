#!/usr/bin/env python3
"""Validate two Actions artifacts and prepare a release directory offline."""
import argparse
import hashlib
import json
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

VERSION = '0.6.1-dot.1'


def fail(message):
    raise ValueError(message)


def entries(archive):
    found = {}
    for info in archive.infolist():
        name = info.orig_filename
        parts = name.split('/')
        if (not name or '\x00' in name or ':' in name or '\\' in name or name.startswith('/') or
                any(p in ('', '.', '..') for p in (parts[:-1] if info.is_dir() else parts)) or
                re.match(r'^[A-Za-z]:', name) or stat.S_ISLNK(info.external_attr >> 16)):
            fail('Unsafe archive entry')
        if info.is_dir():
            continue
        basename = PurePosixPath(name).name
        if basename in found:
            fail('Duplicate archive basename: ' + basename)
        found[basename] = info
    return found


def digest(stream):
    h = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(chunk)
    return h.hexdigest()


def validate(path, kind, revision):
    archive = zipfile.ZipFile(path)
    try:
        files = entries(archive)
        def read(name):
            if name not in files:
                fail('Missing artifact file: ' + name)
            return archive.read(files[name])
        provenance = json.loads(read('provenance.json'))
        if provenance.get('revision') != revision or provenance.get('signed') is not False:
            fail(kind + ' provenance does not match revision or unsigned status')
        if kind == 'windows':
            selected = [n for n in files if n.endswith('-setup.exe')]
            if len(selected) != 1:
                fail('Expected one Windows installer')
        else:
            zips = [n for n in files if n.endswith('.zip')]
            dmgs = [n for n in files if n.endswith('.dmg')]
            arch = provenance.get('architecture')
            if (provenance.get('platform') != 'macOS' or arch not in ('arm64', 'x86_64')
                    or len(zips) != 1 or len(dmgs) != 1):
                fail('Invalid macOS architecture or packages')
            dmg_arch = {'arm64': 'aarch64', 'x86_64': 'x64'}[arch]
            if not zips[0].endswith('-' + arch + '.zip') or not dmgs[0].endswith('_' + dmg_arch + '.dmg'):
                fail('macOS package architecture does not match provenance')
            selected = zips + dmgs
        sums = {}
        for line in read('SHA256SUMS').decode('utf-8-sig').splitlines():
            match = re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(.+)', line)
            if not match:
                fail('Invalid SHA256SUMS entry')
            checksum_path = match.group(2)
            if (checksum_path.startswith('/') or '\\' in checksum_path or ':' in checksum_path or '\x00' in checksum_path or
                    re.match(r'^[A-Za-z]:', checksum_path) or
                    any(part in ('', '.', '..') for part in checksum_path.split('/'))):
                fail('Unsafe or duplicate checksum entry')
            name = PurePosixPath(checksum_path).name
            if name in sums:
                fail('Unsafe or duplicate checksum entry')
            sums[name] = match.group(1).lower()
        for name, expected in sums.items():
            if name not in files:
                fail('Checksummed file missing: ' + name)
            with archive.open(files[name]) as stream:
                if digest(stream) != expected:
                    fail('Checksum mismatch: ' + name)
        if any(name not in sums for name in selected):
            fail('A release package lacks a checksum')
        read('dot-setup.md')
        return archive, files, selected, provenance
    except Exception:
        archive.close()
        raise


def prepare(windows, macos, revision, output):
    if not re.fullmatch(r'[0-9a-fA-F]{40}', revision):
        fail('Revision must be 40 hexadecimal characters')
    if output.exists():
        fail('Output directory already exists')
    wa, wf, ws, wp = validate(windows, 'windows', revision)
    try:
        ma, mf, ms, mp = validate(macos, 'macos', revision)
        try:
            if wa.read(wf['dot-setup.md']) != ma.read(mf['dot-setup.md']):
                fail('Tutorial differs between artifacts')
            names = ws + ms + ['dot-setup.md', 'windows-provenance.json',
                               'macos-provenance.json', 'manifest.json', 'SHA256SUMS']
            if len(set(names)) != len(names):
                fail('Output filenames collide')
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.dot-release-', dir=output.parent) as temp:
                folder = Path(temp) / 'release'
                folder.mkdir()
                for archive, files, selected in ((wa, wf, ws + ['dot-setup.md']), (ma, mf, ms)):
                    for name in selected:
                        with archive.open(files[name]) as source, (folder / name).open('wb') as dest:
                            shutil.copyfileobj(source, dest)
                for name, value in [('windows-provenance.json', wp), ('macos-provenance.json', mp),
                                    ('manifest.json', {'version': VERSION, 'revision': revision})]:
                    (folder / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
                lines = []
                for path in sorted(folder.iterdir()):
                    with path.open('rb') as stream:
                        lines.append(digest(stream) + '  ' + path.name)
                (folder / 'SHA256SUMS').write_text('\n'.join(lines) + '\n', encoding='utf-8')
                folder.rename(output)
        finally:
            ma.close()
    finally:
        wa.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--windows', required=True, type=Path)
    parser.add_argument('--macos', required=True, type=Path)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        prepare(args.windows, args.macos, args.revision, args.out)
    except (ValueError, OSError, zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as error:
        parser.exit(1, 'Release preparation failed: ' + str(error) + '\n')
    print('Release files prepared: ' + str(args.out))


if __name__ == '__main__':
    main()
