"""Build a code-only candidate. It is NOT an installer or Golden image."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

root = Path(__file__).resolve().parents[2]
revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
dist = root / 'dist'
dist.mkdir(exist_ok=True)
output = dist / ('core-vm-' + revision + '.tar.gz')
files = {}
for source, target in ((root / 'backend' / 'app', Path('backend/app')),
                       (root / 'frontend' / 'dist', Path('backend/app/static'))):
    if not source.is_dir():
        raise SystemExit('Missing application or built frontend')
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise SystemExit('Symlinks are not allowed in VM candidates')
        if not path.is_file() or any(p in ('__pycache__', '.pytest_cache') for p in path.parts):
            continue
        relative = path.relative_to(source)
        if target == Path('backend/app') and relative.parts[0] == 'static':
            continue
        if path.suffix in ('.pyc', '.key', '.pem') or path.name == '.env':
            raise SystemExit('Unexpected generated or private file in application')
        files[(target / relative).as_posix()] = path
requirements = root / 'backend' / 'requirements.txt'
files['backend/requirements.txt'] = requirements
manifest = {
    'revision': revision,
    'kind': 'code-only-vm-candidate',
    'requirements_sha256': hashlib.sha256(requirements.read_bytes()).hexdigest(),
    'files': {name: hashlib.sha256(path.read_bytes()).hexdigest()
              for name, path in sorted(files.items())},
    'not_deployable_without': [
        'paired digital revision and integration tests',
        'Golden/firstboot/bootstrap revision coordination',
        'drain, backup, rollback and protected deployment approval'
    ]
}
manifest_path = dist / ('core-vm-' + revision + '.json')
manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
with tarfile.open(output, 'w:gz') as bundle:
    for name, path in sorted(files.items()):
        bundle.add(path, arcname=name, recursive=False)
checksum = hashlib.sha256(output.read_bytes()).hexdigest()
output.with_suffix(output.suffix + '.sha256').write_text(checksum + '  ' + output.name + '\n')
print('Created code-only candidate for', revision)
