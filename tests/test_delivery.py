"""Deliverable acquisition: the shapes eval/dev_set.yaml actually uses.

Counted from eval/dev_set.yaml: 14 dev tasks deliver a folder, 12 a
submission.zip, 2 a .py and 1 an .ifc. Before this, discovery never left the
workdir, never looked inside a zip, and the path regex had no zip/py at all, so
the gate layer read almost nothing on the public dev set.
"""
from __future__ import annotations

import asyncio
import io
import json
import pathlib
import sys
import tempfile
import unittest
import zipfile
from html import escape

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from extract import archive_members, text_of          # noqa: E402
from gates.cross import claims_of, extract_claims     # noqa: E402
from harness import GatedHarness                     # noqa: E402
from playbook import Playbook                        # noqa: E402
from protocol import Task, deliverables_of           # noqa: E402
from telemetry import Telemetry                      # noqa: E402
from verify import GATES                             # noqa: E402

CLAIMS = {
    "units": {"flexure.Mu_kip_ft": "kip-ft"},
    "flexure": {"Mu_kip_ft": 300, "Fy_ksi": 50},
    "requirements": [{"clause": "AISC 360-16 F2", "value": "phi Mn >= Mu"}],
}
BLOCK = "<!-- PLE-CLAIMS\n" + json.dumps(CLAIMS) + "\n-->"


def make_docx(paragraphs: list[str]) -> bytes:
    body = "".join(
        "<w:p><w:r><w:t>" + escape(p) + "</w:t></w:r></w:p>" for p in paragraphs)
    doc = ('<?xml version="1.0" encoding="UTF-8"?><w:document '
           'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{body}</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("word/document.xml", doc)
    return buf.getvalue()


def make_xlsx(strings: list[str], numbers: list[str]) -> bytes:
    shared = "".join(f"<si><t>{escape(text)}</t></si>" for text in strings)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", f"<sst>{shared}</sst>")
        cells = "".join(f"<c><v>{value}</v></c>" for value in numbers)
        archive.writestr("xl/worksheets/sheet1.xml",
                         f"<worksheet><sheetData><row>{cells}</row></sheetData></worksheet>")
    return buf.getvalue()


def make_zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buf.getvalue()


class FakeChannel:
    """Enough of TaskChannel to exercise collection without a container."""

    def __init__(self, files: dict[str, bytes], dirs: dict[str, list[str]]):
        self.files = files
        self.dirs = dirs
        self.requests: list[str] = []

    async def read_file(self, path: str) -> bytes:
        self.requests.append(f"read:{path}")
        if path in self.files:
            return self.files[path]
        raise FileNotFoundError(path)

    async def exec(self, command: str, timeout_sec=None):
        self.requests.append(f"exec:{command}")

        class Result:
            output = ""
            exit_code = 0
        result = Result()
        for directory, children in self.dirs.items():
            if directory in command:
                result.output = "\n".join(children)
                break
        return result


class TestPathParsing(unittest.TestCase):
    def test_absolute_paths_keep_their_root(self):
        task = Task(workdir="/app", session="t", instruction=(
            "Write the package to /filesystem/dc_structural__eor/output/submission.zip "
            "and the memo to /app/files/report.md."))
        paths = deliverables_of(task)
        self.assertIn("/filesystem/dc_structural__eor/output/submission.zip", paths)
        self.assertIn("/app/files/report.md", paths)

    def test_zip_py_and_directory_deliverables_are_declared(self):
        task = Task(workdir="/app", session="t", instruction=(
            "Deliver /app/files/dc_model__hall/output/solution.py, "
            "the model at /app/files/frontier__DCBim/submission/model.ifc "
            "and the package /filesystem/x/output/submission.zip."))
        paths = deliverables_of(task)
        self.assertIn("/app/files/dc_model__hall/output/solution.py", paths)
        self.assertIn("/filesystem/x/output/submission.zip", paths)
        self.assertIn("/app/files/frontier__DCBim/submission/model.ifc", paths)

    def test_bare_filename_still_parses(self):
        task = Task(workdir="/app", session="t", instruction="Write memo.md.")
        self.assertIn("memo.md", deliverables_of(task))


class TestExtraction(unittest.TestCase):
    def test_docx_text_keeps_the_claims_marker(self):
        text = text_of("memo.docx", make_docx(["Beam check.", BLOCK]))
        self.assertIsNotNone(text)
        self.assertIn("<!-- PLE-CLAIMS", text)
        self.assertIsNotNone(extract_claims(text), "claims block lost in docx runs")

    def test_xlsx_text_includes_shared_strings_and_values(self):
        text = text_of("calc.xlsx", make_xlsx(["Mu_kip_ft", BLOCK], ["300", "50"]))
        self.assertIn("Mu_kip_ft", text)
        self.assertIn("300", text)
        self.assertIsNotNone(extract_claims(text))

    def test_zip_members_are_readable(self):
        raw = make_zip({"memo.md": BLOCK.encode(), "calc.csv": b"a,b\n1,2\n"})
        members = dict(archive_members("submission.zip", raw))
        self.assertIn("memo.md", members)
        self.assertIn("<!-- PLE-CLAIMS", members["memo.md"])

    def test_unknown_binary_is_not_text(self):
        self.assertIsNone(text_of("model.ifc", b"ISO-10303-21;\x00\x01"))


class TestCollection(unittest.TestCase):
    def _harness(self):
        # tempfile, not the cwd: a test that writes telemetry next to the source
        # can leave directories behind and, worse, get them committed.
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="ple-test-"))
        return GatedHarness(client=object(), playbook=Playbook(tmp / "p.jsonl"),
                            telemetry=Telemetry(tmp, run_index=0, run_id="t"))

    def test_folder_deliverable_is_enumerated(self):
        harness = self._harness()
        channel = FakeChannel(
            files={"/app/files/memo.md": BLOCK.encode()},
            dirs={"/app/files/": ["/app/files/memo.md"]},
        )
        ctx = asyncio.run(harness._collect(channel, ["/app/files/"], "structural"))
        self.assertIn("/app/files/", ctx["present"])
        self.assertIn("/app/files/memo.md", ctx["texts"])
        self.assertTrue(claims_of(ctx), "claims block not read through the folder")

    def test_zip_package_is_opened(self):
        harness = self._harness()
        raw = make_zip({"memo.md": BLOCK.encode()})
        channel = FakeChannel(files={"/filesystem/x/output/submission.zip": raw}, dirs={})
        ctx = asyncio.run(harness._collect(
            channel, ["/filesystem/x/output/submission.zip"], "structural"))
        keys = list(ctx["texts"])
        self.assertTrue(any("submission.zip!" in key for key in keys), keys)
        self.assertTrue(claims_of(ctx), "claims block not read through the zip")

    def test_claims_gate_passes_from_a_zip_member(self):
        harness = self._harness()
        raw = make_zip({"memo.md": BLOCK.encode()})
        channel = FakeChannel(files={"/filesystem/x/output/submission.zip": raw}, dirs={})
        ctx = asyncio.run(harness._collect(
            channel, ["/filesystem/x/output/submission.zip"], "structural"))
        results = GATES.run("structural", {**ctx, "data": {"structural": {}, "revisions": []}})
        claims = [r for r in results if r.gate_id == "claims_present"]
        self.assertTrue(claims and claims[0].passed, [r.to_row() for r in claims])


if __name__ == "__main__":
    unittest.main()
