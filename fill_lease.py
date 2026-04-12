#!/usr/bin/env python3
"""
Fill %%%PLACEHOLDER%%% tokens in lease_agreement.tex and compile to PDF with pdflatex.

Example:
  python fill_lease.py --fields lease_fields.example.yaml -o lease_out.pdf
  python fill_lease.py --fields instances/lukas.yaml -o lukas_lease.pdf

Required YAML keys are whatever %%%PLACEHOLDER%%% tokens appear in the .tex file
(see lease_fields.example.yaml for the full set). Keys listed in OPTIONAL_PLACEHOLDERS
in fill_lease.py may be omitted or left blank (e.g. PAYMENT_NOTE).

Requires PyYAML for --fields (pip install -r requirements.txt).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Placeholders in the .tex must look like %%%SOME_KEY%%%
PLACEHOLDER_RE = re.compile(r"%%%([A-Z0-9_]+)%%%")


def load_fields_yaml(path: Path) -> dict[str, str]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as e:
        raise SystemExit(
            "PyYAML is required for --fields. Install with: pip install -r requirements.txt"
        ) from e
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SystemExit("--fields YAML must be a mapping (object) at the top level")
    out: dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            raise SystemExit(f"--fields: keys must be strings, got {k!r}")
        if v is None:
            out[k] = ""
        elif isinstance(v, (dict, list)):
            raise SystemExit(f"--fields: value for {k!r} must be a scalar, not nested structure")
        else:
            out[k] = str(v)
    return out


def escape_latex(text: str) -> str:
    """Escape text for safe insertion into LaTeX body (not inside verbatim)."""
    out: list[str] = []
    for ch in text:
        if ch == "\\":
            out.append(r"\textbackslash{}")
        elif ch == "{":
            out.append(r"\{")
        elif ch == "}":
            out.append(r"\}")
        elif ch == "$":
            out.append(r"\$")
        elif ch == "&":
            out.append(r"\&")
        elif ch == "%":
            out.append(r"\%")
        elif ch == "#":
            out.append(r"\#")
        elif ch == "_":
            out.append(r"\_")
        elif ch == "~":
            out.append(r"\textasciitilde{}")
        elif ch == "^":
            out.append(r"\textasciicircum{}")
        else:
            out.append(ch)
    return "".join(out)


# Placeholders that may be omitted or blank in YAML (treated as empty in the PDF).
OPTIONAL_PLACEHOLDERS = frozenset({"PAYMENT_NOTE"})


def substitute_fields(tex: str, fields: dict[str, str], *, allow_partial: bool) -> str:
    found = sorted(set(PLACEHOLDER_RE.findall(tex)))
    if not allow_partial:
        missing = [
            k
            for k in found
            if k not in OPTIONAL_PLACEHOLDERS
            and (k not in fields or not str(fields[k]).strip())
        ]
        if missing:
            raise SystemExit(
                f"Missing or empty required fields: {', '.join(missing)}. "
                f"Use --fields YAML file or --set KEY=value for each. "
                f"Template expects: {', '.join(found)}."
            )
        extra = set(fields) - set(found)
        if extra:
            print(f"Warning: unused field keys (not in template): {sorted(extra)}", file=sys.stderr)

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        raw = fields.get(key)
        if raw is None or str(raw).strip() == "":
            if allow_partial:
                return match.group(0)
            if key in OPTIONAL_PLACEHOLDERS:
                return " "
            raise SystemExit(f"Internal error: placeholder {key!r} not filled")
        if key == "PAYMENT_NOTE":
            return f" {escape_latex(str(raw).strip())} "
        return escape_latex(str(raw))

    out = PLACEHOLDER_RE.sub(repl, tex)
    if not allow_partial:
        leftover = PLACEHOLDER_RE.findall(out)
        if leftover:
            raise SystemExit(f"Unfilled placeholders remain: {sorted(set(leftover))}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill lease LaTeX placeholders and build PDF.")
    parser.add_argument(
        "source",
        nargs="?",
        default="lease_agreement.tex",
        type=Path,
        help="Input .tex file (default: lease_agreement.tex)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output PDF path (default: <source_stem>_filled.pdf next to source)",
    )
    parser.add_argument(
        "--fields",
        type=Path,
        default=None,
        help="YAML file with string/scalar field keys (see lease_fields.example.yaml)",
    )
    parser.add_argument(
        "--set",
        dest="sets",
        action="append",
        default=[],
        metavar="KEY=value",
        help="Set one field (repeatable). Overrides values from --fields for that key.",
    )
    parser.add_argument(
        "--keep-tex",
        action="store_true",
        help="Keep the generated .filled.tex next to the source (default: temp dir only)",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Do not require all fields; leave missing tokens unchanged (template debug only).",
    )
    parser.add_argument(
        "--pdflatex",
        default="pdflatex",
        help="pdflatex executable name or path",
    )
    args = parser.parse_args()

    src = args.source.resolve()
    if not src.is_file():
        raise SystemExit(f"Source not found: {src}")

    fields: dict[str, str] = {}
    if args.fields:
        fields.update(load_fields_yaml(args.fields.resolve()))

    for item in args.sets:
        if "=" not in item:
            raise SystemExit(f"--set must be KEY=value, got: {item!r}")
        k, v = item.split("=", 1)
        fields[k.strip()] = v.strip()

    tex = src.read_text(encoding="utf-8")
    filled = substitute_fields(tex, fields, allow_partial=args.allow_partial)

    out_pdf = args.output
    if out_pdf is None:
        out_pdf = src.parent / f"{src.stem}_filled.pdf"
    else:
        out_pdf = out_pdf.resolve()

    if args.keep_tex:
        filled_tex = src.parent / f"{src.stem}.filled.tex"
        filled_tex.write_text(filled, encoding="utf-8")
        work_tex = filled_tex
        work_dir = src.parent
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="lease_build_"))
        filled_tex = work_dir / f"{src.stem}.filled.tex"
        filled_tex.write_text(filled, encoding="utf-8")
        work_tex = filled_tex

    for i in range(2):
        r = subprocess.run(
            [
                args.pdflatex,
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={work_dir}",
                str(work_tex),
            ],
            cwd=work_dir,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            print(r.stdout, file=sys.stderr)
            print(r.stderr, file=sys.stderr)
            raise SystemExit(f"pdflatex failed (pass {i + 1})")

    built = work_dir / f"{work_tex.stem}.pdf"
    if not built.is_file():
        raise SystemExit(f"Expected PDF not found: {built}")

    shutil.copy2(built, out_pdf)
    print(f"Wrote {out_pdf}")

    if not args.keep_tex:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
