"""CLI for the data extraction pipeline.

Converts the upstream LU MII XML/JSON resources into our optimized data layout
under `tezaurs/data/`:

  paradigms.json   ← Lexicon_v2.xml   (58 paradigms + 2717 endings + global prefixes)
  tagset.json      ← TagSet.xml       (97 grammatical attributes with values)
  statistics.json  ← Statistics.xml   (corpus frequency counts for tagger)
  lexemes.parquet  ← 7 XML lexicons + 2 JSONL dumps (~270K lexemes, unified schema)

The pre-built data files are shipped in `tezaurs/data/`; this script is only
needed to regenerate them. Clone the upstream Java repo first:

  git clone https://github.com/PeterisP/morphology.git reference

Then run:
  python -m tools.extract_data                  # extract all
  python -m tools.extract_data paradigms        # one section
  python -m tools.extract_data --resources DIR  # custom upstream path
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from tools import lexemes as lexemes_mod
from tools import paradigms as paradigms_mod
from tools import statistics as statistics_mod
from tools import tagset as tagset_mod
from tools import tokenizer as tokenizer_mod

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESOURCES = REPO_ROOT / "reference" / "src" / "main" / "resources"
DEFAULT_JAVA_SRC = REPO_ROOT / "reference" / "src" / "main" / "java" / "lv" / "semti" / "morphology"
DEFAULT_DATA_OUT = REPO_ROOT / "tezaurs" / "data"


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _say(msg: str) -> None:
    print(f"[{_ts()}] {msg}", flush=True)


def extract_paradigms(resources: Path, data_out: Path) -> None:
    sources = [
        (resources / "Lexicon_v2.xml", "lv"),
        (resources / "Latgalian.xml", "ltg"),
    ]
    dst = data_out / "paradigms.json"
    _say(f"paradigms: {', '.join(s[0].name for s in sources)} → {dst.relative_to(REPO_ROOT)}")
    bundle = paradigms_mod.parse_paradigms(sources)
    paradigms_mod.write_paradigms(bundle, dst)
    by_lang: dict[str, int] = {}
    for p in bundle.paradigms:
        by_lang[p.language] = by_lang.get(p.language, 0) + 1
    _say(
        f"  paradigms={len(bundle.paradigms)} ({', '.join(f'{lang}={n}' for lang, n in by_lang.items())}) "
        f"endings={sum(len(p.endings) for p in bundle.paradigms)}"
    )


def extract_tagset(resources: Path, data_out: Path) -> None:
    for src_name, dst_name in (
        ("TagSet.xml", "tagset.json"),
        ("TagSet_Tilde.xml", "tagset_tilde.json"),
    ):
        src = resources / src_name
        dst = data_out / dst_name
        _say(f"tagset: {src.name} → {dst.relative_to(REPO_ROOT)}")
        ts = tagset_mod.parse_tagset(src)
        tagset_mod.write_tagset(ts, dst)
        _say(
            f"  attributes={len(ts.attributes)} "
            f"values={sum(len(a.values) for a in ts.attributes)} "
            f"free_attrs={len(ts.free_attributes)}"
        )


def extract_statistics(resources: Path, data_out: Path) -> None:
    src = resources / "Statistics.xml"
    dst = data_out / "statistics.json"
    _say(f"statistics: {src.name} → {dst.relative_to(REPO_ROOT)}")
    stats = statistics_mod.parse_statistics(src)
    statistics_mod.write_statistics(stats, dst)
    _say(
        f"  ending_freqs={len(stats.ending_frequencies)} "
        f"lexeme_freqs={len(stats.lexeme_frequencies)}"
    )


def extract_lexemes(resources: Path, data_out: Path) -> None:
    paradigms_json = data_out / "paradigms.json"
    if not paradigms_json.exists():
        _say("lexemes: paradigms.json not found, extracting it first")
        extract_paradigms(resources, data_out)
    dst = data_out / "lexemes.parquet"
    _say(f"lexemes: 7 XML + 2 JSONL → {dst.relative_to(REPO_ROOT)}")
    count = lexemes_mod.extract_lexemes(resources, paradigms_json, dst, log=sys.stdout)
    _say(f"  total rows: {count:,}  ({dst.stat().st_size / 1_000_000:.1f} MB on disk)")


def extract_tokenizer(resources: Path, data_out: Path) -> None:
    src = DEFAULT_JAVA_SRC / "analyzer" / "Splitting.java"
    dst = data_out / "tokenizer.json"
    _say(f"tokenizer: {src.name} → {dst.relative_to(REPO_ROOT)}")
    consts = tokenizer_mod.parse_tokenizer(src)
    tokenizer_mod.write_tokenizer(consts, dst)
    _say(f"  separators={len(consts.separators)} chars")


SECTIONS = {
    "paradigms": extract_paradigms,
    "tagset": extract_tagset,
    "statistics": extract_statistics,
    "lexemes": extract_lexemes,
    "tokenizer": extract_tokenizer,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "sections",
        nargs="*",
        choices=[*SECTIONS, "all"],
        help="which sections to extract (default: all)",
    )
    parser.add_argument(
        "--resources",
        type=Path,
        default=DEFAULT_RESOURCES,
        help=f"upstream resources dir (default: {DEFAULT_RESOURCES})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_DATA_OUT,
        help=f"output data dir (default: {DEFAULT_DATA_OUT})",
    )
    args = parser.parse_args(argv)

    if not args.resources.exists():
        parser.error(f"resources dir does not exist: {args.resources}")

    sections = list(SECTIONS) if not args.sections or "all" in args.sections else args.sections

    t0 = time.perf_counter()
    for s in sections:
        SECTIONS[s](args.resources, args.out)
    _say(f"done in {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
