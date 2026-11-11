#!/usr/bin/env python3
"""极简 FDT 解析器（无外部依赖）。

macOS 上装不了 dtc 时的替代品。支持：
  fdt.py dump   <dtb>                  # 打印成 dts 风格文本
  fdt.py get    <dtb> <node-path> [prop]
  fdt.py find   <dtb> <关键字>          # 找节点名/属性名/字符串值包含关键字的节点
  fdt.py ptree  <dtb>                  # 只打节点树
"""
import struct
import sys

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9


class Node:
    __slots__ = ("name", "props", "children", "parent", "path")

    def __init__(self, name, parent):
        self.name = name
        self.props = {}
        self.children = []
        self.parent = parent
        if parent is None:
            self.path = "/"
        elif parent.path == "/":
            self.path = "/" + name
        else:
            self.path = parent.path + "/" + name

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


def load(path):
    data = open(path, "rb").read()
    magic, totalsize, off_struct, off_strings, off_rsv, ver, lastcomp, cpu, size_str, size_struct = struct.unpack(
        ">10I", data[:40]
    )
    if magic != FDT_MAGIC:
        raise SystemExit("不是 DTB（magic=0x%08x）" % magic)
    strings = data[off_strings:off_strings + size_str]
    pos = off_struct
    root = None
    cur = None
    while True:
        (tok,) = struct.unpack(">I", data[pos:pos + 4])
        pos += 4
        if tok == FDT_BEGIN_NODE:
            end = data.index(b"\0", pos)
            name = data[pos:end].decode("utf-8", "replace")
            pos = (end + 4) & ~3
            n = Node(name, cur)
            if cur is None:
                root = n
            else:
                cur.children.append(n)
            cur = n
        elif tok == FDT_END_NODE:
            cur = cur.parent
        elif tok == FDT_PROP:
            ln, nameoff = struct.unpack(">II", data[pos:pos + 8])
            pos += 8
            val = data[pos:pos + ln]
            pos = (pos + ln + 3) & ~3
            nend = strings.index(b"\0", nameoff)
            pname = strings[nameoff:nend].decode("utf-8", "replace")
            cur.props[pname] = val
        elif tok == FDT_NOP:
            continue
        elif tok == FDT_END:
            break
        else:
            raise SystemExit("未知 FDT token %d @%d" % (tok, pos))
    return root


def fmt_val(v):
    if len(v) == 0:
        return "True"
    printable = all(32 <= b < 127 or b == 0 for b in v) and v[-1] == 0 and len(v) > 1
    if printable and b"\0" not in v[:-1]:
        return '"%s"' % v[:-1].decode("utf-8", "replace")
    cells = []
    for i in range(0, len(v), 4):
        chunk = v[i:i + 4]
        if len(chunk) < 4:
            cells.append("<0x%s>" % chunk.hex())
        else:
            cells.append("0x%02x" % struct.unpack(">I", chunk)[0])
    return "<%s>" % " ".join(cells)


def dump(node, indent=0, out=sys.stdout):
    pad = "    " * indent
    label = node.name if node.name else "/"
    out.write("%s%s {\n" % (pad, label))
    for k, v in node.props.items():
        out.write("%s    %s = %s;\n" % (pad, k, fmt_val(v)))
    for c in node.children:
        dump(c, indent + 1, out)
    out.write("%s};\n" % pad)


def find_node(root, path):
    if path in ("/", ""):
        return root
    cur = root
    for part in [p for p in path.split("/") if p]:
        nxt = None
        for c in cur.children:
            if c.name == part:
                nxt = c
                break
        if nxt is None:
            return None
        cur = nxt
    return cur


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    cmd, path = sys.argv[1], sys.argv[2]
    root = load(path)
    if cmd == "dump":
        dump(root)
    elif cmd == "ptree":
        for n in root.walk():
            print(n.path)
    elif cmd == "get":
        if len(sys.argv) < 4:
            raise SystemExit("需要节点路径")
        n = find_node(root, sys.argv[3])
        if n is None:
            raise SystemExit("找不到节点 %s" % sys.argv[3])
        if len(sys.argv) >= 5:
            v = n.props.get(sys.argv[4])
            if v is None:
                raise SystemExit("节点 %s 没有属性 %s" % (sys.argv[3], sys.argv[4]))
            print(fmt_val(v))
        else:
            for k, v in n.props.items():
                print("%-28s = %s" % (k, fmt_val(v)))
    elif cmd == "find":
        kw = sys.argv[3].lower()
        for n in root.walk():
            hit = kw in n.name.lower()
            if not hit:
                for k, v in n.props.items():
                    if kw in k.lower() or kw in v.decode("latin-1").lower():
                        hit = True
                        break
            if hit:
                print(n.path)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
