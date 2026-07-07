"""
Consolidate individual RAG case files into crime-category-grouped documents.

WHY: Zoho Catalyst QuickML KB has an undocumented ~12-document limit.
     Individual case files (220+) exceed this. Merging by crime category
     keeps document count low while keeping each document semantically
     coherent — the RAG retriever pulls the right category first, then
     the auto-chunker inside Zoho finds the specific case.

GROUPING LOGIC:
  - Parse the SECTIONS field from each case file
  - Normalize multi-section combos to their PRIMARY crime category:
      "Assault; Theft"  →  "Assault"  (primary listed first)
      "Drug possession/use; Drug trafficking"  →  "Drug Offences"
  - Cases with "Not on record" go into a catch-all "Uncategorised" doc
  - Each category becomes one consolidated .txt file

SCALABILITY:
  - Works with any number of input files
  - If a category grows beyond a configurable threshold (default 100 KB),
    it is split into numbered parts (e.g., Theft_part1.txt, Theft_part2.txt)
    to keep retrieval fast (smaller docs = tighter chunks)
  - The total number of output files is designed to stay ≤ 12

USAGE:
  python consolidate_cases.py [--input-dir rag_export] [--output-dir rag_consolidated] [--max-size-kb 100]
"""

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Crime category normalisation map
# ---------------------------------------------------------------------------
# Multi-section combinations are mapped to a single primary category.
# The key is the raw SECTIONS string; the value is the normalised category.
# Any raw value not listed here falls back to its first semicolon-delimited
# token (the primary section).

_CATEGORY_MAP = {
    # Drug combos → single bucket
    "Drug possession/use; Drug trafficking": "Drug Offences",
    "Drug possession/use":                   "Drug Offences",
    # Assault combos → primary "Assault" unless murder is involved
    "Assault; Murder":             "Murder",
    "Assault; Domestic Violence":  "Domestic Violence",
    "Assault; Robbery":            "Robbery",
    "Assault; Theft":              "Assault",
    # Fraud-family
    "Cheating by impersonation":   "Fraud and Cheating",
    "Identity theft":              "Fraud and Cheating",
    # Standalone keepers
    "Theft":               "Theft",
    "Assault":             "Assault",
    "Murder":              "Murder",
    "Robbery":             "Robbery",
    "Domestic Violence":   "Domestic Violence",
    # Catch-all
    "Not on record":       "Uncategorised",
}


def _normalise_category(raw_sections: str) -> str:
    """Return the normalised crime category for a raw SECTIONS line."""
    stripped = raw_sections.strip()
    if stripped in _CATEGORY_MAP:
        return _CATEGORY_MAP[stripped]
    # Fallback: use the first semicolon-delimited token
    first = stripped.split(";")[0].strip()
    if first in _CATEGORY_MAP:
        return _CATEGORY_MAP[first]
    return first or "Uncategorised"


def _parse_case_file(filepath: Path) -> tuple[str, str]:
    """
    Read a single case .txt file.
    Returns (normalised_category, full_file_content).
    """
    content = filepath.read_text(encoding="utf-8", errors="replace")
    # Extract SECTIONS line
    match = re.search(r"^SECTIONS:\s*(.+)$", content, re.MULTILINE)
    raw_sections = match.group(1).strip() if match else "Not on record"
    category = _normalise_category(raw_sections)
    return category, content


def _extract_crime_no(content: str) -> str:
    """Pull the Crime No from file content for the separator header."""
    match = re.search(r"Crime No:\s*(\S+)", content)
    return match.group(1) if match else "Unknown"


def _build_separator(crime_no: str) -> str:
    """Visible separator between cases inside a consolidated file."""
    bar = "=" * 60
    return f"\n{bar}\nCASE REPORT — Crime No: {crime_no}\n{bar}\n"


def consolidate(
    input_dir: Path,
    output_dir: Path,
    max_size_kb: int = 100,
) -> dict[str, list[str]]:
    """
    Main consolidation logic.

    Returns a dict mapping output filename → list of Crime Nos included.
    """
    # 1. Collect all case files
    case_files = sorted(input_dir.glob("case_*.txt"))
    if not case_files:
        print(f"No case_*.txt files found in {input_dir}", file=sys.stderr)
        return {}

    print(f"Found {len(case_files)} case files in {input_dir}")

    # 2. Group by normalised crime category
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for fp in case_files:
        category, content = _parse_case_file(fp)
        crime_no = _extract_crime_no(content)
        groups[category].append((crime_no, content))

    print(f"Grouped into {len(groups)} categories: {', '.join(sorted(groups))}")

    # 3. Write consolidated files (with optional splitting)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, list[str]] = {}
    max_bytes = max_size_kb * 1024

    for category, cases in sorted(groups.items()):
        safe_name = re.sub(r"[^A-Za-z0-9]+", "_", category).strip("_")
        parts: list[list[tuple[str, str]]] = [[]]
        current_size = 0

        for crime_no, content in cases:
            entry_size = len(_build_separator(crime_no).encode()) + len(content.encode())
            if current_size + entry_size > max_bytes and parts[-1]:
                parts.append([])
                current_size = 0
            parts[-1].append((crime_no, content))
            current_size += entry_size

        for idx, part_cases in enumerate(parts):
            if len(parts) > 1:
                filename = f"{safe_name}_part{idx + 1}.txt"
            else:
                filename = f"{safe_name}.txt"

            filepath = output_dir / filename
            crime_nos = []

            with open(filepath, "w", encoding="utf-8") as f:
                # Header for the consolidated document
                f.write(f"CRIME CATEGORY: {category}\n")
                f.write(f"Total cases in this file: {len(part_cases)}\n")
                f.write(f"{'=' * 60}\n\n")

                for crime_no, content in part_cases:
                    f.write(_build_separator(crime_no))
                    f.write(content.rstrip() + "\n")
                    crime_nos.append(crime_no)

            size_kb = filepath.stat().st_size / 1024
            manifest[filename] = crime_nos
            print(f"  {filename}: {len(crime_nos)} cases, {size_kb:.1f} KB")

    total_files = len(manifest)
    total_cases = sum(len(v) for v in manifest.values())
    print(f"\nConsolidation complete: {total_cases} cases -> {total_files} files")
    if total_files > 12:
        print(
            f"WARNING: {total_files} files exceed the Zoho KB 12-document limit. "
            f"Increase --max-size-kb to merge more aggressively.",
            file=sys.stderr,
        )
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Consolidate individual case files into crime-category documents for Zoho KB."
    )
    parser.add_argument(
        "--input-dir", default="rag_export",
        help="Directory containing individual case_*.txt files (default: rag_export)",
    )
    parser.add_argument(
        "--output-dir", default="rag_consolidated",
        help="Output directory for consolidated files (default: rag_consolidated)",
    )
    parser.add_argument(
        "--max-size-kb", type=int, default=100,
        help="Max size per consolidated file in KB before splitting (default: 100)",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    input_dir = script_dir / args.input_dir
    output_dir = script_dir / args.output_dir

    manifest = consolidate(input_dir, output_dir, args.max_size_kb)

    if manifest:
        # Write a manifest file for reference
        manifest_path = output_dir / "_manifest.txt"
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(f"Consolidated {sum(len(v) for v in manifest.values())} cases "
                    f"into {len(manifest)} files\n\n")
            for filename, crime_nos in sorted(manifest.items()):
                f.write(f"{filename} ({len(crime_nos)} cases):\n")
                for cn in crime_nos:
                    f.write(f"  {cn}\n")
                f.write("\n")
        print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
