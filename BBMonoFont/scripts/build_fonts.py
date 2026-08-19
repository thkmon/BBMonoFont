#!/usr/bin/env python3
"""Build the BB Mono I and BB Mono S font families.

This implementation is intentionally self-contained.  It uses only the public
FontTools API and the unmodified upstream font binaries stored in source-fonts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.misc.roundTools import otRound
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable


ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = ROOT / "source-fonts"
DEFAULT_OUTPUT = ROOT / "fonts"
VERSION = "1.000"
LATIN_ADVANCE = 600
CJK_ADVANCE = 1200

IBM_COPYRIGHT = 'Copyright © 2017 IBM Corp. with Reserved Font Name "Plex".'
SARASA_COPYRIGHT = (
    "Copyright (c) 2015-2025, Renzhi Li. "
    "Portions Copyright (c) 2016 The Inter Project Authors. "
    "Portions Copyright (c) 2014-2021 Adobe Systems Incorporated, "
    "with Reserved Font Name 'Source'. "
    "Portions Copyright (c) 2012 Google Inc."
)

# Unicode blocks supplied by the CJK donor. Latin, ASCII punctuation, coding
# symbols, and every code point outside these ranges remain IBM Plex Mono.
CJK_RANGES = (
    (0x1100, 0x11FF),   # Hangul Jamo
    (0x3000, 0x303F),   # CJK Symbols and Punctuation
    (0x3130, 0x318F),   # Hangul Compatibility Jamo
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0xA960, 0xA97F),   # Hangul Jamo Extended-A
    (0xAC00, 0xD7A3),   # Modern Hangul syllables
    (0xD7B0, 0xD7FF),   # Hangul Jamo Extended-B
    (0xFF00, 0xFFEF),   # Halfwidth and Fullwidth Forms
)


@dataclass(frozen=True)
class DonorSpec:
    path: Path
    x_scale: float
    y_scale: float
    label: str


@dataclass(frozen=True)
class FamilySpec:
    suffix: str
    family: str
    primary: DonorSpec
    fallback: DonorSpec | None
    description: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def in_cjk_scope(codepoint: int) -> bool:
    return any(start <= codepoint <= end for start, end in CJK_RANGES)


def cell_advance(codepoint: int) -> int:
    """Use one cell for true halfwidth forms and two cells for CJK forms."""
    if 0xFF00 <= codepoint <= 0xFFEF and unicodedata.east_asian_width(chr(codepoint)) == "H":
        return LATIN_ADVANCE
    return CJK_ADVANCE


def glyph_bounds(glyph_set: object, glyph_name: str) -> tuple[float, float, float, float] | None:
    pen = BoundsPen(glyph_set)
    glyph_set[glyph_name].draw(pen)
    return pen.bounds


def modern_hangul_center(font: TTFont) -> float:
    cmap = font.getBestCmap()
    glyph_set = font.getGlyphSet()
    centers: list[float] = []
    for codepoint in range(0xAC00, 0xD7A4):
        glyph_name = cmap.get(codepoint)
        if glyph_name is None:
            continue
        bounds = glyph_bounds(glyph_set, glyph_name)
        if bounds is not None:
            centers.append((bounds[1] + bounds[3]) / 2.0)
    if len(centers) != 11172:
        raise RuntimeError(
            f"{font.reader.file.name} has {len(centers)} bounded modern Hangul glyphs; expected 11172"
        )
    return float(statistics.median(centers))


def ensure_full_unicode_cmap(font: TTFont) -> None:
    if any(table.format == 12 and table.platformID == 3 and table.platEncID == 10
           for table in font["cmap"].tables):
        return
    table = CmapSubtable.newSubtable(12)
    table.platformID = 3
    table.platEncID = 10
    table.language = 0
    table.cmap = dict(font.getBestCmap())
    font["cmap"].tables.append(table)


def update_cmaps(font: TTFont, mapping: dict[int, str]) -> None:
    ensure_full_unicode_cmap(font)
    for table in font["cmap"].tables:
        if not table.isUnicode() or table.format not in (4, 12):
            continue
        for codepoint, glyph_name in mapping.items():
            if table.format == 12 or codepoint <= 0xFFFF:
                table.cmap[codepoint] = glyph_name


def transformed_glyph(
    glyph_set: object,
    source_name: str,
    x_scale: float,
    y_scale: float,
    y_shift: float,
    advance: int,
) -> tuple[object, int]:
    bounds = glyph_bounds(glyph_set, source_name)
    if bounds is None:
        x_shift = 0.0
        left_side_bearing = 0
    else:
        xmin, _ymin, xmax, _ymax = bounds
        # Keep this expression in center-point form. Besides being easier to
        # audit, it avoids a floating-point reassociation at exact .5-unit
        # boundaries before TrueType's mandated rounding is applied.
        x_shift = advance / 2.0 - x_scale * (xmin + xmax) / 2.0
        left_side_bearing = otRound(xmin * x_scale + x_shift)

    # Decompose every component before renaming. This guarantees that a copied
    # glyph never keeps a reference to a donor-only glyph name.
    recording = DecomposingRecordingPen(glyph_set)
    glyph_set[source_name].draw(recording)
    destination = TTGlyphPen(None)
    transform = TransformPen(
        destination,
        (x_scale, 0.0, 0.0, y_scale, x_shift, y_shift),
    )
    recording.replay(transform)
    return destination.glyph(), left_side_bearing


def choose_donor(
    codepoint: int,
    primary_cmap: dict[int, str],
    fallback_cmap: dict[int, str],
) -> tuple[str, str] | None:

    # Use the family-specific primary donor wherever it has the requested
    # code point. BB Mono I therefore keeps IBM's Korean forms consistently,
    # while Sarasa supplies only missing Hanja and extended coverage.
    if codepoint in primary_cmap:
        return "p", primary_cmap[codepoint]
    if codepoint in fallback_cmap:
        return "f", fallback_cmap[codepoint]
    return None


def add_cjk_glyphs(
    base: TTFont,
    family: FamilySpec,
    primary: TTFont,
    fallback: TTFont | None,
    target_center: float,
) -> tuple[dict[int, str], dict[str, object]]:
    specs = {"p": family.primary}
    donor_centers = {"p": modern_hangul_center(primary)}
    donor_fonts = {"p": primary}
    if family.fallback is not None and fallback is not None:
        specs["f"] = family.fallback
        donor_centers["f"] = modern_hangul_center(fallback)
        donor_fonts["f"] = fallback

    donor_cmaps = {key: donor.getBestCmap() for key, donor in donor_fonts.items()}
    donor_glyph_sets = {key: donor.getGlyphSet() for key, donor in donor_fonts.items()}

    y_shifts = {
        key: target_center - donor_centers[key] * specs[key].y_scale
        for key in specs
    }

    available = set(donor_cmaps["p"])
    if "f" in donor_cmaps:
        available.update(donor_cmaps["f"])
    codepoints = sorted(cp for cp in available if in_cjk_scope(cp))

    base_glyf = base["glyf"]
    base_hmtx = base["hmtx"].metrics
    glyph_order = list(base.getGlyphOrder())
    mapping: dict[int, str] = {}
    copied: dict[tuple[str, str, int], str] = {}

    for codepoint in codepoints:
        selected = choose_donor(
            codepoint,
            donor_cmaps["p"],
            donor_cmaps.get("f", {}),
        )
        if selected is None:
            continue
        key, source_name = selected
        advance = cell_advance(codepoint)
        cache_key = (key, source_name, advance)
        destination_name = copied.get(cache_key)
        if destination_name is None:
            destination_name = f"bbm{family.suffix.lower()}{key}{codepoint:05X}"
            glyph, lsb = transformed_glyph(
                donor_glyph_sets[key],
                source_name,
                specs[key].x_scale,
                specs[key].y_scale,
                y_shifts[key],
                advance,
            )
            base_glyf.glyphs[destination_name] = glyph
            base_hmtx[destination_name] = (advance, lsb)
            glyph_order.append(destination_name)
            copied[cache_key] = destination_name
        mapping[codepoint] = destination_name

    base.setGlyphOrder(glyph_order)
    base_glyf.glyphOrder = glyph_order
    update_cmaps(base, mapping)
    return mapping, {
        "target_center": target_center,
        "donor_centers": donor_centers,
        "y_shifts": y_shifts,
        "codepoints": len(mapping),
        "glyphs": len(copied),
    }


def add_jamo_composition(font: TTFont, mapping: dict[int, str]) -> int:
    rules: list[str] = []
    triples: list[str] = []
    pairs: list[str] = []
    for syllable in range(0xAC00, 0xD7A4):
        index = syllable - 0xAC00
        leading = 0x1100 + index // 588
        vowel = 0x1161 + (index % 588) // 28
        tail_index = index % 28
        components = [leading, vowel]
        if tail_index:
            components.append(0x11A7 + tail_index)
        if syllable not in mapping or any(cp not in mapping for cp in components):
            continue
        names = [mapping[cp] for cp in components]
        statement = f"  sub {' '.join(names)} by {mapping[syllable]};"
        (triples if tail_index else pairs).append(statement)

    # Three-component rules must run first. Otherwise an LV rule could consume
    # the beginning of an LVT sequence before the full syllable is formed.
    rules.extend(triples)
    rules.extend(pairs)
    if len(rules) != 11172:
        raise RuntimeError(f"generated {len(rules)} Jamo composition rules; expected 11172")
    feature_text = "languagesystem DFLT dflt;\nfeature ccmp {\n" + "\n".join(rules) + "\n} ccmp;\n"

    # feaLib compiles a complete GSUB table; it does not merge one into an
    # existing table. Compile the Hangul lookup in isolation, restore IBM's
    # original GSUB, then append only the new lookup to every existing ccmp
    # feature record. This preserves IBM's ligatures and language systems.
    original_gsub = font["GSUB"]
    addOpenTypeFeaturesFromString(font, feature_text, tables=["GSUB"])
    compiled_gsub = font["GSUB"]
    new_lookups = list(compiled_gsub.table.LookupList.Lookup)
    if len(new_lookups) != 1:
        raise RuntimeError(f"expected one compiled Hangul lookup, got {len(new_lookups)}")
    font["GSUB"] = original_gsub

    lookup_list = original_gsub.table.LookupList
    new_index = len(lookup_list.Lookup)
    lookup_list.Lookup.extend(new_lookups)
    lookup_list.LookupCount = len(lookup_list.Lookup)
    ccmp_records = [
        record
        for record in original_gsub.table.FeatureList.FeatureRecord
        if record.FeatureTag == "ccmp"
    ]
    if not ccmp_records:
        raise RuntimeError("IBM base font has no ccmp feature to extend")
    for record in ccmp_records:
        if new_index not in record.Feature.LookupListIndex:
            record.Feature.LookupListIndex.append(new_index)
            record.Feature.LookupCount = len(record.Feature.LookupListIndex)
    return len(rules)


def set_name(font: TTFont, name_id: int, value: str) -> None:
    name_table = font["name"]
    name_table.names = [record for record in name_table.names if record.nameID != name_id]
    name_table.setName(value, name_id, 3, 1, 0x409)
    name_table.setName(value, name_id, 0, 4, 0)


def rewrite_metadata(font: TTFont, family: FamilySpec, style: str) -> None:
    full_name = f"{family.family} {style}"
    postscript_name = f"{family.family.replace(' ', '')}-{style}"
    names = {
        0: f"{IBM_COPYRIGHT} {SARASA_COPYRIGHT}",
        1: family.family,
        2: style,
        3: f"{full_name}; Version {VERSION}",
        4: full_name,
        5: f"Version {VERSION}",
        6: postscript_name,
        8: "BB Mono Font contributors",
        9: "IBM Plex type designers and Sarasa Gothic contributors",
        10: family.description,
        11: "https://github.com/thkmon/BBMonoFont",
        13: "This Font Software is licensed under the SIL Open Font License, Version 1.1.",
        14: "https://openfontlicense.org",
        16: family.family,
        17: style,
    }
    for name_id, value in names.items():
        set_name(font, name_id, value)

    # Remove typographic WWS names inherited from the base if present.
    for name_id in (18, 21, 22):
        font["name"].names = [n for n in font["name"].names if n.nameID != name_id]

    bold = style == "Bold"
    font["head"].macStyle = (font["head"].macStyle | 1) if bold else (font["head"].macStyle & ~1)
    font["head"].fontRevision = float(VERSION)
    font["head"].modified = font["head"].created
    font["OS/2"].usWeightClass = 700 if bold else 400
    if bold:
        font["OS/2"].fsSelection = (font["OS/2"].fsSelection | (1 << 5)) & ~(1 << 6)
    else:
        font["OS/2"].fsSelection = (font["OS/2"].fsSelection | (1 << 6)) & ~(1 << 5)
    font["post"].isFixedPitch = 1
    font["hhea"].advanceWidthMax = CJK_ADVANCE
    font["OS/2"].panose.bProportion = 9
    font["OS/2"].achVendID = "BBMF"
    font["OS/2"].recalcUnicodeRanges(font)
    if hasattr(font["OS/2"], "recalcCodePageRanges"):
        font["OS/2"].recalcCodePageRanges(font)
    for table_tag in ("hdmx", "LTSH", "VDMX"):
        if table_tag in font:
            del font[table_tag]
    if "DSIG" in font:
        del font["DSIG"]


def locate_autohinter() -> Path | None:
    candidates = [
        Path(sys.executable).resolve().parent / "ttfautohint.exe",
        Path(sys.executable).resolve().parent / "ttfautohint",
    ]
    try:
        import ttfautohint

        package_dir = Path(ttfautohint.__file__).resolve().parent
        candidates.extend((package_dir / "ttfautohint.exe", package_dir / "ttfautohint"))
    except ImportError:
        pass
    command = shutil.which("ttfautohint")
    if command:
        candidates.append(Path(command))
    return next((path for path in candidates if path.is_file()), None)


def autohint(source: Path, destination: Path) -> None:
    executable = locate_autohinter()
    if executable is None:
        raise RuntimeError("ttfautohint was not found; install ttfautohint-py==0.6.0")
    subprocess.run(
        [
            str(executable),
            "--increase-x-height=0",
            "--windows-compatibility",
            "--ttfa-table",
            str(source),
            str(destination),
        ],
        check=True,
    )


def family_specs(style: str) -> tuple[FamilySpec, FamilySpec]:
    ibm = SOURCE_ROOT / "ibm-plex"
    sarasa = SOURCE_ROOT / "sarasa-gothic"
    sans = DonorSpec(ibm / f"IBMPlexSansKR-{style}.ttf", 1.1363636363636365, 1.1363636363636365, "IBM Plex Sans KR")
    sarasa_donor = DonorSpec(sarasa / f"SarasaMonoK-{style}.ttf", 1.10, 1.08, "Sarasa Mono K")
    return (
        FamilySpec(
            "I",
            "BB Mono I",
            sans,
            sarasa_donor,
            "IBM Plex Mono Latin combined with IBM Plex Sans KR modern Hangul; Sarasa Mono K supplies additional CJK coverage.",
        ),
        FamilySpec(
            "S",
            "BB Mono S",
            sarasa_donor,
            None,
            "IBM Plex Mono Latin combined with Sarasa Mono K Hangul and CJK glyphs.",
        ),
    )


def build_one(family: FamilySpec, style: str, output_dir: Path, skip_autohint: bool) -> dict[str, object]:
    started = time.perf_counter()
    ibm = SOURCE_ROOT / "ibm-plex"
    base_path = ibm / f"IBMPlexMono-{style}.ttf"
    base = TTFont(base_path, recalcTimestamp=False)
    primary = TTFont(family.primary.path, recalcTimestamp=False)
    fallback = TTFont(family.fallback.path, recalcTimestamp=False) if family.fallback else None
    try:
        if base["head"].unitsPerEm != 1000:
            raise RuntimeError(f"unexpected base UPM: {base['head'].unitsPerEm}")
        target_source = TTFont(
            SOURCE_ROOT / "sarasa-gothic" / f"SarasaMonoK-{style}.ttf",
            recalcTimestamp=False,
        )
        try:
            target_center = modern_hangul_center(target_source)
        finally:
            target_source.close()

        old_lookup_count = len(base["GSUB"].table.LookupList.Lookup) if "GSUB" in base else 0
        mapping, copy_report = add_cjk_glyphs(base, family, primary, fallback, target_center)
        composition_rules = add_jamo_composition(base, mapping)
        rewrite_metadata(base, family, style)

        output_dir.mkdir(parents=True, exist_ok=True)
        final_path = output_dir / f"BBMono-{family.suffix}-{style}.ttf"
        with tempfile.TemporaryDirectory(prefix="bbmono-") as temp_dir:
            unhinted = Path(temp_dir) / final_path.name
            base.save(unhinted, reorderTables=False)
            if skip_autohint:
                shutil.copy2(unhinted, final_path)
            else:
                autohint(unhinted, final_path)

        # ttfautohint adjusts version metadata. Restore all public names and a
        # deterministic timestamp after hinting.
        finished = TTFont(final_path, recalcTimestamp=False)
        try:
            rewrite_metadata(finished, family, style)
            finished.save(final_path, reorderTables=False)
        finally:
            finished.close()

        return {
            "family": family.family,
            "style": style,
            "file": final_path.name,
            "base": base_path.name,
            "primary": family.primary.path.name,
            "fallback": family.fallback.path.name if family.fallback else None,
            "latin_advance": LATIN_ADVANCE,
            "cjk_advance": CJK_ADVANCE,
            "primary_scale": [family.primary.x_scale, family.primary.y_scale],
            "fallback_scale": [family.fallback.x_scale, family.fallback.y_scale] if family.fallback else None,
            "copied": copy_report,
            "jamo_composition_rules": composition_rules,
            "base_gsub_lookups": old_lookup_count,
            "output_gsub_lookups": len(base["GSUB"].table.LookupList.Lookup),
            "autohinted": not skip_autohint,
            "sha256": sha256(final_path),
            "bytes": final_path.stat().st_size,
            "seconds": round(time.perf_counter() - started, 3),
        }
    finally:
        base.close()
        primary.close()
        if fallback is not None:
            fallback.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-autohint", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    required = [
        SOURCE_ROOT / "ibm-plex" / f"IBMPlexMono-{style}.ttf"
        for style in ("Regular", "Bold")
    ]
    for style in ("Regular", "Bold"):
        required.extend(spec.primary.path for spec in family_specs(style))
        required.append(SOURCE_ROOT / "sarasa-gothic" / f"SarasaMonoK-{style}.ttf")
    missing = sorted({str(path) for path in required if not path.is_file()})
    if missing:
        raise FileNotFoundError("missing source files:\n  " + "\n  ".join(missing))

    reports: list[dict[str, object]] = []
    for style in ("Regular", "Bold"):
        for family in family_specs(style):
            print(f"Building {family.family} {style} ...", flush=True)
            report = build_one(family, style, args.output, args.skip_autohint)
            reports.append(report)
            print(f"  {report['file']}  {report['bytes']:,} bytes", flush=True)

    report_path = args.output / "build-report.json"
    report_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    checksum_lines = [
        f"{report['sha256']}  {report['file']}"
        for report in sorted(reports, key=lambda item: str(item["file"]))
    ]
    (args.output / "SHA256SUMS.txt").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="ascii",
    )
    print(f"Wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
