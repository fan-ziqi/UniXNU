#!/usr/bin/env python3
"""Wrap a FAT initrd in standard UEFI compression for vendor_boot.

Requires UniXNURamDiskDxe with UNIXFAT1 support. TianoCompress --uefi is the
EDK II standard compressor, not the default Tiano-specific variant. The host
round-trip is checked before an output is published. vendor_boot still checks
the complete partition size and the board's load-address window.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib


def identity(path):
    sha, crc = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(8 << 20), b''):
            sha.update(data)
            crc = zlib.crc32(data, crc)
    return sha.hexdigest(), crc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--compressor', type=Path, required=True)
    args = parser.parse_args()
    size = args.input.stat().st_size
    if size < 512 or size > 512 * 2**20 or size % 512:
        parser.error('FAT image must be sector-aligned and at most 512 MiB')
    with args.input.open('rb') as source:
        if source.read(512)[510:512] != b'\x55\xaa':
            parser.error('input has no FAT boot-sector signature')
    if args.output.exists():
        parser.error('refuse to overwrite an existing packed initrd')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    digest, crc = identity(args.input)
    with tempfile.TemporaryDirectory(prefix='uefi-pack-', dir=args.output.parent) as td:
        work = Path(td)
        compressed, decoded = work / 'stream.bin', work / 'decoded.img'
        subprocess.run([args.compressor, '-e', '--uefi', '-o', compressed, args.input], check=True)
        subprocess.run([args.compressor, '-d', '--uefi', '-o', decoded, compressed], check=True)
        if decoded.stat().st_size != size or identity(decoded) != (digest, crc):
            raise SystemExit('UEFI compression round-trip differs from the input')
        data = compressed.read_bytes()
        if len(data) < 8 or struct.unpack_from('<II', data) != (len(data) - 8, size):
            raise SystemExit('compressor did not produce a standard UEFI stream')
        header = struct.pack('<8sIIQQII24s', b'UNIXFAT1', 1, 64, len(data), size, crc, 0, bytes(24))
        with args.output.open('xb') as target:
            target.write(header)
            target.write(data)
    report = dict(format='UNIXFAT1', codec='UEFI-standard', expanded_bytes=size,
                  stored_bytes=args.output.stat().st_size, input_sha256=digest,
                  output_sha256=identity(args.output)[0], crc32=f'{crc:08x}',
                  host_round_trip=True, hardware_tested=False)
    args.output.with_suffix(args.output.suffix + '.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
