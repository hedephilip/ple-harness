"""Text extraction for the formats PLE actually delivers.

Standard library only. The kit installs exactly what `requirements.txt` names,
inside a build that has internet but a container that does not, so pulling in
python-docx or openpyxl to read a handful of strings would grow the image for
three functions. `.docx`, `.xlsx`, `.pptx` and `.zip` are zip archives of XML;
Python reads them directly.

Why this exists: `docs/artifacts.md` and `eval/dev_set.yaml` show the dev set
delivering 12 `submission.zip` packages, 14 folders, 2 `.py` and 1 `.ifc`. A gate
layer that parses only `.md`/`.txt` declines nearly all of them and can never
recompute anything. Extraction is the difference between a gate and a no-op.
"""
from __future__ import annotations

import io
import re
import zipfile
from html import unescape

TEXT_SUFFIXES = (".md", ".txt", ".csv", ".json", ".py", ".html", ".htm",
                 ".xml", ".yaml", ".yml", ".log", ".ini", ".cfg", ".rst")
OOXML_SUFFIXES = (".docx", ".xlsx", ".pptx")
ARCHIVE_SUFFIXES = (".zip",)

_WS = re.compile(r"[ \t]+")
_EMPTY_LINES = re.compile(r"\n{3,}")


def is_text_name(name: str) -> bool:
    return str(name).lower().endswith(TEXT_SUFFIXES)


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS.sub(" ", text)
    return _EMPTY_LINES.sub("\n\n", text).strip()


def _runs(xml: bytes, pattern: bytes) -> list[str]:
    """Concatenate a paragraph's runs without separators.

    A claims block is split across runs by Word and friends. Joining runs with a
    space would turn `<!--` into `<! --` and destroy the marker the gate layer
    searches for, so runs are joined with nothing and paragraphs with newlines.
    """
    out: list[str] = []
    for para in re.split(pattern, xml):
        found = re.findall(rb"<[wa]:t\b[^>]*>(.*?)</[wa]:t>", para, re.S)
        if found:
            out.append(unescape(b"".join(found).decode("utf-8", "replace")))
    return out


def _docx_text(raw: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        xml = archive.read("word/document.xml")
    return _tidy("\n".join(_runs(xml, rb"</w:p>")))


def _xlsx_text(raw: bytes) -> str:
    parts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if "xl/sharedStrings.xml" in names:
            shared = archive.read("xl/sharedStrings.xml")
            for item in re.split(rb"</si>", shared):
                found = re.findall(rb"<t\b[^>]*>(.*?)</t>", item, re.S)
                if found:
                    parts.append(unescape(b"".join(found).decode("utf-8", "replace")))
        for name in names:
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                sheet = archive.read(name)
                for value in re.findall(rb"<v>(.*?)</v>", sheet, re.S):
                    parts.append(value.decode("utf-8", "replace"))
    return _tidy("\n".join(parts))


def _pptx_text(raw: bytes) -> str:
    parts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for name in sorted(archive.namelist()):
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                parts.extend(_runs(archive.read(name), rb"</a:p>"))
    return _tidy("\n".join(parts))


def text_of(name: str, raw: bytes | str) -> str | None:
    """Best-effort text for one artifact. None when the format hides its text."""
    if isinstance(raw, str):
        return raw
    if not raw:
        return None
    low = str(name).lower()
    try:
        if low.endswith(".docx"):
            return _docx_text(raw)
        if low.endswith(".xlsx"):
            return _xlsx_text(raw)
        if low.endswith(".pptx"):
            return _pptx_text(raw)
    except (zipfile.BadZipFile, KeyError, OSError):
        return None
    if low.endswith(TEXT_SUFFIXES):
        return raw.decode("utf-8", "replace")
    return None


def archive_members(name: str, raw: bytes, limit: int = 200) -> list[tuple[str, str]]:
    """(member path, text) for every text-bearing member of a zip deliverable."""
    out: list[tuple[str, str]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for member in archive.namelist()[:limit]:
                low = member.lower()
                if not low.endswith(TEXT_SUFFIXES + OOXML_SUFFIXES):
                    continue
                try:
                    data = archive.read(member)
                except (KeyError, OSError, zipfile.BadZipFile):
                    continue
                text = text_of(member, data)
                if text:
                    out.append((member, text))
    except (zipfile.BadZipFile, OSError):
        return []
    return out
