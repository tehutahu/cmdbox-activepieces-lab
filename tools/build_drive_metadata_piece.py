"""Pinned public source -> ignored local bundle/archive. No AP installation.

Dependencies are restored separately with npm ci --ignore-scripts from the
reviewed lock; this command makes no dependency/version selection.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import hashlib
import gzip
import io
import json
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
PIN = 'd125d34e59ac57ea4d0df57af4b917344027f06b'
ROOTS = ('packages/pieces/framework/', 'packages/core/')


def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'cmdbox-public-pinned-piece-build'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--node', required=True)
    parser.add_argument('--dependencies', type=Path, required=True)
    parser.add_argument('--source-cache', type=Path, required=True)
    parser.add_argument('--tree-cache', type=Path)
    args = parser.parse_args()
    deps, source = args.dependencies.resolve(), args.source_cache.resolve()
    # Build/output caches must remain under this lab's ignored roots.
    ignored = [ROOT / 'runtimes', ROOT / 'local-review']
    assert any(source.is_relative_to(p) for p in ignored)
    assert any(deps.is_relative_to(p) for p in ignored)
    lock = ROOT / 'pieces/drive-metadata-search/build-dependencies.lock.json'
    assert lock.read_bytes() == (deps / 'package-lock.json').read_bytes(), 'Restore exact reviewed dependency lock'
    tree = json.loads(args.tree_cache.read_bytes() if args.tree_cache else get(
        'https://api.github.com/repos/activepieces/activepieces/git/trees/' + PIN + '?recursive=1'))
    assert tree.get('sha') == PIN and not tree.get('truncated'), 'Incomplete or wrong pinned tree'
    selected = [x for x in tree['tree'] if x['type'] == 'blob' and
                ((x['path'].startswith(ROOTS) and x['path'].endswith(('.ts', '.json'))) or x['path'] == 'LICENSE')]

    def fetch(entry):
        path = source / entry['path']
        data = path.read_bytes() if path.exists() else get(
            'https://raw.githubusercontent.com/activepieces/activepieces/' + PIN + '/' + entry['path'])
        blob_hash = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        assert blob_hash == entry['sha'], 'Pinned source differs: ' + entry['path']
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as output:
                output.write(data)
        return {'path': entry['path'], 'gitBlob': blob_hash, 'sha256': hashlib.sha256(data).hexdigest()}

    with ThreadPoolExecutor(max_workers=8) as pool:
        sources = list(pool.map(fetch, selected))
    review = ROOT / 'local-review' / ('drive-piece-build-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    review.mkdir(exist_ok=False)
    output = review / 'package'
    built = subprocess.run([args.node, str(ROOT / 'tools/bundle_drive_metadata_piece.mjs'), str(source), str(deps), str(output)],
                           check=True, capture_output=True, text=True, encoding='utf-8')
    print(built.stdout.strip())
    archive = review / 'cmdbox-lab-piece-drive-metadata-search-0.1.0.tgz'
    with archive.open('xb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as packed:
                for relative in ('package.json', 'src/index.js', 'THIRD-PARTY-NOTICES.txt'):
                    data = (output / relative).read_bytes()
                    info = tarfile.TarInfo('package/' + relative)
                    info.size, info.mode, info.mtime = len(data), 0o644, 0
                    packed.addfile(info, io.BytesIO(data))
    manifest = {'status': 'pass', 'pin': PIN, 'sources': sources, 'build': json.loads(built.stdout),
                'archiveSha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                'dependencyLockSha256': hashlib.sha256(lock.read_bytes()).hexdigest(), 'installedIntoAp': False}
    (review / 'build-manifest.json').write_bytes((json.dumps(manifest, indent=2) + '\n').encode())
    print(json.dumps({'buildDirectory': str(review), 'archiveSha256': manifest['archiveSha256'], 'installedIntoAp': False}))


if __name__ == '__main__':
    main()
