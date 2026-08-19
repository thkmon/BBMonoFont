#!/usr/bin/env python3
"""Structural and metric verification for generated BB Mono fonts."""

from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from pathlib import Path

from fontTools.ttLib import TTFont


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FONT_DIR = ROOT / "fonts"
EXPECTED = (
    ("BBMono-I-Regular.ttf", "BB Mono I", "Regular"),
    ("BBMono-I-Bold.ttf", "BB Mono I", "Bold"),
    ("BBMono-S-Regular.ttf", "BB Mono S", "Regular"),
    ("BBMono-S-Bold.ttf", "BB Mono S", "Bold"),
)
CJK_RANGES = (
    (0x1100, 0x11FF),
    (0x3000, 0x303F),
    (0x3130, 0x318F),
    (0x4E00, 0x9FFF),
    (0xA960, 0xA97F),
    (0xAC00, 0xD7A3),
    (0xD7B0, 0xD7FF),
    (0xFF00, 0xFFEF),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest.upper()


def names(font: TTFont, name_id: int) -> set[str]:
    result: set[str] = set()
    for record in font["name"].names:
        if record.nameID == name_id:
            try:
                result.add(record.toUnicode())
            except UnicodeDecodeError:
                pass
    return result


def expected_advance(codepoint: int) -> int:
    if 0xFF00 <= codepoint <= 0xFFEF and unicodedata.east_asian_width(chr(codepoint)) == "H":
        return 600
    return 1200


def check_font(path: Path, expected_family: str, expected_style: str) -> dict[str, object]:
    errors: list[str] = []
    font = TTFont(path, recalcBBoxes=False, recalcTimestamp=False)
    base_path = ROOT / "source-fonts" / "ibm-plex" / f"IBMPlexMono-{expected_style}.ttf"
    base = TTFont(base_path, recalcBBoxes=False, recalcTimestamp=False)
    try:
        cmap = font.getBestCmap()
        base_cmap = base.getBestCmap()
        metrics = font["hmtx"].metrics
        family_names = names(font, 1)
        style_names = names(font, 2)
        postscript_names = names(font, 6)

        if family_names != {expected_family}:
            errors.append(f"family names: {sorted(family_names)}")
        if style_names != {expected_style}:
            errors.append(f"style names: {sorted(style_names)}")
        expected_ps = f"{expected_family.replace(' ', '')}-{expected_style}"
        if postscript_names != {expected_ps}:
            errors.append(f"PostScript names: {sorted(postscript_names)}")
        latin_checks = "A0{}[]()<>/\\|_-=+abcdefghijklmnopqrstuvwxyz"
        for character in latin_checks:
            glyph_name = cmap.get(ord(character))
            if glyph_name is None:
                errors.append(f"missing Latin character U+{ord(character):04X}")
            elif metrics[glyph_name][0] != 600:
                errors.append(f"U+{ord(character):04X} advance is {metrics[glyph_name][0]}, expected 600")
            else:
                base_name = base_cmap.get(ord(character))
                if base_name is None:
                    errors.append(f"base font is missing U+{ord(character):04X}")
                else:
                    output_points = list(font["glyf"][glyph_name].getCoordinates(font["glyf"])[0])
                    base_points = list(base["glyf"][base_name].getCoordinates(base["glyf"])[0])
                    if output_points != base_points:
                        errors.append(f"U+{ord(character):04X} Latin outline changed")

        hangul_count = 0
        hangul_hinted = 0
        for codepoint in range(0xAC00, 0xD7A4):
            glyph_name = cmap.get(codepoint)
            if glyph_name is None:
                continue
            hangul_count += 1
            if metrics[glyph_name][0] != 1200:
                errors.append(f"U+{codepoint:04X} advance is not 1200")
                break
            glyph = font["glyf"][glyph_name]
            if getattr(glyph, "program", None) is not None and glyph.program.getBytecode():
                hangul_hinted += 1
        if hangul_count != 11172:
            errors.append(f"modern Hangul coverage is {hangul_count}, expected 11172")

        cjk_codepoints = {
            codepoint
            for start, end in CJK_RANGES
            for codepoint in range(start, end + 1)
            if codepoint in cmap
        }
        if len(cjk_codepoints) != 32904:
            errors.append(f"selected CJK coverage is {len(cjk_codepoints)}, expected 32904")
        for codepoint in cjk_codepoints:
            wanted = expected_advance(codepoint)
            if metrics[cmap[codepoint]][0] != wanted:
                errors.append(
                    f"selected CJK U+{codepoint:04X} advance is {metrics[cmap[codepoint]][0]}, expected {wanted}"
                )
                break
        if "TTFA" not in font:
            errors.append("TTFA table is missing; output was not autohinted")
        if hangul_hinted != 11172:
            errors.append(f"hinted modern Hangul glyphs: {hangul_hinted}, expected 11172")
        if "GSUB" not in font:
            errors.append("GSUB table is missing")
        else:
            base_lookups = len(base["GSUB"].table.LookupList.Lookup)
            output_lookups = len(font["GSUB"].table.LookupList.Lookup)
            if output_lookups != base_lookups + 1:
                errors.append(
                    f"GSUB lookup count is {output_lookups}; expected preserved base {base_lookups} + 1"
                )
            added_index = output_lookups - 1
            ccmp_records = [
                record
                for record in font["GSUB"].table.FeatureList.FeatureRecord
                if record.FeatureTag == "ccmp"
            ]
            if not ccmp_records or any(
                added_index not in record.Feature.LookupListIndex for record in ccmp_records
            ):
                errors.append("new Hangul lookup is not linked from every ccmp feature record")
        if font["post"].isFixedPitch != 1:
            errors.append("post.isFixedPitch is not 1")
        if font["head"].unitsPerEm != 1000:
            errors.append(f"unitsPerEm is {font['head'].unitsPerEm}, expected 1000")

        copyright_text = " ".join(names(font, 0))
        license_text = " ".join(names(font, 13))
        if "IBM Corp" not in copyright_text or "Renzhi Li" not in copyright_text:
            errors.append("combined upstream copyright metadata is incomplete")
        if "SIL Open Font License" not in license_text:
            errors.append("OFL metadata is missing")

        if errors:
            raise RuntimeError(path.name + " failed verification:\n  " + "\n  ".join(errors))
        return {
            "file": path.name,
            "family": expected_family,
            "style": expected_style,
            "glyphs": len(font.getGlyphOrder()),
            "mapped_codepoints": len(cmap),
            "modern_hangul": hangul_count,
            "hinted_modern_hangul": hangul_hinted,
            "selected_cjk": len(cjk_codepoints),
            "latin_advance": metrics[cmap[ord("A")]][0],
            "hangul_advance": metrics[cmap[0xAC00]][0],
            "gsub_lookups": len(font["GSUB"].table.LookupList.Lookup),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
    finally:
        font.close()
        base.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("font_dir", nargs="?", type=Path, default=DEFAULT_FONT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reports = []
    for filename, family, style in EXPECTED:
        path = args.font_dir / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        report = check_font(path, family, style)
        reports.append(report)
        print(
            f"OK {filename}: glyphs={report['glyphs']}, Hangul={report['modern_hangul']}, "
            f"advance={report['latin_advance']}:{report['hangul_advance']}"
        )
    (args.font_dir / "verification-report.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
