"""Differential CPU check of one lifted function call (a debugging tool; needs `pip install unicorn`).

Reads the .pre/.post snapshots src/fci_probe.c writes (a build with FCI_PROBE=<va>, tools/compile.py),
replays the original x86 bytes from the .pre state in the Unicorn emulator (the reference CPU) until the
call returns, and compares the emulator's registers and every byte it wrote with the lifted code's .post
state. Mismatching bytes are reported with the original instruction that wrote them.

  python -B tools/oracle.py <prefix> [--max N] [--dump-event N OUT] [--hook LO HI] [--args N] [--xbe PATH]

--xbe PATH lets the reference run pass kernel calls: the runtime gives kernel import slot i the
address 0xFE000000 + 4i, and with the image's thunk table (slot -> ordinal) and the argument
sizes in the toolkit's kernel_bridge.c each call returns at once with a stand-in result (critical
sections and IRQL changes do nothing, waits succeed, others return 0; the Rtl memory
routines 268/269/284/298/320 are emulated exactly, and MmAllocateContiguousMemory[Ex] and
NtAllocateVirtualMemory hand out fresh memory past the snapshot, at addresses that differ from
the lifted run's). Results that depend on the kernel can therefore differ from the lifted run; every
stand-in used is listed. The argument sizes come from the toolkit build's kernel_bridge.c
(FCI_KERNEL_BRIDGE, default the game build's staged copy).

Without a .post (the lifted call never returned, e.g. a stop inside it) only the
reference run is reported, with the callee-trace comparison. --hook sets the code
range (hex) whose instructions drive the callee trace (default: the Bink sections).

Reads data only. The snapshots are guest memory, so they stay out of Git.
"""

import ctypes
import os
from pathlib import Path
import struct
import sys

from unicorn import (
    UC_ARCH_X86,
    UC_HOOK_CODE,
    UC_HOOK_INTR,
    UC_HOOK_MEM_UNMAPPED,
    UC_HOOK_MEM_WRITE,
    UC_MODE_32,
    UC_PROT_ALL,
    Uc,
    UcError,
)
from unicorn import x86_const as X

CONTIG, TILED = 0x80000000, 0xF0000000
EXTRA = 0x1000000  # stand-in allocations: past the snapshot's contiguous window / user RAM
REGS = ["eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi", "fs_base", "seh_ebp", "df"]


def load(path):
    data = open(path, "rb").read()
    if data[:8] != b"FCIPROBE":
        raise ValueError(path)
    va, phase = struct.unpack_from("<II", data, 8)
    pos = 16
    regs = dict(zip(REGS, struct.unpack_from("<11I", data, pos)))
    pos += 44
    mm = [data[pos + 8 * i : pos + 8 * i + 8] for i in range(8)]
    pos += 64
    xmm = [data[pos + 16 * i : pos + 16 * i + 16] for i in range(8)]
    pos += 128
    regions = []
    while True:
        rva, length = struct.unpack_from("<II", data, pos)
        pos += 8
        if not rva and not length:
            break
        regions.append((rva, data[pos : pos + length]))
        pos += length
    return va, phase, regs, mm, xmm, regions


def read(regions, va, n):
    for rva, blob in regions:
        if rva <= va and va + n <= rva + len(blob):
            return blob[va - rva : va - rva + n]
    return None


def set_fs(uc, base, regions, gdt=0xFFFF0000):
    """fs:[0] is the SEH chain (_SEH_prolog reads it); Unicorn's FS_BASE register does
    nothing in 32-bit mode, so FS gets a GDT data descriptor with the snapshot's base (DS/ES/SS a flat one: with
    a GDT loaded, null selectors there broke the stack writes)."""
    if any(rva <= gdt < rva + len(blob) for rva, blob in regions):
        raise ValueError("GDT page is guest memory")
    lo = 0xFFFF | (base & 0xFFFF) << 16
    hi = (base >> 16) & 0xFF | 0x93 << 8 | 0xCF << 16 | (base >> 24) << 24
    uc.mem_map(gdt, 0x1000)
    uc.mem_write(gdt + 8, struct.pack("<IIII", lo, hi, 0xFFFF, 0xCF9300))  # 0x08 FS, 0x10 flat data
    uc.reg_write(X.UC_X86_REG_GDTR, (0, gdt, 0x17, 0))
    for reg in (X.UC_X86_REG_DS, X.UC_X86_REG_ES, X.UC_X86_REG_SS):
        uc.reg_write(reg, 0x10)
    uc.reg_write(X.UC_X86_REG_FS, 8)


