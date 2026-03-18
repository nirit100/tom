#!/usr/bin/env python3
"""Downloader for mediathekviewweb search results.

This script uses Playwright to render the search pages, extracts MP4/HD
links and downloads them with requests.
"""
import argparse
import logging
import sys
import os
import time
from urllib.parse import quote_plus

import requests
try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None


DEFAULT_QUERY = "Tom und das Erdbeermarmeladebrot mit Honig"


def collect_links_playwright(query, pages, headless=True, timeout=12000):
    if sync_playwright is None:
        raise RuntimeError("Playwright is not installed. Install with 'pip install playwright' and run 'playwright install'.")
    links = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        for page_num in range(1, pages + 1):
            frag = f"#query={quote_plus(query)}&page={page_num}"
            url = f"https://mediathekviewweb.de/{frag}"
            logging.info("Playwright loading page %d: %s", page_num, url)
            try:
                page.goto(url, timeout=timeout)
                page.wait_for_selector("table tbody tr", timeout=timeout)
            except Exception:
                logging.debug("No rows found on page %d", page_num)
                break

            rows = page.query_selector_all("table tbody tr")
            new_found = 0
            # count of links already present from previous pages (before scanning this page)
            seen_before_count = 0
            anchors_total = 0
            # rows appear as pairs: data row (8 tds) followed by a link-row (1 td)
            i = 0
            seen_before = set(u.get('url') for u in links)
            seen = set(seen_before)
            while i < len(rows):
                data_row = rows[i]
                link_row = rows[i+1] if i+1 < len(rows) else None
                i += 2

                tds = data_row.query_selector_all("td")
                if len(tds) < 3:
                    continue
                try:
                    sender = tds[0].inner_text().strip()
                except Exception:
                    sender = ""
                try:
                    thema = tds[1].inner_text().strip()
                except Exception:
                    thema = ""
                try:
                    titel = tds[2].inner_text().strip()
                except Exception:
                    titel = ""

                # collect anchors from the following link_row if present, else from last TD
                anchors = []
                if link_row:
                    try:
                        anchors = link_row.query_selector_all('a')
                    except Exception:
                        anchors = []
                if not anchors:
                    try:
                        anchors = tds[-1].query_selector_all('a')
                    except Exception:
                        anchors = []

                anchors_total += len(anchors)
                for a in anchors:
                    href = a.get_attribute('href')
                    a_txt = (a.inner_text() or '').strip().lower()
                    if not href or not href.startswith('http'):
                        continue
                    # skip subtitles and API proxy links
                    if 'subtitle' in href or href.endswith('.vtt') or '/subtitle' in href:
                        continue
                    # accept common video file extensions or known CDN links
                    accept = False
                    for ext in ('.mp4', '.mkv', '.webm', '.mp3', '.aac'):
                        if ext in href:
                            accept = True
                            break
                    if not accept:
                        # also accept links that contain quality markers like '.xxl' or '.xl' or '.ml'
                        if any(x in href for x in ('.xxl', '.xl', '.ml', '.avc')):
                            accept = True
                    if not accept:
                        continue

                    original_name = href.split("/")[-1].split("?")[0]
                    if titel and thema:
                        candidate = f"{sender} - {thema} - {titel} - {original_name}" if sender else f"{thema} - {titel} - {original_name}"
                    elif titel:
                        candidate = f"{sender} - {titel} - {original_name}" if sender else f"{titel} - {original_name}"
                    else:
                        candidate = original_name
                    # if the URL was already collected on previous pages, count it so
                    # we can distinguish "page had only old links" from an empty/failed scan
                    if href in seen_before:
                        seen_before_count += 1
                        continue
                    # skip duplicates encountered within the same page
                    if href in seen:
                        continue
                    seen.add(href)
                    entry = {"url": href, "thema": thema, "titel": titel, "sender": sender, "orig_name": original_name, "candidate": candidate}
                    links.append(entry)
                    new_found += 1
            logging.info("Page %d: +%d new links added, %d old links seen, %d anchors scanned", page_num, new_found, seen_before_count, anchors_total)
        try:
            context.close()
            browser.close()
        except Exception:
            pass
    return links


def _sanitize_filename(name: str) -> str:
    # remove or replace characters illegal in filenames, collapse spaces
    import re
    name = name.strip()
    # replace path separators
    name = name.replace("/", "_")
    # remove control chars
    name = re.sub(r"[\x00-\x1f\x7f]+", "", name)
    # replace characters not allowed
    name = re.sub(r"[:\\\"\*\?<>\\|]+", "", name)
    # collapse multiple spaces
    name = re.sub(r"\s+", " ", name)
    # trim length
    return name[:200]


