#!/usr/bin/env python3
"""Exercise seed growth on macOS before downloading installation images."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'drivers/DarwinBoot/Test'))
import packed_ramdisk


def check_attachment_selection():
    spec = importlib.util.spec_from_file_location('grow_seed', ROOT / 'scripts/seed-data-grow.py')
    grow = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grow)
    # Production failure: disk10 (synthesized) appeared before disk9 (physical).
    listing = {'Containers': [
        {'ContainerReference': 'disk2', 'PhysicalStores': [{'DeviceIdentifier': 'disk0s2'}]},
        {'ContainerReference': 'disk10', 'PhysicalStores': [{'DeviceIdentifier': 'disk9'}]},
    ]}
    for attachment in ('/dev/disk10\tAPFS\n/dev/disk10s1\tVolume\n/dev/disk9\t\n',
                       '/dev/disk9\t\n/dev/disk10\tAPFS\n'):
        assert grow.container_for_attachment(listing, attachment) == ('disk10', 'disk9')
    for physical in ('disk9s1', 'disk9s1s2'):
        sliced = {'Containers': [{'ContainerReference': 'disk10',
                                  'PhysicalStores': [{'DeviceIdentifier': physical}]}]}
        assert grow.container_for_attachment(sliced, '/dev/disk9\t\n') == ('disk10', 'disk9')
    assert grow.container_for_attachment(listing, '/dev/disk90\t\n') == (None, 'disk90')
    ambiguous = {'Containers': listing['Containers'] + [
        {'ContainerReference': 'disk11', 'PhysicalStores': [{'DeviceIdentifier': 'disk10s2'}]}]}
    try:
        grow.container_for_attachment(ambiguous, '/dev/disk9\t\n/dev/disk10\t\n')
    except ValueError:
        pass
    else:
        raise AssertionError('Ambiguous attached containers must be rejected')
    print('APFS attachment selection checks passed', flush=True)


def main():
    check_attachment_selection()
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    spec = importlib.util.spec_from_file_location('make_seed', ROOT / 'scripts/make-macos-data-seed.py')
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    with tempfile.TemporaryDirectory(prefix='apfs-grow-check-', dir=build) as directory:
        work = Path(directory)
        raw = work / 'seed.cdr'
        subprocess.run(['hdiutil', 'create', '-size', '512m', '-layout', 'NONE', '-fs', 'APFS',
                        '-volname', 'SeedGrowCheck', '-type', 'UDTO', str(raw)], check=True)
        for mode in ('original-uuid', 'fixed-uuid'):
            if mode == 'fixed-uuid':
                seed.set_volume_uuid(raw, uuid.UUID('79157BD4-6A8C-45D6-A0EB-11FEA89BDE46'))
            base = work / f'{mode}.dbr'
            output = work / f'{mode}-grown.dbr'
            packed_ramdisk.pack(raw, base)
            subprocess.run([sys.executable, ROOT / 'scripts/seed-data-grow.py', '--gib', '3', base, output], check=True)
            logical, _ = packed_ramdisk.regions(output.read_bytes())
            if logical != 3 * 2**30:
                raise SystemExit(f'{mode}: unexpected logical size {logical}')
            print(f'APFS grow check passed: {mode}', flush=True)


if __name__ == '__main__':
    main()
