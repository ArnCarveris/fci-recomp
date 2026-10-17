"""Find the XDK library functions in an XBE with TGP482's Xbox XBE Recomp signature list.

  python -B tools/sigmatch.py <xbe> signatures.toml out.json [image_symbols.h] [pins.json]

Reimplements that project's matcher (tools/symbols/main.cpp at 65e959d4, MIT) without its
constant-fingerprint fallback: a linear sweep of each code section with image addresses and rel32
targets masked, a 64-bit FNV rolling hash over `len` masked bytes from each instruction start, then the
hits whose rel32 callees hash as recorded (their callees' too for several hits or `deep`); `count`/`nth`
pick one of identical functions by link order, and `.XTLID` export ids are used where bytes find nothing.
[data] symbols are an operand of an instruction of a found function. Needs capstone.
"""

import hashlib
import json
from pathlib import Path
import re
import struct
import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

MUL = 0x100000001B3
MASK64 = (1 << 64) - 1
MASKED = 0x100
callees_differ = set()


def is_addr(v):
    return 0x10000 <= v < 0x4000000


def parse_value(text):
    """The small TOML subset signatures.toml uses: inline tables, arrays, strings, ints, bools."""
    pos = 0

    def ws():
        nonlocal pos
        while pos < len(text) and text[pos] in " \t":
            pos += 1

    def value():
        nonlocal pos
        ws()
        c = text[pos]
        if c == "{":
            pos += 1
            out = {}
            while True:
                ws()
                if text[pos] == "}":
                    pos += 1
                    return out
                m = re.compile(r"(\w+)\s*=\s*").match(text, pos)
                pos = m.end()
                out[m.group(1)] = value()
                ws()
                if text[pos] == ",":
                    pos += 1
        if c == "[":
            pos += 1
            out = []
            while True:
                ws()
                if text[pos] == "]":
                    pos += 1
                    return out
                out.append(value())
                ws()
                if text[pos] == ",":
                    pos += 1
        if c == '"':
            end = text.index('"', pos + 1)
            s = text[pos + 1 : end]
            pos = end + 1
            return s
        m = re.compile(r"true|false|0x[0-9A-Fa-f]+|-?\d+").match(text, pos)
        pos = m.end()
        t = m.group(0)
        return t == "true" if t in ("true", "false") else int(t, 0)

    return value()


def read_sigs(path):
    tables = {"symbols": {}, "anchors": {}, "data": {}}
    cur = None
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            cur = tables.get(line.strip("[]"))
            continue
        m = re.match(r"(\w+) = (.*)$", line)
        if cur is not None and m:
            cur[m.group(1)] = parse_value(m.group(2))
    return tables


class Image:
    def __init__(self, xbe):
        self.x = xbe
        base = struct.unpack_from("<I", xbe, 0x104)[0]
        count, hdr = struct.unpack_from("<II", xbe, 0x11C)
        self.sections = []
        for i in range(count):
            o = hdr - base + i * 56
            flags, va, vsize, raw, rsize, name_va = struct.unpack_from("<IIIIII", xbe, o)
            n = name_va - base
            self.sections.append((xbe[n : xbe.index(b"\0", n)].decode(), va, vsize, raw, rsize, flags))
        self.md = Cs(CS_ARCH_X86, CS_MODE_32)
        self.md.detail = True
        self.code = {}

    def sweep(self, name):
        if name in self.code:
            return self.code[name]
        sec = next(s for s in self.sections if s[0] == name)
        _, va, vsize, raw, rsize, _ = sec
        n = min(vsize, rsize)
        b = self.x[raw : raw + n]
        m = list(b)
        start = bytearray(n)
        o = 0
        while o < n:
            start[o] = 1
            insn = next(self.md.disasm(b[o : o + 15], va + o, 1), None) if b[o] else None
            if insn is None:
                o += 1
                continue
            if insn.disp_size == 4 and is_addr(insn.disp & 0xFFFFFFFF):
                for k in range(4):
                    m[o + insn.disp_offset + k] = MASKED
            if insn.imm_size == 4 and (
                self.relative(insn) or is_addr(struct.unpack_from("<I", b, o + insn.imm_offset)[0])
            ):
                for k in range(4):
                    m[o + insn.imm_offset + k] = MASKED
            o += insn.size
        h = [0] * (n + 1)
        for i in range(n):
            h[i + 1] = (h[i] * MUL + m[i] + 1) & MASK64
        self.code[name] = (va, b, start, h)
        return self.code[name]

    @staticmethod
    def relative(insn):
        return insn.mnemonic == "call" or insn.mnemonic.startswith("j")

    def section_of(self, va):
        for s in self.sections:
            if s[1] <= va < s[1] + min(s[2], s[4]) and s[5] & 4:
                return s[0]
        return None

    def hash_at(self, va, ln):
        name = self.section_of(va)
        if not name:
            return None
        sva, b, start, h = self.sweep(name)
        a = va - sva
        if a + ln > len(b):
            return None
        return (h[a + ln] - h[a] * pow(MUL, ln, 1 << 64)) & MASK64

    def insns(self, va, ln):
        name = self.section_of(va)
        sva, b, _, _ = self.sweep(name)
        a = va - sva
        return list(self.md.disasm(b[a : a + ln], va))

    def external_targets(self, va, ln):
        out = []
        for insn in self.insns(va, ln):
            if self.relative(insn) and insn.imm_size == 4:
                t = insn.operands[0].imm & 0xFFFFFFFF
                if not va <= t < va + ln:
                    out.append(t)
        return out