def download_file(url, outdir, session=None, filename=None, max_retries=3, allow_resume=True):
    """Download `url` to `outdir/filename` with retries, exponential backoff and resume.

    Supports resuming downloads when a partial .part file exists and the server
    accepts `Range` requests. Uses jittered exponential backoff between attempts.
    """
    import random

    session = session or requests.Session()
    if filename:
        local_name = os.path.join(outdir, filename)
    else:
        local_name = os.path.join(outdir, url.split("/")[-1].split("?")[0])
    if os.path.exists(local_name):
        return local_name

    part_name = local_name + ".part"
    # If resume is disabled, remove any existing partial file so we start fresh
    if not allow_resume and os.path.exists(part_name):
        try:
            os.remove(part_name)
        except Exception:
            pass

    for attempt in range(1, max_retries + 1):
        try:
            headers = {}
            mode = "wb"
            offset = 0
            if allow_resume and os.path.exists(part_name):
                offset = os.path.getsize(part_name)
                if offset > 0:
                    headers['Range'] = f'bytes={offset}-'
                    mode = 'ab'

            with session.get(url, stream=True, timeout=(10, 60), headers=headers) as r:
                # If we attempted a Range request but server returned 200,
                # restart the download from scratch (truncate .part).
                if r.status_code == 200 and mode == 'ab':
                    logging.debug('Server did not honor Range; restarting download for %s', url)
                    mode = 'wb'
                    offset = 0
                    # truncate
                    try:
                        open(part_name, 'wb').close()
                    except Exception:
                        pass
                r.raise_for_status()
                with open(part_name, mode) as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

            os.replace(part_name, local_name)
            return local_name

        except KeyboardInterrupt:
            # allow user interrupt to bubble up
            raise
        except Exception as exc:
            logging.warning('Download attempt %d failed for %s: %s', attempt, url, exc)
            if attempt == max_retries:
                logging.exception('Giving up on %s after %d attempts', url, attempt)
                raise
            # exponential backoff with jitter
            base = min(60, 2 ** (attempt - 1))
            sleep = base * (0.5 + random.random())
            logging.info('Retrying %s in %.1fs (attempt %d/%d)', url, sleep, attempt + 1, max_retries)
            time.sleep(sleep)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", "-q", default=DEFAULT_QUERY)
    parser.add_argument("--pages", "-p", type=int, default=5, help="Max pages to scrape")
    parser.add_argument("--out", "-o", default="downloads")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--collect-only", action="store_true", default=False,
                        help="Only collect links and print them to stdout, don't download")
    parser.add_argument("--skip-existing", action="store_true", default=False,
                        help="Skip files that already exist in the output directory")
    parser.add_argument("--jobs", type=int, default=1,
                        help="Number of parallel downloads (default 1 = sequential)")
    parser.add_argument("--verify-only", action="store_true", default=False,
                        help="Collect links and check whether suggested filenames exist in --out; do not download")
    parser.add_argument("--no-resume", action="store_true", default=False,
                        help="Disable HTTP resume (Range); always start downloads fresh")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase verbosity (-v INFO, -vv DEBUG)")
    args = parser.parse_args()

    level = logging.WARNING
    if args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO
    # send logs to stderr so collected links printed to stdout remain clean
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s: %(message)s", stream=sys.stderr)

    os.makedirs(args.out, exist_ok=True)

    logging.info("Using Playwright to collect links")
    entries = collect_links_playwright(args.query, args.pages, headless=args.headless)
    logging.info("Total MP4 links: %d", len(entries))

    if args.collect_only:
        # print collected links to stdout (one per line). Logging goes to stderr.
        for entry in entries:
            url = entry.get("url")
            thema = entry.get("thema", "")
            titel = entry.get("titel", "")
            orig = entry.get("orig_name", url.split("/")[-1].split("?")[0])
            candidate = entry.get("candidate", f"{thema} - {titel} - {orig}" if (thema or titel) else orig)
            sanitized = _sanitize_filename(candidate)
            # ensure extension present
            if "." not in sanitized and "." in orig:
                sanitized = f"{sanitized}.{orig.split('.')[-1]}"
            # Print URL and suggested filename separated by a tab to stdout
            print(f"{url}\t{sanitized}")
        return

    if args.verify_only:
        # verify whether suggested filenames exist in the output folder
        for entry in entries:
            url = entry.get("url")
            orig = entry.get("orig_name", url.split("/")[-1].split("?")[0])
            candidate = entry.get("candidate", orig)
            sanitized = _sanitize_filename(candidate)
            if "." not in sanitized and "." in orig:
                sanitized = f"{sanitized}.{orig.split('.')[-1]}"
            path = os.path.join(args.out, sanitized)
            status = "EXISTS" if os.path.exists(path) else "MISSING"
            # print to stdout for machine consumption, logs remain on stderr
            print(f"{status}\t{sanitized}\t{url}")
        return

    # perform downloads, optionally in parallel
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _prepare_entry(entry):
        url = entry["url"]
        thema = entry.get("thema", "")
        titel = entry.get("titel", "")
        orig = entry.get("orig_name", url.split("/")[-1].split("?")[0])
        candidate = entry.get("candidate", f"{thema} - {titel} - {orig}" if (thema or titel) else orig)
        sanitized = _sanitize_filename(candidate)
        if "." not in sanitized and "." in orig:
            sanitized = f"{sanitized}.{orig.split('.')[-1]}"
        return url, sanitized

    def _download_task(url, filename):
        # create a fresh session per worker to avoid sharing state
        if args.skip_existing:
            dest = os.path.join(args.out, filename)
            if os.path.exists(dest):
                logging.info("Skipping (exists): %s", dest)
                return (url, dest, "skipped")
        logging.info("Downloading: %s", url)
        try:
            path = download_file(url, args.out, session=None, filename=filename, allow_resume=not args.no_resume)
            logging.info("Saved: %s", path)
            return (url, path, "ok")
        except Exception:
            logging.exception("Failed: %s", url)
            return (url, None, "error")

    tasks = []
    if args.jobs <= 1:
        # sequential
        for entry in entries:
            url, filename = _prepare_entry(entry)
            _download_task(url, filename)
    else:
        with ThreadPoolExecutor(max_workers=args.jobs) as ex:
            futures = {ex.submit(_download_task, *_prepare_entry(e)): e for e in entries}
            for fut in as_completed(futures):
                fut.result()


if __name__ == "__main__":
    main()
