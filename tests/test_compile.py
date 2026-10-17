"""tools/compile.py's rewriting of generated C, on synthetic text (no game code)"""

from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import compile as wb  # noqa: E402

HEADER = b'#define RECOMP_GENERATED_CODE\n#include "recomp_funcs.h"\n#include <math.h>\n'


def body(name, text=b"    eax = 1;\n    esp += 4; return;\n"):
    return b"\nvoid " + name + b"(void)\n{\n" + text + b"\n}\n"


class ReplaceBodies(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def write(self, text):
        path = self.work / "recomp_0099.c"
        path.write_bytes(text)
        return path

    def test_untouched_file_is_compiled_as_is(self):
        source = self.write(HEADER + body(b"sub_00012000"))
        record = {}
        self.assertEqual(wb.replace_bodies(source, self.work, record), source)
        self.assertEqual(record, {})

    def test_override_and_quarantine_replace_only_their_bodies(self):
        text = (
            HEADER
            + body(b"sub_00012000")
            + body(b"sub_004B03B4", b'    RECOMP_UNIMPL("cli", 1);')
            + body(b"sub_000674C6", b"    if (!_cf) goto x;")
            + body(b"sub_00012100")
        )
        record = {}
        out = wb.replace_bodies(self.write(text), self.work, record).read_bytes()
        self.assertIn(b"void sub_004B03B4(void)\n{\n    fci_override_004B03B4();\n}\n", out)
        self.assertIn(b"void sub_000674C6(void)\n{\n    fci_quarantined_lift(0x000674C6u);\n}\n", out)
        self.assertNotIn(b"RECOMP_UNIMPL", out)
        self.assertNotIn(b"_cf", out)
        self.assertEqual(out.count(b"    eax = 1;"), 2)  # neighbours unchanged
        self.assertIn(b"void fci_override_004B03B4(void);", out)
        self.assertIn(b"void fci_quarantined_lift(uint32_t va);", out)
        self.assertEqual(record["replaced"][0]["functions"], ["sub_000674C6", "sub_004B03B4"])

    def test_windows_relift_crlf_still_gets_required_rewrites(self):
        text = (HEADER + body(b"sub_004B03B4", b'    RECOMP_UNIMPL("cli", 1);')).replace(b"\n", b"\r\n")
        record = {}
        out = wb.replace_bodies(self.write(text), self.work, record).read_bytes()
        self.assertIn(b"fci_override_004B03B4();", out)
        self.assertNotIn(b"\r\n", out)
        self.assertTrue(record["replaced"][0]["normalized_crlf"])

    def test_missing_branch_label_stops_on_its_original_condition(self):
        source = self.write(
            HEADER
            + body(
                b"sub_00012000", b"    if (eax) (void)0; /* goto loc_00012003 - dead code, label not in function */\n"
            )
        )
        record = {}
        out = wb.replace_bodies(source, self.work, record).read_bytes()
        self.assertIn(b"if (eax) fci_unresolved_stub(0x00012003u);", out)
        self.assertNotIn(b"(void)0", out)
        self.assertEqual(record["replaced"][0]["missing_gotos_stopped"], 1)

    def test_editor_overrides_do_not_capture_main_game_addresses(self):
        original = wb.REPLACE
        try:
            wb.REPLACE = {"sub_0005FBA4": ("override", "verified editor descriptor helper")}
            record = {}
            source = self.write(HEADER + body(b"sub_004B03B4") + body(b"sub_0005FBA4"))
            out = wb.replace_bodies(source, self.work, record).read_bytes()
            self.assertIn(b"fci_override_0005FBA4();", out)
            self.assertNotIn(b"fci_override_004B03B4();", out)
            self.assertEqual(record["replaced"][0]["functions"], ["sub_0005FBA4"])
        finally:
            wb.REPLACE = original

    def test_prefix_name_is_not_matched(self):
        source = self.write(HEADER + body(b"sub_004B03B40"))
        self.assertEqual(wb.replace_bodies(source, self.work, {}), source)

    def test_probe_wraps_only_the_named_function(self):
        import os

        os.environ["FCI_PROBE"] = "005b45b0"
        try:
            record = {}
            out = wb.replace_bodies(
                self.write(HEADER + body(b"sub_005B45B0") + body(b"sub_005B4580")), self.work, record
            ).read_bytes()
        finally:
            del os.environ["FCI_PROBE"]
        self.assertIn(
            b"void sub_005B45B0(void)\n{ fci_probe_enter(0x005b45b0u); sub_005B45B0_fci_body(); "
            b"fci_probe_leave(0x005b45b0u); }\nvoid sub_005B45B0_fci_body(void)\n{\n    eax = 1;",
            out,
        )
        self.assertIn(b"\nvoid sub_005B4580(void)\n{\n    eax = 1;", out)  # neighbour untouched
        self.assertIn(b"void fci_probe_enter(uint32_t va);", out)
        self.assertEqual(record["replaced"][0]["probes"], ["005b45b0"])

    def test_prehook_runs_before_the_unchanged_body(self):
        out = wb.replace_bodies(
            self.write(HEADER + body(b"sub_00580363") + body(b"sub_00580400")), self.work, {}
        ).read_bytes()
        self.assertIn(b"\nvoid sub_00580363_fci_body(void)\n{\n    eax = 1;", out)  # body kept
        self.assertIn(b"void sub_00580363(void) { fci_prehook_00580363(); sub_00580363_fci_body(); }", out)
        self.assertIn(b"\nvoid sub_00580400(void)\n{\n    eax = 1;", out)  # neighbour untouched
        self.assertIn(b"void fci_prehook_00580363(void);", out)

    def test_host_direct3d_switch_keeps_the_lifted_body(self):
        saved = wb.xbr_functions
        wb.xbr_functions = lambda: ["sub_005065A0"]
        try:
            out = wb.replace_bodies(
                self.write(HEADER + body(b"sub_005065A0") + body(b"sub_00506600")), self.work, {}
            ).read_bytes()
        finally:
            wb.xbr_functions = saved
        self.assertIn(b"\nvoid xbr_orig_sub_005065A0_c(void)\n{\n    eax = 1;", out)
        self.assertIn(
            b"void sub_005065A0(void) { if (fci_xbr_enabled()) xbr_sub_005065A0(); else xbr_orig_sub_005065A0_c(); }",
            out,
        )
        self.assertIn(b"\nvoid sub_00506600(void)\n{\n    eax = 1;", out)
        self.assertIn(b"int fci_xbr_enabled(void);", out)


class InstructionRewrites(unittest.TestCase):
    def test_port_io_and_wbinvd_become_runtime_calls(self):
        text = (
            b'    RECOMP_UNIMPL("out dx, al", 0x0050EA10u); /* TODO: out dx, al */\n'
            b'    RECOMP_UNIMPL("in eax, dx", 0x00400000u);\n'
            b'    RECOMP_UNIMPL("out 0x30, ax", 0x00400004u);\n'
            b'    RECOMP_UNIMPL("wbinvd", 0x0050BF84u);\n'
            b'    RECOMP_UNIMPL("outsd dx, dword ptr [esi]", 0x00400008u);\n'
        )
        out, count = wb.rewrite_ports(text)
        self.assertEqual(count, 4)
        self.assertIn(b"fci_port_out(LO16(edx), LO8(eax), 1, 0x0050EA10u);", out)
        self.assertIn(b"eax = fci_port_in(LO16(edx), 4, 0x00400000u);", out)
        self.assertIn(b"fci_port_out(0x30u, LO16(eax), 2, 0x00400004u);", out)
        self.assertIn(b"fci_wbinvd(0x0050BF84u);", out)
        self.assertIn(b'RECOMP_UNIMPL("outsd', out)  # string forms stay stops

    def test_failed_translation_becomes_stop(self):
        text = HEADER + b"void sub_002C4E84(void) { /* translation failed */ }\n"
        work = Path(tempfile.mkdtemp())
        try:
            source = work / "recomp_0098.c"
            source.write_bytes(text)
            record = {}
            out = wb.replace_bodies(source, work, record).read_bytes()
            self.assertIn(b"void sub_002C4E84(void) { fci_quarantined_lift(0x002C4E84u); }", out)
            self.assertEqual(record["replaced"][0]["failed_translations"], ["sub_002C4E84"])
        finally:
            shutil.rmtree(work, ignore_errors=True)


class UnresolvedStubs(unittest.TestCase):
    def test_stub_shape_rewrites_to_visible_stop(self):
        text = b"void sub_000122A0(void) { g_esp += 4; /* 0x000122A0: not detected */ }\n"
        self.assertEqual(len(wb.STUB.findall(text)), 1)
        out = wb.STUB.sub(rb"void \1(void) { fci_unresolved_stub(0x\2u); }", text)
        self.assertEqual(out, b"void sub_000122A0(void) { fci_unresolved_stub(0x000122A0u); }\n")


if __name__ == "__main__":
    unittest.main()
