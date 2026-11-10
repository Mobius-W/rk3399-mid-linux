#!/usr/bin/env python3
"""AOSP boot.img (v0) 打包器 — 供 RK3399 vendor U-Boot 的 bootrk 流程使用。

vendor U-Boot 2014.10-RK3399 读的字段：magic / kernel_size / ramdisk_size /
second_size / page_size / cmdline；地址字段它用自己 env 里的 kernel_addr_r，
这里填合理默认值即可。
"""
import argparse
import hashlib
import struct

PAGE = 2048


def pad(data: bytes, page: int = PAGE) -> bytes:
    return data + b"\0" * ((-len(data)) % page)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--ramdisk", default=None)
    ap.add_argument("--second", default=None)
    ap.add_argument("--cmdline", required=True)
    ap.add_argument("--name", default="rk3399-mid")
    ap.add_argument("--kernel-addr", default="0x02080000")
    ap.add_argument("--ramdisk-addr", default="0x04000000")
    ap.add_argument("--second-addr", default="0x0f000000")
    ap.add_argument("--tags-addr", default="0x08300000")
    ap.add_argument("-o", "--output", required=True)
    a = ap.parse_args()

    kernel = open(a.kernel, "rb").read()
    ramdisk = open(a.ramdisk, "rb").read() if a.ramdisk else b""
    second = open(a.second, "rb").read() if a.second else b""
    cmdline = a.cmdline.encode()[:1023]

    hdr = bytearray(PAGE)
    hdr[0:8] = b"ANDROID!"
    struct.pack_into("<I", hdr, 0x08, len(kernel))
    struct.pack_into("<I", hdr, 0x0C, int(a.kernel_addr, 0))
    struct.pack_into("<I", hdr, 0x10, len(ramdisk))
    struct.pack_into("<I", hdr, 0x14, int(a.ramdisk_addr, 0))
    struct.pack_into("<I", hdr, 0x18, len(second))
    struct.pack_into("<I", hdr, 0x1C, int(a.second_addr, 0))
    struct.pack_into("<I", hdr, 0x20, int(a.tags_addr, 0))
    struct.pack_into("<I", hdr, 0x24, PAGE)
    struct.pack_into("<I", hdr, 0x28, 0)  # header_version
    struct.pack_into("<I", hdr, 0x2C, 0)  # os_version
    name = a.name.encode()[:15]
    hdr[0x30:0x30 + len(name)] = name
    hdr[0x40:0x40 + len(cmdline)] = cmdline

    sha = hashlib.sha1()
    sha.update(kernel)
    sha.update(struct.pack("<I", len(kernel)))
    sha.update(ramdisk)
    sha.update(struct.pack("<I", len(ramdisk)))
    sha.update(second)
    sha.update(struct.pack("<I", len(second)))
    hdr[0x240:0x240 + 20] = sha.digest()

    out = bytes(hdr) + pad(kernel) + pad(ramdisk) + pad(second)
    with open(a.output, "wb") as f:
        f.write(out)

    print(f"boot.img -> {a.output}")
    print(f"  kernel  {len(kernel):>9} B  @{a.kernel_addr}")
    print(f"  ramdisk {len(ramdisk):>9} B  @{a.ramdisk_addr}")
    print(f"  second  {len(second):>9} B")
    print(f"  total   {len(out):>9} B  ({len(out)/1048576:.2f} MiB)")
    print(f"  cmdline {a.cmdline}")


if __name__ == "__main__":
    main()
