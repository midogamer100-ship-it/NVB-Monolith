"""Hosted Ubuntu CI: download pinned binary wheels for offline VM installation.

Produces dist/vm-runtime for a separate GitHub artifact. No credentials, cluster
calls, application execution or Golden construction.
"""
import json
import importlib.metadata
import os
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig
import tempfile

from wheel_artifact import MAX_ARCHIVE, manifest, normalize, pinned_requirements


def main():
    if sys.version_info[:2] != (3, 12) or platform.system() != 'Linux' or sysconfig.get_platform() != 'linux-x86_64':
        raise SystemExit('Runtime packaging requires CPython 3.12 on Linux x86_64')
    root = Path(__file__).resolve().parents[2]  # Installed as scripts/ci/package_runtime.py.
    requirements = (root / 'backend/requirements.txt').read_bytes()
    pinned_requirements(requirements)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    output = root / 'dist/vm-runtime'
    if output.exists():
        raise SystemExit('Runtime output already exists; preserve it and use a clean CI workspace')
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='nvb-runtime-') as temporary:
        # Constrain downloads to the versions in the SAME interpreter that just
        # ran the Core tests, including transitive dependencies. Never silently
        # resolve a newer transitive release between tests and packaging.
        installed = {}
        for distribution in importlib.metadata.distributions():
            name = distribution.metadata.get('Name')
            if name:
                name = normalize(name)
                if name in installed and installed[name] != distribution.version:
                    raise SystemExit('Ambiguous installed distribution versions')
                installed[name] = distribution.version
        constraints = Path(temporary) / 'constraints.txt'
        constraints.write_text(''.join(name + '==' + version + '\n' for name, version in sorted(installed.items())), encoding='utf-8')
        downloads = Path(temporary) / 'wheels'
        downloads.mkdir()
        clean = {key: value for key, value in os.environ.items() if not key.upper().startswith('PIP_')}
        clean.update(PIP_CONFIG_FILE='/dev/null', PIP_INDEX_URL='https://pypi.org/simple',
                     PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_NO_INPUT='1')
        subprocess.run([sys.executable, '-m', 'pip', 'download', '--no-cache-dir', '--only-binary=:all:',
                        '--constraint', str(constraints), '--dest', str(downloads), '-r', str(root / 'backend/requirements.txt')],
                       env=clean, check=True, timeout=900)
        files = {path.name: path.read_bytes() for path in downloads.iterdir() if path.is_file()}
        if sum(map(len, files.values())) > MAX_ARCHIVE - 2 * 1024 * 1024:
            raise SystemExit('Offline VM runtime exceeds artifact size budget')
        metadata = manifest(revision, requirements, files)
        for name, raw in files.items():
            (output / name).write_bytes(raw)
        (output / 'runtime.json').write_text(json.dumps(metadata, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print('Offline VM runtime packaged for ' + revision + '; distributions: ' + str(len(files)))


if __name__ == '__main__':
    main()