def calls_match(img, va, ln, calls, deep):
    out = img.external_targets(va, ln)
    if len(out) != len(calls):
        return False
    for t, c in zip(out, calls):
        cl, ch = c[0], int(c[1], 16)
        if not cl:
            continue
        if img.hash_at(t, cl) != ch:
            return False
        if deep and len(c) > 2 and not calls_match(img, t, cl, c[2], False):
            return False
    return True


def find(img, sigs):
    by_sec_len = {}
    for name, s in sigs.items():
        if s.get("len"):
            by_sec_len.setdefault((s["sec"], s["len"]), {}).setdefault(int(s["hash"], 16), []).append(name)
    hits = {name: [] for name in sigs}
    bytes_only = {}
    for (sec, ln), table in by_sec_len.items():
        if not any(x[0] == sec for x in img.sections):
            continue
        sva, b, start, h = img.sweep(sec)
        p = pow(MUL, ln, 1 << 64)
        for a in range(len(b) - ln + 1):
            if start[a]:
                names = table.get((h[a + ln] - h[a] * p) & MASK64)
                for name in names or ():
                    bytes_only.setdefault(name, []).append(sva + a)
                    if calls_match(img, sva + a, ln, sigs[name].get("calls", []), False):
                        hits[name].append(sva + a)
    # Bytes unique, callees not: a callee outside the library (the title's allocator, say)
    # differs between titles. The reference falls back to constant fingerprints here.
    for name, vas in bytes_only.items():
        if not hits[name] and len(vas) == 1 and sigs[name].get("count", 1) == 1:
            hits[name] = vas
            callees_differ.add(name)
    for name, s in sigs.items():
        if len(hits[name]) > 1 or s.get("deep"):
            deep = [va for va in hits[name] if calls_match(img, va, s["len"], s.get("calls", []), True)]
            if (deep or s.get("deep")) and name not in callees_differ:
                hits[name] = deep
    return hits


def resolve(img, sigs, hits, exports):
    found, report = {}, {}
    for name, s in sigs.items():
        h = hits.get(name, [])
        count = s.get("count", 1)
        if count == 1 and len(h) == 1:
            found[name] = h[0]
        elif count > 1 and len(h) == count:
            found[name] = h[s.get("nth", 0)]
        elif not h and s.get("xtlid") in exports:
            found[name] = exports[s["xtlid"]]
            report[name] = "xtlid"
        if name in found and name in callees_differ:
            report[name] = "found, callees differ"
        report.setdefault(
            name,
            "found"
            if name in found
            else ("ambiguous %d" % len(h) if h else ("missed" if s.get("len") else "no signature")),
        )
    return found, report


