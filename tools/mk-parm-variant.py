#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK3399-MID —— 把 armbian 产出的 GPT 镜像转换成「保留原厂 PARM + MBR 分区表」变体。

为什么要这个变体
----------------
本板 eMMC user 区 LBA0 是 Rockchip parameter（"PARM" 头 + u32 长度 + CRLF 文本），
文本 898 B，跨 LBA0 与 LBA1 前 386 B。其中 CMDLINE 行带着 mtdparts：

    mtdparts=rk29xxnand:0x00002000@0x00002000(uboot),0x00002000@0x00004000(trust),...

boot0 里的原厂 miniloader 靠这份 mtdparts 去 user 区固定坐标取引导件：
    LBA8192  -> "LOADER" 容器（U-Boot proper）
    LBA16384 -> "BL3X"   容器（trust / ATF）

而 armbian 默认 IMAGE_PARTITION_TABLE=gpt：sfdisk 会把 GPT 头写到 LBA1、
保护 MBR 写到 LBA0 —— 与 PARM 正面冲突，会毁掉 mtdparts。

本脚本的解法
------------
LBA0 的前 446 字节是 MBR 分区表之前的「引导代码区」，可以放我们的东西；
446..511 是 4 个 16 字节的 MBR 分区项。=> 只要让 parameter 整体 ≤ 446 字节，
两者就能共存：

    LBA0[0 : len(param)]  = 压缩版 parameter（保留全部头字段，mtdparts 只留引导相关条目）
    LBA0[len : 446]      = 0
    LBA0[446 : 512]      = MBR 分区表（p1..pn，type 0x83）+ 0x55AA
    LBA1 .. LBA34        = 0（抹掉 GPT 头与 entry array）
    镜像末尾 33 个 LBA   = 0（抹掉 secondary GPT）

压缩 parameter 的 mtdparts 只保留 uboot / trust / misc / resource 四条：
miniloader 只需要定位 uboot@0x2000 与 trust@0x4000，misc/resource 是为了
保留原厂后续分区的起点信息。Android 的 kernel/boot/system 等条目被舍弃，
这不影响 Armbian 路径（miniloader 只需要把 U-Boot proper 拉起来）。

用法
----
    python3 mk-parm-variant.py <in.img> <out.img> [--parm stock-parm.bin]
