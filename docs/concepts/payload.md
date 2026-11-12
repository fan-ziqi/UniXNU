# Boot payload

The payload is a FAT volume that becomes the ramdisk of the Android boot image. UniXNU reads the configuration from it, and DarwinBoot reads the kernel, the ADT and the optional trust cache from it.

For a Mu-Silicium initrd payload, embed `UniXNURamDiskDxe`, DiskIoDxe and the FAT driver in the firmware. They expose the payload volume before UniXNU reads its configuration. See [payload discovery](/porting/uefi-firmware#payload-discovery).

Boot arguments are stored in the payload's `EFI/UniXNU/unixnu.toml`. After changing them, run `./unixnu payload` and `./unixnu bootimg`, then boot the new image. See [apply boot arguments](/xnu/boot-arguments#apply-arguments) for precedence and inspection commands.

## Compressed initrd delivery

Firmware with `UniXNURamDiskDxe` UNIXFAT1 support can receive a compressed FAT
volume, including through a GKI `vendor_boot` ramdisk. Run
`scripts/pack-uefi-ramdisk.py INPUT OUTPUT --compressor /path/to/TianoCompress`.
The script uses standard UEFI compression, verifies a full host round trip,
and records the input and output hashes. The default Tiano codec is different.

The 64-byte little-endian envelope contains `UNIXFAT1`, version 1, header size,
stored size, expanded size and CRC32. The driver bounds the expanded volume at
512 MiB, decompresses it through `EFI_DECOMPRESS_PROTOCOL`, checks its size and
CRC, and publishes the result as a read-only block device. Plain FAT initrds
retain the existing path. The compressed input must fit the receiving partition
and its load-address window; decompression does not enlarge those limits.

A sheng device displayed the compressed test menu after flashing v4 UEFI to
`boot_b`, placing the compressed FAT in `vendor_boot_b`, and issuing a normal
reboot. This verifies menu discovery, not XNU execution or a cold power cycle.

## Volume layout

```
/EFI/UniXNU/unixnu.toml
/EFI/UniXNU/Payloads/kernel.macho
/EFI/UniXNU/Payloads/kernel.macho.adt
/EFI/UniXNU/Payloads/kernel.macho.trustcache
/EFI/UniXNU/Payloads/scratch-data.img
```

The payload step writes the volume with `mformat` and `mcopy`. Timestamps are fixed at 1980-01-01, so the volume is reproducible for the same inputs. The ADT contains a random seed, so two payload builds differ.

## Configuration

The payload step writes this configuration:

```toml
version = 1

[boot]
timeout = 3
default = "xnu"

[kits]
autoload = false

[[entry]]
id = "xnu"
title = "UniXNU"
type = "xnu"
path = "Payloads/kernel.macho"
initrd = "Payloads/scratch-data.img"
args = "-v serial=3"
```

`initrd` is present when a Data seed is supplied. `args` is the joined `[payload] kernel_args` and `--kernel-arg` values.

## ADT sidecar

Format 2 compiles `[device_tree] source` with the declared include paths. The common generator combines the hardware DTB, resolved OS/device properties, and payload inputs, then writes Apple node encoding. See [Device tree](/porting/device-tree).

Format 1 uses the board script named in `[payload.adt] tool`, with these arguments:

| Option | Source |
| --- | --- |
| `--output` | `Payloads/kernel.macho.adt` |
| `--dram-size` | `[payload] dram_size` |
| `--owned-memory-size` | `[payload.adt] owned_memory_size` |
| `--root-match-volume-uuid` | `[payload.adt] root_match_volume_uuid` |
| `--chip-id` | `[payload.adt] chip_id` |
| `--cpu-regs` | `[payload.adt] cpu_regs` |
| `--psci-method` | `[payload.adt] psci_method` |
| `--unique-chip-id` | `--unique-chip-id` or `UNIXNU_UNIQUE_CHIP_ID` |
| `--packed-data-ramdisk` | `[payload.adt] packed_data_ramdisk` |
| `--data-ramdisk` | a Data seed without packed delivery |
| `--trust-cache` | a trust cache bundle |
| `--owner-trust-cache` | an owner-signed bundle with the original caches and extra modules. It replaces `--trust-cache` and skips the board allow-list |
| `--ipad-identity` | `[payload.adt] ipad_identity` |

The ADT must reserve the following properties when the matching input exists:

| Property | Purpose |
| --- | --- |
| `/chosen/memory-map/RAMDisk` | DarwinBoot writes the ramdisk address and size |
| `/chosen/memory-map/PackedRAMDisk` | DarwinBoot writes the packed ramdisk address and size |
| `/chosen/memory-map/TrustCache` | DarwinBoot writes the trust cache address and size |
| `/chosen/darwinboot-memory-size` | Requests a contiguous window larger than 256 MiB |
| `/chosen/darwinboot-memory-excluded` | DarwinBoot writes the ranges of the window the kernel must not use (gaps between DRAM banks, memory the firmware keeps) and puts the usable byte count in `memSizeActual` |
| `/chosen/darwinboot-loader-inputs` | DarwinBoot writes two 32-byte records (payload RAM disk, initrd buffer): base, size, UEFI memory type, state, usable bytes |

DarwinBoot requires the placeholder to exist for every input it receives. A mismatch is `EFI_COMPROMISED_DATA`.

## Kernel arguments

The payload checks the command line before writing the volume:

- Every argument matches `[A-Za-z0-9_.\-]+` with an optional `=value` of `[A-Za-z0-9_.,\-]+`.
- An extra `--kernel-arg NAME=VALUE` replaces the board argument with the same name.
- The joined line is at most 1000 bytes. DarwinBoot copies it into a 1024-byte buffer.

The command line is stored in `unixnu.toml` as `args`. DarwinBoot copies it into `boot_args` without modification.

## Trust cache

The trust cache bundle is validated by DarwinBoot:

- A 32-bit count from 1 to 128.
- One offset table entry per cache.
- Every cache starts with version 2.
- Every entry is 24 bytes.
- Every hash type is 1 to 4.
- Hashes are sorted in ascending order.

The bundle is copied into the kernel window and its address and size replace the `TrustCache` placeholder.

An `--owner-trust-cache` bundle is copied without the `[payload] trust_cache_sha256` check. It carries the original caches and extra modules such as the GPU plugin.

## Data ramdisk

When the selected kernel configuration enables `CONFIG_XNU_OWNER_DATA_MOUNT`,
the payload requires `--data-ramdisk FILE` or `[build] data_ramdisk` in the local
build configuration. Without a generated `.config`, this check reads the
selected device defconfig. A persistent overlay still needs its original seed
to publish the Data volume; changing the seed is not a way to resume old Data.
Missing seeds stop packaging before the payload is written.

A Data seed can be delivered in two forms:

| Form | ADT placeholder | Behavior |
| --- | --- | --- |
| Dense | `RAMDisk` | DarwinBoot copies the whole image |
| Packed | `PackedRAMDisk` | DarwinBoot validates the `DBRDISK1` extent table and copies the extents |

The packed form carries a header with the magic `DBRDISK1`, version 1, the page size, the expanded size and an extent table of `(offset, length)` pairs. Omitted ranges are zeroed RAM.

`scripts/seed-data-grow.py` grows a packed seed to the tablet's storage. The kernel accepts a Data disk of up to 1 TiB, and above 2 GiB the typed provider keeps only the nonzero pages of the seed.

## Determinism

The boot image is deterministic for a given firmware volume, device tree and ramdisk. The ADT random seed makes each payload build differ. The payload report records the kernel, ADT, trust cache, Data seed and payload hashes.

## Next steps

- [Boot chain](/concepts/boot-chain) describes how the payload is consumed.
- [Boot configuration](/reference/boot-configuration) lists every `unixnu.toml` key.
- [Boot arguments](/xnu/boot-arguments) lists the kernel arguments.