def image_pins(raw, sig_path, pins_path=None):
    """the image's hand pins (data/<image>.pins.json)"""
    if not pins_path:
        return {}
    pins = json.loads(Path(pins_path).read_text())
    if pins.get("image_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("pins belong to a different XBE")
    return pins["symbols"]


def main(xbe_path, sig_path, out_path, header_path=None, pins_path=None):
    img = Image(open(xbe_path, "rb").read())
    tables = read_sigs(sig_path)
    exports = {}
    for s in img.sections:
        if s[0] == ".XTLID":
            d = img.x[s[3] : s[3] + min(s[2], s[4])]
            for i in range(0, len(d) - 7, 8):
                idn, va = struct.unpack_from("<II", d, i)
                if idn:
                    exports[idn] = va
    sigs = {**tables["symbols"], **tables["anchors"]}
    hits = find(img, {k: v for k, v in sigs.items() if v})
    found, report = resolve(img, {k: v for k, v in sigs.items() if v}, hits, exports)
    for name in tables["symbols"]:
        if not tables["symbols"][name]:
            report[name] = "no signature"
    data = {}
    for name, d in tables["data"].items():
        va = None
        if d.get("in") in found:
            fn = found[d["in"]]
            insns = img.insns(fn, sigs[d["in"]]["len"])
            if d["insn"] < len(insns):
                insn = insns[d["insn"]]
                if d["op"] == "imm":
                    imms = [op.imm & 0xFFFFFFFF for op in insn.operands if op.type == 2]
                    va = imms[-1] if imms else None
                elif insn.disp_size == 4:
                    va = insn.disp & 0xFFFFFFFF
        if va is None and d.get("xtlid") in exports:
            va = exports[d["xtlid"]]
        data[name] = va
    symbols = {k: found.get(k, 0) for k in tables["symbols"]}
    # hand pins: addresses the signatures cannot find
    image_sha = hashlib.sha256(img.x).hexdigest()
    for k, v in image_pins(img.x, sig_path, pins_path).items():
        symbols[k] = int(v["va"], 16)
        report[k] = "pinned"
    result = {
        "summary": {
            r: sum(1 for v in report.values() if v.split()[0] == r)
            for r in ("found", "xtlid", "ambiguous", "missed", "no")
        },
        "symbols": {k: ("0x%08X" % v if v else report.get(k)) for k, v in sorted(symbols.items())},
        "image_sha256": image_sha,
        "report": dict(sorted(report.items())),
        "data": {k: ("0x%08X" % v if v else None) for k, v in sorted(data.items())},
        "ambiguous_hits": {
            k: ["0x%08X" % a for a in v] for k, v in sorted(hits.items()) if len(v) > 1 and k not in found
        },
    }
    open(out_path, "w").write(json.dumps(result, indent=1) + "\n")
    if header_path:
        # As the reference's codegen_emit.cpp: a function this image lacks gets a placeholder
        # address (0xFFFF0000 + n) so its host override still links; nothing calls it.
        lines = [
            "// Image symbols, written by tools/sigmatch.py; do not edit",
            "#pragma once",
            '#define IMAGE_XBE "' + Path(xbe_path).name + '"',
        ]
        absent = 0
        for k, v in sorted(symbols.items()):
            if not v:
                v, absent = 0xFFFF0000 + absent, absent + 1
                lines.append("#define SYM_%s %08X\n#define HAS_%s 0" % (k, v, k))
            else:
                lines.append("#define SYM_%s %08X\n#define HAS_%s 1" % (k, v, k))
        for k, v in sorted(data.items()):
            lines.append("#define SYM_%s %08X\n#define HAS_%s %d" % (k, v or 0, k, 1 if v else 0))
        layout = sig_path.replace("signatures.toml", "layout.toml")
        try:
            for line in open(layout, encoding="utf-8"):
                m = re.match(r"(\w+)\s*=\s*(0x[0-9A-Fa-f]+|\d+)", line)
                if m:
                    lines.append("#define XDK_%s 0x%X" % (m.group(1), int(m.group(2), 0)))
        except OSError:
            pass
        open(header_path, "w").write("\n".join(lines) + "\n")
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main(*sys.argv[1:])
