#!/usr/bin/env python3
"""替换 Rockchip resource.img (RSCE) 里的 rk-kernel.dtb — 原位、不改条目布局。

RSCE 布局：
  0x000  "RSCE" + 版本 + 条目数
  0x200 起每 0x200 字节一个 ENTR 条目：
         +0x000 "ENTR"
         +0x004 name[128]
         +0x104 offset_in_sectors (u32 LE)   ← 文件内偏移 = offset*512
         +0x108 size_bytes        (u32 LE)
"""
import argparse
import shutil
import struct
import sys

SLOT = 0x200


def find_entry(data: bytes, name: str):
    for e in range(0x200, 0x1200, SLOT):
        if data[e:e + 4] != b"ENTR":
            continue
        nm = data[e + 4:e + 132].split(b"\0")[0].decode("ascii", "ignore")
        if nm == name:
            off, size = struct.unpack("<II", data[e + 260:e + 268])
            return e, off * 512, size
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("resource_img")
    ap.add_argument("dtb")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--name", default="rk-kernel.dtb")
    a = ap.parse_args()

    data = bytearray(open(a.resource_img, "rb").read())
    dtb = open(a.dtb, "rb").read()
    if dtb[:4] != b"\xd0\x0d\xfe\xed":
        sys.exit("输入不是合法 FDT（magic 不对）")

    hit = find_entry(bytes(data), a.name)
    if not hit:
        sys.exit(f"resource.img 里找不到条目 {a.name}")
    ent, foff, old_size = hit
    if len(dtb) > old_size:
        sys.exit(f"新 dtb {len(dtb)} B 超过槽位 {old_size} B，需要重排布局")

    data[foff:foff + len(dtb)] = dtb
    data[foff + len(dtb):foff + old_size] = b"\0" * (old_size - len(dtb))
    struct.pack_into("<I", data, ent + 264, len(dtb))

    with open(a.output, "wb") as f:
        f.write(data)

    print(f"resource.img -> {a.output}")
    print(f"  {a.name}: 槽位 @0x{foff:X}  旧 {old_size} B -> 新 {len(dtb)} B")


if __name__ == "__main__":
    main()