"""

import argparse
import os
import shutil
import struct
import sys

SECTOR = 512
# LBA0 里 MBR 分区表之前的可用字节数
MBR_TABLE_OFF = 446
# Linux filesystem data 的 GPT type GUID（mixed-endian）
GUID_LINUX_FS = bytes.fromhex("af3dc60f838472478e793d69d8477de4")
GUID_EFI = bytes.fromhex("c12a7328f81f11d2ba4b00a0c93ec93b")


def read_gpt(img):
    """返回 [(index, type_guid, first_lba, last_lba, name)]；没有 GPT 就返回 []。"""
    img.seek(SECTOR)
    hdr = img.read(SECTOR)
    if hdr[:8] != b"EFI PART":
        return []
    entry_lba = struct.unpack_from("<Q", hdr, 72)[0]
    num_entries = struct.unpack_from("<I", hdr, 80)[0]
    entry_size = struct.unpack_from("<I", hdr, 84)[0]
    img.seek(entry_lba * SECTOR)
    raw = img.read(num_entries * entry_size)
    out = []
    for i in range(num_entries):
        e = raw[i * entry_size:(i + 1) * entry_size]
        if len(e) < 128 or e[:16] == b"\x00" * 16:
            continue
        first_lba = struct.unpack_from("<Q", e, 32)[0]
        last_lba = struct.unpack_from("<Q", e, 40)[0]
        name = e[56:128].decode("utf-16-le", "replace").rstrip("\x00")
        out.append((i + 1, e[:16], first_lba, last_lba, name))
    return out


def build_mbr(parts):
    """parts: [(first_lba, last_lba, name)] -> 512 字节 MBR（含保护式 55AA）。"""
    mbr = bytearray(SECTOR)
    for idx, (first, last, _name) in enumerate(parts[:4]):
        off = 446 + idx * 16
        count = last - first + 1
        entry = bytearray(16)
        entry[0] = 0x00                                    # 非活动
        entry[1:4] = bytes((0xFE, 0xFF, 0xFF))              # CHS start：LBA 模式
        entry[4] = 0x83                                    # Linux
        entry[5:8] = bytes((0xFE, 0xFF, 0xFF))              # CHS end：LBA 模式
        struct.pack_into("<I", entry, 8, first & 0xFFFFFFFF)
        struct.pack_into("<I", entry, 12, count & 0xFFFFFFFF)
        mbr[off:off + 16] = entry
    mbr[510] = 0x55
    mbr[511] = 0xAA
    return bytes(mbr)


def build_compact_param(stock_parm, keep=("uboot", "trust", "misc", "resource")):
    """从原厂 parameter 生成压缩版（整体 ≤ MBR_TABLE_OFF 字节）。"""
    if stock_parm[:4] != b"PARM":
        raise SystemExit("stock parameter 不是 PARM 头")
    size = struct.unpack_from("<I", stock_parm, 4)[0]
    text = stock_parm[8:size].decode("utf-8", "replace")
    lines = text.split("\r\n")

    head = []
    for line in lines:
        if not line or line.startswith("CMDLINE:"):
            continue
        head.append(line)

    # 从原厂 mtdparts 里挑出要保留的条目
    src_mtd = ""
    for line in lines:
        if line.startswith("CMDLINE:") and "mtdparts=" in line:
            src_mtd = line.split("mtdparts=", 1)[1]
            break
    entries = []
    if src_mtd:
        for item in src_mtd.split(","):
            name = item.split("(", 1)[1].rstrip(")") if "(" in item else ""
            if name in keep:
                entries.append(item)
    if len(entries) < 2 or "uboot" not in entries[0] or "trust" not in entries[1]:
        raise SystemExit(f"无法从原厂 mtdparts 中提取 uboot/trust：{src_mtd[:80]}")

    cmdline = "CMDLINE: androidboot.hardware=rk30board init=/init mtdparts=" + ",".join(entries)

    # 优先丢弃 '#' 注释行（Rockchip parameter 解析器会忽略它们），其次才动普通行
    dropped = []
    while True:
        body = "\r\n".join(head + [cmdline])
        blob = b"PARM" + struct.pack("<I", 8 + len(body)) + body.encode("utf-8")
        if len(blob) <= MBR_TABLE_OFF:
            break
        cands = [l for l in head if l.startswith("#")] or head
        if not cands:
            raise SystemExit(f"压缩后 parameter 仍超长：{len(blob)} > {MBR_TABLE_OFF}")
        victim = max(cands, key=len)
        head.remove(victim)
        dropped.append(victim)
    return blob, entries, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_img")
    ap.add_argument("out_img")
    ap.add_argument("--parm", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                   "..", "armbian", "blobs", "stock-parm.bin"))
    ap.add_argument("--report", action="store_true", help="只打印解析结果，不写文件")
    args = ap.parse_args()

    stock = open(args.parm, "rb").read()
    param, kept, dropped = build_compact_param(stock)

    with open(args.in_img, "rb") as img:
        gpt = read_gpt(img)
        if not gpt:
            raise SystemExit(f"{args.in_img} 里没有 GPT 头（LBA1 无 'EFI PART'）")
        print("=== 原 GPT 分区 ===")
        parts = []
        for idx, guid, first, last, name in gpt:
            kind = "linux" if guid == GUID_LINUX_FS else ("efi" if guid == GUID_EFI else "other")
            print(f"  p{idx}: {name:<20} LBA {first}..{last}  ({kind})")
            parts.append((first, last, name))

        if args.report:
            print(f"\n=== 压缩 parameter ({len(param)} B, 保留 mtdparts: {kept}) ===")
            print(param[8:].decode("utf-8", "replace"))
            return 0

        mbr = build_mbr(parts)
        total = os.path.getsize(args.in_img)

        # 先整盘复制成输出文件，再原地打补丁；否则 r+b 会对不存在的文件报错，
        # 也会在没有覆盖到的区域留下空洞。
        if os.path.abspath(args.in_img) != os.path.abspath(args.out_img):
            shutil.copyfile(args.in_img, args.out_img)

        with open(args.out_img, "r+b") as out:
            # 1) LBA0：parameter + MBR
            lba0 = bytearray(SECTOR)
            lba0[0:len(param)] = param
            lba0[MBR_TABLE_OFF:SECTOR] = mbr[MBR_TABLE_OFF:SECTOR]
            out.seek(0)
            out.write(bytes(lba0))

            # 2) 抹掉 GPT 头与 entry array（LBA1..LBA34）
            out.seek(SECTOR)
            out.write(b"\x00" * (34 * SECTOR))

            # 3) 抹掉末尾的 secondary GPT（最后 33 个 LBA）
            out.seek(total - 33 * SECTOR)
            out.write(b"\x00" * (33 * SECTOR))

    print(f"\n=== 已写出 {args.out_img} ===")
    print(f"  LBA0[0:{len(param)}]      = 压缩版 parameter")
    print(f"  LBA0[{MBR_TABLE_OFF}:512]  = MBR 分区表")
    print(f"  LBA1..34 / 末尾 33 LBA    = 已清零")
    print("  压缩 mtdparts:", ", ".join(kept))
    return 0


if __name__ == "__main__":
    sys.exit(main())
