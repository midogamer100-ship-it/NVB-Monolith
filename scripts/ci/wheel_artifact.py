"""Validate an offline CPython 3.12/Linux VM runtime artifact; never install it."""
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import PurePosixPath
import re
import zipfile

MAX_ARCHIVE = 512 * 1024 * 1024
MAX_WHEELS = 256


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def normalize(name):
    return re.sub('[-_.]+', '-', name).lower()


def pinned_requirements(raw):
    requirements = {}
    for line in raw.decode('utf-8').splitlines():
        line = line.partition('#')[0].strip()
        if not line:
            continue
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[A-Za-z0-9_,.-]+\])?==([A-Za-z0-9][A-Za-z0-9_.!+-]*)', line)
        require(match is not None, 'VM requirements must use exact package pins; URL/options/includes are unsupported')
        name, version = normalize(match[1]), match[2]
        require(name not in requirements, 'Duplicate direct VM dependency')
        requirements[name] = version
    require(requirements, 'No pinned VM runtime dependencies')
    return requirements


def wheel_metadata(filename, raw):
    require(isinstance(filename, str) and len(filename) <= 240
            and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.!+-]*\\.whl', filename), 'Invalid wheel filename')
    with zipfile.ZipFile(io.BytesIO(raw)) as wheel:
        entries = wheel.infolist()
        require(0 < len(entries) <= 100000 and sum(item.file_size for item in entries) <= 1024 * 1024 * 1024,
                'Expanded wheel exceeds size budget')
        seen = set()
        for item in entries:
            path = PurePosixPath(item.filename.rstrip('/'))
            require(not path.is_absolute() and '..' not in path.parts and '\\' not in item.filename
                    and path.as_posix() == item.filename.rstrip('/') and item.filename not in seen
                    and not any(ord(c) < 32 for c in item.filename)
                    and (item.external_attr >> 16) & 0o170000 != 0o120000,
                    'Unsafe or duplicate file in dependency wheel')
            seen.add(item.filename)
        metadata = [item for item in entries if re.fullmatch('[^/]+\\.dist-info/METADATA', item.filename)]
        require(len(metadata) == 1 and metadata[0].file_size <= 1024 * 1024, 'Wheel distribution metadata missing/oversized')
        message = BytesParser().parsebytes(wheel.read(metadata[0]))
        name, version = message.get('Name', ''), message.get('Version', '')
        require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*', name)
                and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.!+-]*', version), 'Invalid wheel distribution identity')
        require(normalize(filename.split('-', 1)[0]) == normalize(name), 'Wheel filename/distribution differ')
    return normalize(name), version


def manifest(revision, requirements, wheels):
    require(re.fullmatch('[0-9a-f]{40}', revision) and 0 < len(wheels) <= MAX_WHEELS, 'Invalid runtime source/wheel inventory')
    direct = pinned_requirements(requirements)
    packages = {}
    for filename, raw in wheels.items():
        name, version = wheel_metadata(filename, raw)
        require(name not in packages, 'More than one wheel for the same distribution')
        packages[name] = version
    require(all(packages.get(name) == version for name, version in direct.items()), 'Pinned runtime dependency missing or wrong version')
    return {'schema_version': 1, 'revision': revision, 'python': '3.12', 'platform': 'linux-x86_64',
            'requirements_sha256': sha(requirements), 'packages': packages,
            'files': {name: sha(raw) for name, raw in sorted(wheels.items())}}


def validate(package, revision, requirements, expected_zip_sha256):
    require(isinstance(package, bytes) and len(package) <= MAX_ARCHIVE and sha(package) == expected_zip_sha256,
            'GitHub offline-runtime ZIP digest/size differs')
    with zipfile.ZipFile(io.BytesIO(package)) as bundle:
        entries = bundle.infolist()
        require(1 < len(entries) <= MAX_WHEELS + 1 and len({item.filename for item in entries}) == len(entries)
                and sum(item.file_size for item in entries) <= MAX_ARCHIVE,
                'Unexpected runtime ZIP inventory/size')
        require('runtime.json' in {item.filename for item in entries}
                and bundle.getinfo('runtime.json').file_size <= 2 * 1024 * 1024,
                'Runtime inventory metadata missing/oversized')
        declared_raw = bundle.read('runtime.json')
        declared = json.loads(declared_raw)
        wheels = {}
        for item in entries:
            require(not item.is_dir() and not item.flag_bits & 1, 'Encrypted/directory runtime ZIP member')
            if item.filename == 'runtime.json':
                continue
            require('/' not in item.filename and '\\' not in item.filename and item.filename.endswith('.whl'),
                    'Unexpected offline-runtime member')
            wheels[item.filename] = bundle.read(item)
    actual = manifest(revision, requirements, wheels)
    require(declared == actual, 'Offline runtime metadata differs from verified package bytes')
    return {'revision': revision, 'zip_sha256': sha(package), 'requirements_sha256': sha(requirements),
            'manifest_sha256': sha(declared_raw), 'packages': actual['packages'], 'wheels': wheels}