def write_state(uc, va, path, pre):
    """The reference CPU's state, in fci_probe.c's snapshot format, for a lifted
    replay (RECOMP_FCI_REPLAY) of the call that starts here."""
    regs = [
        uc.reg_read(r)
        for r in (
            X.UC_X86_REG_EAX,
            X.UC_X86_REG_ECX,
            X.UC_X86_REG_EDX,
            X.UC_X86_REG_EBX,
            X.UC_X86_REG_ESP,
            X.UC_X86_REG_EBP,
            X.UC_X86_REG_ESI,
            X.UC_X86_REG_EDI,
        )
    ]
    regs += [pre["fs_base"], regs[5], pre["df"]]  # seh_ebp: a frameless callee inherits ebp
    with open(path, "wb") as f:
        f.write(b"FCIPROBE" + struct.pack("<II", va, 0) + struct.pack("<11I", *regs))
        for i in range(8):
            mantissa = uc.reg_read(getattr(X, f"UC_X86_REG_FP{i}"))[0]
            f.write(struct.pack("<Q", mantissa & 0xFFFFFFFFFFFFFFFF))
        for i in range(8):
            f.write(uc.reg_read(getattr(X, f"UC_X86_REG_XMM{i}")).to_bytes(16, "little"))
        for begin, end, _ in uc.mem_regions():
            f.write(struct.pack("<II", begin, end + 1 - begin))
            f.write(bytes(uc.mem_read(begin, end + 1 - begin)))
        f.write(struct.pack("<II", 0, 0))
    print(f"  state at {va:08X} written to {path}")


KERNEL_BRIDGE = os.environ.get(
    "FCI_KERNEL_BRIDGE",
    str(
        Path(__file__).resolve().parents[1]
        / "build"
        / "build"
        / "default"
        / "case"
        / "inputs"
        / "toolkit"
        / "src"
        / "kernel"
        / "kernel_bridge.c"
    ),
)


def kernel_slots(xbe_path):
    """Slot index -> ordinal from the image's kernel thunk table (retail key)."""
    d = open(xbe_path, "rb").read()
    base = struct.unpack_from("<I", d, 0x104)[0]
    thunk_va = struct.unpack_from("<I", d, 0x158)[0] ^ 0x5B6D40B6
    nsec = struct.unpack_from("<I", d, 0x11C)[0]
    shdr = struct.unpack_from("<I", d, 0x120)[0] - base
    for i in range(nsec):
        flags, sva, vsize, raw, rsize = struct.unpack_from("<5I", d, shdr + i * 56)
        if sva <= thunk_va < sva + rsize:
            off = raw + thunk_va - sva
            break
    slots = []
    while True:
        v = struct.unpack_from("<I", d, off + 4 * len(slots))[0]
        if not v:
            return slots
        slots.append(v & 0x7FFFFFFF)


def kernel_arg_bytes():
    """Ordinal -> stack bytes popped, from the bridge's table (case N: return B;)."""
    import re

    out = {}
    for m in re.finditer(r"case (\d+): return +(\d+);", open(KERNEL_BRIDGE, encoding="utf-8").read()):
        out.setdefault(int(m.group(1)), int(m.group(2)))
    return out


