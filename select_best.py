#!/usr/bin/env python3
"""Select best-quality video per episode and copy to a destination folder.

This script groups files by the naming convention used by `downloader.py`:
  <prefix> - <original_name>
where <prefix> is typically "Sender - Thema - Titel" and <original_name
contains quality markers like `avc-1080`, `avc-720`, `xxl`, `xl`, `ml`, or numeric
resolutions (1080,720,360).

By default the script runs in dry-run mode and prints which file would be chosen.
Use `--apply` to actually copy the selected files to the destination directory.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
from typing import Dict, List, Tuple


VIDEO_EXTS = {'.mp4', '.mkv', '.webm', '.mov', '.avi'}


def quality_score(name: str) -> int:
    """Return an integer score for the quality indicated in `name`.

    Higher is better. Recognizes numeric resolutions (e.g. 1080, 720), and
    marker tokens (`xxl`, `xl`, `ml`). Falls back to 0 when unknown.
    """
    s = name.lower()
    # numeric resolution
    m = re.search(r'(\d{3,4})(?=[^\d]|$)', s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    # token mapping
    for token, score in (('xxl', 1500), ('xl', 1000), ('ml', 500), ('hd', 900)):
        if token in s:
            return score
    return 0


def group_files(src: str) -> Dict[str, List[Tuple[str, str, int, int]]]:
    """Group files by prefix (everything before the last ' - ').

    Returns mapping: prefix -> list of tuples (filename, orig_name, score, size)
    """
    groups: Dict[str, List[Tuple[str, str, int, int]]] = {}
    for fname in sorted(os.listdir(src)):
        path = os.path.join(src, fname)
        if not os.path.isfile(path):
            continue
        root, ext = os.path.splitext(fname)
        if ext.lower() not in VIDEO_EXTS:
            continue
        if ' - ' in fname:
            prefix, orig = fname.rsplit(' - ', 1)
        else:
            prefix = root
            orig = ''
        score = quality_score(orig or fname)
        size = os.path.getsize(path)
        groups.setdefault(prefix, []).append((fname, orig, score, size))
    return groups


def choose_best(items: List[Tuple[str, str, int, int]]) -> Tuple[str, int, int]:
    """Return the best item (filename, score, size) from the list.

    Tie-breaker: prefer higher score, then larger file size.
    """
    best = max(items, key=lambda t: (t[2], t[3]))
    return best[0], best[2], best[3]


def main() -> None:
    parser = argparse.ArgumentParser(description="Select best-quality video per episode")
    parser.add_argument('--src', '-s', default='downloads', help='Source directory with downloaded files')
    parser.add_argument('--dest', '-d', default='best', help='Destination directory for best files')
    parser.add_argument('--apply', action='store_true', help='Actually copy selected files (dry-run by default)')
    parser.add_argument('--overwrite', action='store_true', help='Overwrite existing files in destination')
    parser.add_argument('-v', '--verbose', action='count', default=0)
    args = parser.parse_args()

    level = logging.WARNING
    if args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO
    logging.basicConfig(level=level, format='%(asctime)s %(levelname)s: %(message)s')

    src = args.src
    dest = args.dest
    if not os.path.isdir(src):
        logging.error('Source directory not found: %s', src)
        raise SystemExit(1)

    groups = group_files(src)
    total = 0
    selected = []
    for prefix, items in sorted(groups.items()):
        fname, score, size = choose_best(items)
        total += 1
        selected.append((prefix, fname, score, size))

    if not selected:
        logging.info('No video files found in %s', src)
        return

    # Print plan
    for prefix, fname, score, size in selected:
        print(f'{prefix}\t{fname}\tquality={score}\tsize={size}')

    if not args.apply:
        logging.info('Dry-run complete: %d episodes (use --apply to copy)', total)
        return

    os.makedirs(dest, exist_ok=True)
    copied = 0
    for prefix, fname, score, size in selected:
        src_path = os.path.join(src, fname)
        dst_path = os.path.join(dest, fname)
        if os.path.exists(dst_path) and not args.overwrite:
            logging.info('Skipping existing: %s', dst_path)
            continue
        shutil.copy2(src_path, dst_path)
        copied += 1
        logging.info('Copied: %s -> %s', src_path, dst_path)

    logging.info('Done: %d copied to %s', copied, dest)


if __name__ == '__main__':
    main()