def main(prefix, limit, dump=None, hook=(0x005A8B20, 0x005C0000), nargs=8, xbe=None):
    va, _, pre, mm, xmm, regions = load(prefix + ".pre")
    try:
        _, _, post, post_mm, post_xmm, post_regions = load(prefix + ".post")
    except OSError:
        post = None
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    keep, heap = [], {}
    for rva, blob in regions:
        lo = rva & ~0xFFF
        hi = (rva + len(blob) + 0xFFF) & ~0xFFF
        if lo == CONTIG:
            # The runtime's tiled aperture 0xF0000000+P is a view of the contiguous
            # window 0x80000000+P (xbox_memory_layout.c); XGRPH writes through it.
            buf = ctypes.create_string_buffer(hi - lo + EXTRA)
            keep.append(buf)
            uc.mem_map_ptr(lo, hi - lo + EXTRA, UC_PROT_ALL, ctypes.addressof(buf))
            uc.mem_map_ptr(TILED, hi - lo + EXTRA, UC_PROT_ALL, ctypes.addressof(buf))
            heap["contig"] = hi
        elif lo < 0x10000000:
            uc.mem_map(lo, hi - lo + EXTRA)
            heap["virtual"] = hi
        else:
            uc.mem_map(lo, hi - lo)
        uc.mem_write(rva, blob)
    for name, reg in (
        ("eax", X.UC_X86_REG_EAX),
        ("ecx", X.UC_X86_REG_ECX),
        ("edx", X.UC_X86_REG_EDX),
        ("ebx", X.UC_X86_REG_EBX),
        ("esp", X.UC_X86_REG_ESP),
        ("ebp", X.UC_X86_REG_EBP),
        ("esi", X.UC_X86_REG_ESI),
        ("edi", X.UC_X86_REG_EDI),
    ):
        uc.reg_write(reg, pre[name])
    set_fs(uc, pre["fs_base"], regions)
    for i in range(8):
        # MMi aliases the x87 register FPi (mantissa = the 64-bit value, exponent all ones);
        # Unicorn's MMi ids are no-ops.
        uc.reg_write(getattr(X, f"UC_X86_REG_FP{i}"), (int.from_bytes(mm[i], "little"), 0xFFFF))
        uc.reg_write(getattr(X, f"UC_X86_REG_XMM{i}"), int.from_bytes(xmm[i], "little"))
    ret = struct.unpack("<I", read(regions, pre["esp"], 4))[0]
    writer = {}
    state = {"eip": va, "steps": 0}

    def on_write(uc_, access, address, size, value, user):
        eip = uc_.reg_read(X.UC_X86_REG_EIP)
        state["steps"] += 1
        if TILED <= address < TILED + 0x10000000:
            address += CONTIG - TILED  # compared through the contiguous view
        for k in range(size):
            writer[address + k] = (state["steps"], eip)

    def on_unmapped(uc_, access, address, size, value, user):
        print(f"unmapped access {address:08X} size {size} at {uc_.reg_read(X.UC_X86_REG_EIP):08X}")
        return False

    def on_intr(uc_, intno, user):
        print(f"interrupt {intno} at {uc_.reg_read(X.UC_X86_REG_EIP):08X}")
        uc_.emu_stop()

    # Callee trace (fci_probe.c writes <prefix>.trace when other probed functions
    # run inside the captured call): the same tuple from the reference CPU at
    # each of those entries; the first mismatch brackets the faulty code.
    lifted_trace, oracle_trace = [], []
    try:
        lifted_trace = [line.split() for line in open(prefix + ".trace")]
    except OSError:
        pass

    def fnv(h, data):
        for byte in data:
            h = ((h ^ byte) * 16777619) & 0xFFFFFFFF
        return h

    if lifted_trace:
        entries = {int(row[1], 16) for row in lifted_trace if row[0] == "E"}
        nest = []

        def on_code(uc_, address, size, user):
            esp = uc_.reg_read(X.UC_X86_REG_ESP)
            while nest and address == nest[-1][1] and esp > nest[-1][2]:  # ret or ret n
                callee, _, _, a1, a2 = nest.pop()  # back at the return address
                h = 0
                if 0x10000 <= a1 < 0x03FF0000 and 0 < a2 < 0x1000:
                    h = 2166136261
                    for r in range(8):
                        h = fnv(h, uc_.mem_read(a1 + r * a2, 16))
                oracle_trace.append(["R", "%08X" % callee, "%08X" % h])
            if address in entries:
                row = [address] + [
                    uc_.reg_read(r) for r in (X.UC_X86_REG_EAX, X.UC_X86_REG_ECX, X.UC_X86_REG_EDX, X.UC_X86_REG_EBX)
                ]
                row += [esp, uc_.reg_read(X.UC_X86_REG_ESI), uc_.reg_read(X.UC_X86_REG_EDI)]
                args = list(struct.unpack("<8I", uc_.mem_read(esp + 4, 32)))
                row += args
                row += [fnv(2166136261, uc_.mem_read(p, 256)) if 0x10000 <= p < 0x03FFFF00 else 0 for p in args]
                oracle_trace.append(["E"] + ["%08X" % v for v in row])
                if dump and len(oracle_trace) - 1 == dump[0]:
                    write_state(uc_, address, dump[1] + ".pre", pre)
                nest.append((address, struct.unpack("<I", uc_.mem_read(esp, 4))[0], esp, args[0], args[1]))

        # Every instruction of the Bink sections: entries and the callers' return points.
        uc.hook_add(UC_HOOK_CODE, on_code, begin=hook[0], end=hook[1])
    kernel_used, kernel_order = {}, []
    if xbe:
        slots, arg_bytes = kernel_slots(xbe), kernel_arg_bytes()
        uc.mem_map(0xFE000000, 0x1000)

        def alloc(kind, size, align):
            """Bump allocation in the EXTRA space; addresses differ from the lifted run's."""
            if kind not in heap:
                raise ValueError("no snapshot region for " + kind)
            base = (heap[kind] + align - 1) & ~(align - 1)
            heap[kind] = base + ((size + 0xFFF) & ~0xFFF)
            return base

        def on_kernel(uc_, address, size, user):
            ordinal = slots[(address - 0xFE000000) // 4] if (address - 0xFE000000) // 4 < len(slots) else -1
            esp = uc_.reg_read(X.UC_X86_REG_ESP)
            ret_to = struct.unpack("<I", uc_.mem_read(esp, 4))[0]
            arg0 = struct.unpack("<I", uc_.mem_read(esp + 4, 4))[0]
            result = 0
            if ordinal == 173:  # MmGetPhysicalAddress
                result = arg0 & 0x0FFFFFFF
            elif ordinal == 119:  # KeInsertQueueDpc
                result = 1
            elif ordinal == 166 or ordinal == 165:  # MmAllocateContiguousMemory[Ex](size, ...)
                result = alloc("contig", arg0, 0x1000)
            elif ordinal == 184:  # NtAllocateVirtualMemory(&base, 0, &size, type, prot)
                a = struct.unpack("<3I", uc_.mem_read(esp + 4, 12))
                base = struct.unpack("<I", uc_.mem_read(a[0], 4))[0]
                size = (struct.unpack("<I", uc_.mem_read(a[2], 4))[0] + 0xFFF) & ~0xFFF
                if not base:
                    base = alloc("virtual", size, 0x10000)
                uc_.mem_write(a[0], struct.pack("<I", base))
                uc_.mem_write(a[2], struct.pack("<I", size))
            elif ordinal in (268, 269, 284, 298, 320):
                # Pure memory routines run for real (the heap checks its fill pattern
                # with RtlCompareMemory; a stand-in 0 corrupts its free lists).
                a = struct.unpack("<3I", uc_.mem_read(esp + 4, 12))
                if ordinal == 268:  # RtlCompareMemory(a, b, n) -> matching prefix
                    x, y = uc_.mem_read(a[0], a[2]), uc_.mem_read(a[1], a[2])
                    result = next((i for i in range(a[2]) if x[i] != y[i]), a[2])
                elif ordinal == 269:  # RtlCompareMemoryUlong(p, n, value)
                    x, pat = uc_.mem_read(a[0], a[1] & ~3), struct.pack("<I", a[2])
                    result = next((i for i in range(0, len(x), 4) if x[i : i + 4] != pat), len(x))
                elif ordinal == 284:  # RtlFillMemory(p, n, byte)
                    uc_.mem_write(a[0], bytes([a[2] & 0xFF]) * a[1])
                elif ordinal == 298:  # RtlMoveMemory(dst, src, n)
                    uc_.mem_write(a[0], bytes(uc_.mem_read(a[1], a[2])))
                else:  # RtlZeroMemory(p, n)
                    uc_.mem_write(a[0], bytes(a[1]))
            kernel_used[ordinal] = kernel_used.get(ordinal, 0) + 1
            kernel_order.append((ordinal, ret_to))
            uc_.reg_write(X.UC_X86_REG_EAX, result)
            uc_.reg_write(X.UC_X86_REG_ESP, esp + 4 + arg_bytes.get(ordinal, 0))
            uc_.reg_write(X.UC_X86_REG_EIP, ret_to)

        uc.hook_add(UC_HOOK_CODE, on_kernel, begin=0xFE000000, end=0xFE000FFF)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
    uc.hook_add(UC_HOOK_MEM_UNMAPPED, on_unmapped)
    uc.hook_add(UC_HOOK_INTR, on_intr)
    partial = False
    try:
        uc.emu_start(va, ret, count=500_000_000)
    except UcError as e:
        partial = True
        print(f"emulation stopped: {e} at {uc.reg_read(X.UC_X86_REG_EIP):08X}")
        sp = uc.reg_read(X.UC_X86_REG_ESP)
        print("  stack: " + " ".join("%08X" % v for v in struct.unpack("<16I", uc.mem_read(sp, 64))))
        if kernel_order:
            print(
                "  last kernel stand-ins (ordinal, return): " + ", ".join(f"{o}@{r:08X}" for o, r in kernel_order[-8:])
            )
            used = ", ".join(f"{o} x{n}" for o, n in sorted(kernel_used.items()))
            print("  kernel stand-ins (ordinal x calls): " + used)
        if post is None or not writer:
            return 2
        # The writes before the stop still compare: an early divergence shows up there.
        print(f"  partial comparison: the {len(writer)} bytes the reference wrote before stopping")
    eip = uc.reg_read(X.UC_X86_REG_EIP)
    print(f"function {va:08X}: emulated to {eip:08X} (return {ret:08X}); {len(writer)} bytes written")
    if kernel_used:
        print("  kernel stand-ins (ordinal x calls): " + ", ".join(f"{o} x{n}" for o, n in sorted(kernel_used.items())))
    if lifted_trace:
        names = (
            ["kind", "va", "eax", "ecx", "edx", "ebx", "esp", "esi", "edi"]
            + [f"[esp+{4 + 4 * k:X}]" for k in range(8)]
            + [f"*[esp+{4 + 4 * k:X}] hash" for k in range(8)]
        )
        print(f"  callee trace: lifted {len(lifted_trace)} events, oracle {len(oracle_trace)}")

        def key(row):  # registers and the first nargs stack slots (+ their hashes)
            if row[0] != "E":
                return row
            return row[:9] + row[9 : 9 + nargs] + row[17 : 17 + nargs]

        for n, (lt, ot) in enumerate(zip(lifted_trace, oracle_trace)):
            if key(lt) != key(ot):
                if ot[0] == "R" and lt[0] == "R":
                    diff = [f"block after return: oracle {ot[2]} lifted {lt[2]}"]
                else:
                    keep = set(range(9)) | set(range(9, 9 + nargs)) | set(range(17, 17 + nargs))
                    diff = [
                        f"{names[k]} oracle {ot[k]} lifted {lt[k]}"
                        for k in range(min(len(lt), len(ot)))
                        if lt[k] != ot[k] and k in keep
                    ]
                print(
                    f"  first divergence at event #{n} ({ot[0]} {ot[1]}; previous "
                    f"{' '.join(oracle_trace[n - 1][:2]) if n else '-'}): " + "; ".join(diff)
                )
                if ot[0] == "E":
                    print("    entry: " + " ".join(ot[1:17]))
                break
        else:
            print("  callee traces agree on the common prefix")
    if post is None:
        print("  no .post: the lifted call did not return")
        return 1
    for name, reg in (
        ("eax", X.UC_X86_REG_EAX),
        ("ebx", X.UC_X86_REG_EBX),
        ("esp", X.UC_X86_REG_ESP),
        ("ebp", X.UC_X86_REG_EBP),
        ("esi", X.UC_X86_REG_ESI),
        ("edi", X.UC_X86_REG_EDI),
    ):
        if partial:
            break
        e = uc.reg_read(reg)
        if e != post[name]:
            print(f"  register {name}: oracle {e:08X} lifted {post[name]:08X}")
    bad = []
    for address in sorted(writer):
        try:
            emu = uc.mem_read(address, 1)[0]
        except UcError:  # the faulting write of a partial run
            continue
        lifted = read(post_regions, address, 1)
        if lifted is None or lifted[0] != emu:
            bad.append((address, emu, None if lifted is None else lifted[0]) + writer[address])
    print(f"  {len(bad)} of {len(writer)} written bytes differ")
    by_insn = {}
    for address, emu, lifted, seq, eip in sorted(bad, key=lambda row: row[3]):
        by_insn.setdefault(eip, []).append((seq, address, emu, lifted))
    # In order of the earliest differing write: the first one is closest to the cause.
    for eip, rows in sorted(by_insn.items(), key=lambda kv: kv[1][0][0])[:limit]:
        seq, a, e, lifted = rows[0]
        print(
            f"  insn {eip:08X}: {len(rows)} bytes, first at write #{seq} {a:08X} oracle {e:02X} lifted "
            f"{'--' if lifted is None else format(lifted, '02X')}"
        )
    return 2 if partial else 1 if bad else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    limit = int(args[args.index("--max") + 1]) if "--max" in args else 20
    dump = None
    if "--dump-event" in args:  # --dump-event N OUT: reference state at trace event N -> OUT.pre
        k = args.index("--dump-event")
        dump = (int(args[k + 1]), args[k + 2])
    hook = (0x005A8B20, 0x005C0000)
    if "--hook" in args:  # --hook LO HI: code range for the callee trace
        k = args.index("--hook")
        hook = (int(args[k + 1], 16), int(args[k + 2], 16))
    nargs = int(args[args.index("--args") + 1]) if "--args" in args else 8  # stack slots compared
    xbe = args[args.index("--xbe") + 1] if "--xbe" in args else None
    sys.exit(main(args[0], limit, dump, hook, nargs, xbe))
