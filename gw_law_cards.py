# scrape_gwlaw_anki.py
import os
import re
import time
import random
import csv
import hashlib
import logging
from typing import Generator, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import genanki

BASE = "https://www.law.gwu.edu/full-time-faculty"
HEADERS = {"User-Agent":"Don-anki-builder/1.0 (+contact: you@example.com)"}
OUT_DIR = "out"
MEDIA_DIR = os.path.join(OUT_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)
logger = logging.getLogger(__name__)

def get(url: str) -> requests.Response:
    """Fetch a URL with proper headers and error handling."""
    logger.debug("Requesting %s", url)
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    logger.debug("Received %s (%s)", url, r.status_code)
    return r


def faculty_list_pages(
    start: str = BASE,
) -> Generator[tuple[BeautifulSoup, str], None, None]:
    """Iterate through paginated faculty directory pages."""
    page = 0
    while True:
        url = start if page == 0 else f"{start}?page={page}"
        resp = get(url)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Check if there are any faculty cards on this page
        cards = soup.select("div.gw-person-card")
        if len(cards) == 0:
            logger.info("Reached end of pagination at page %d", page)
            break

        yield soup, url
        page += 1
        time.sleep(random.uniform(1.5, 3.0))


def parse_faculty_cards(soup: BeautifulSoup, page_url: str) -> list[dict[str, str]]:
    entries = []
    cards = soup.select("div.gw-person-card")
    logger.debug("Found %d gw-person-card divs on %s", len(cards), page_url)
    for card in cards:
        link = card.find("a", href=True)
        if not link:
            logger.debug("Skipping card without anchor")
            continue
        href = link["href"]
        if href.startswith("mailto:"):
            continue
        full_url = urljoin(page_url, href)
        name = clean_text(link.get_text())
        heading = card.find(["h2", "h3", "h4"])
        if not name and heading:
            name = clean_text(heading.get_text())
        if not name:
            logger.warning("Card at %s missing name text", full_url)
            continue
        # Title is in the card-person-role paragraph
        title = ""
        title_candidate = card.find(class_="card-person-role")
        if title_candidate:
            title = clean_text(title_candidate.get_text())
        # Get image from card with specific class
        img = card.find("img", class_="gw-person-card-image")
        img_url = urljoin(page_url, img.get("src")) if img and img.get("src") else None
        entries.append({"name": name, "title": title, "profile_url": full_url, "img_url": img_url})
    # de-duplicate by profile_url
    uniq = []
    seen = set()
    for entry in entries:
        if entry["profile_url"] in seen:
            continue
        uniq.append(entry)
        seen.add(entry["profile_url"])
    return uniq

def clean_text(txt: Optional[str]) -> str:
    """Normalize whitespace in text."""
    txt = re.sub(r"\s+", " ", txt or "").strip()
    return txt


def fetch_profile(profile_url: str) -> dict[str, str]:
    resp = get(profile_url)
    soup = BeautifulSoup(resp.text, "html.parser")

    # Bio: first substantial paragraph in main content area
    bio = ""
    main = soup.find("main")
    if main:
        for p in main.find_all("p"):
            t = clean_text(p.get_text())
            # Skip short text, contact info, and email addresses
            if t and len(t) > 120 and "Contact:" not in t and "Email" not in t and "@" not in t:
                bio = t
                break

    # If no bio found in main, try all paragraphs
    if not bio:
        for p in soup.select("p"):
            t = clean_text(p.get_text())
            if t and len(t) > 120 and "Contact:" not in t and "Email" not in t and "@" not in t:
                bio = t
                break

    return {"bio": bio}


def download_image(url: Optional[str]) -> Optional[tuple[str, str]]:
    """Download an image and return (path, filename)."""
    if not url:
        return None
    filename = hashlib.sha1(url.encode()).hexdigest() + os.path.splitext(urlparse(url).path)[1][:5]
    path = os.path.join(MEDIA_DIR, filename)
    if not os.path.exists(path):
        logger.info("Downloading image %s", url)
        r = get(url)
        with open(path, "wb") as f:
            f.write(r.content)
        time.sleep(random.uniform(1.5, 3.0))
    else:
        logger.debug("Image already exists %s", path)
    return path, filename

def scrape_all() -> list[dict[str, str]]:
    people = []
    for soup, url in faculty_list_pages():
        entries = parse_faculty_cards(soup, url)
        logger.info("Parsed %d faculty entries from %s", len(entries), url)
        people.extend(entries)
        time.sleep(random.uniform(1.0, 2.0))
    # Deduplicate by profile URL
    keyed, out = {}, []
    for p in people:
        keyed[p["profile_url"]] = p
    for prof in keyed.values():
        logger.info("Fetching profile %s", prof["profile_url"])
        data = fetch_profile(prof["profile_url"])
        # Merge card data with profile data (card data takes precedence)
        record = {**data, **prof}
        if not record.get("bio"):
            logger.warning("Missing bio for %s", record.get("name") or record["profile_url"])
        out.append(record)
        time.sleep(random.uniform(1.5, 3.0))
    return out

def export_csv(rows: list[dict[str, str]], path: str) -> None:
    fields = ["FrontImage","Name","Title","Bio","SourceURL","ImageSource"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({
                "FrontImage": r.get("image_filename") or "",
                "Name": r.get("name",""),
                "Title": r.get("title",""),
                "Bio": r.get("bio",""),
                "SourceURL": r.get("profile_url",""),
                "ImageSource": r.get("img_url",""),
            })

def export_apkg(rows: list[dict[str, str]], path: str) -> None:
    model = genanki.Model(
        1607392319,
        "GW Faculty Photo→Back",
        fields=[
            {"name":"FrontImage"},
            {"name":"Name"},
            {"name":"Title"},
            {"name":"Bio"},
            {"name":"SourceURL"},
        ],
        templates=[{
            "name":"Card 1",
            "qfmt":"<div style='text-align:center;'>{{FrontImage}}</div>",
            "afmt":"{{FrontSide}}<hr><h2>{{Name}}</h2><div><i>{{Title}}</i></div><div style='margin-top:8px;'>{{Bio}}</div><div style='margin-top:8px;'><a href='{{SourceURL}}'>Profile</a></div>",
        }],
        css=".card { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial; font-size: 16px; } img { max-width: 100%; height:auto; }")
    deck = genanki.Deck(2059400110, "GW Law — Full-Time Faculty")
    media = []
    for r in rows:
        front_html = ""
        if r.get("image_filename"):
            front_html = f"<img src='{r['image_filename']}' />"
            media.append(os.path.join(MEDIA_DIR, r["image_filename"]))
        note = genanki.Note(
            model=model,
            fields=[front_html, r.get("name",""), r.get("title",""), r.get("bio",""), r.get("profile_url","")],
            tags=["gwlaw","full-time-faculty", (r.get("name","")[:1] or "_").lower()]
        )
        deck.add_note(note)
    pkg = genanki.Package(deck)
    pkg.media_files = media
    pkg.write_to_file(path)
    logger.info("Wrote Anki package with %d notes to %s", len(rows), path)

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger.info("Starting GW Law faculty scrape")
    rows = scrape_all()
    logger.info("Fetched %d faculty profiles", len(rows))
    # Download images and inject filenames
    for r in rows:
        img = r.get("img_url")
        if img:
            res = download_image(img)
            if res:
                _, fn = res
                r["image_filename"] = fn
                logger.info("Downloaded image for %s", r.get("name","(unknown)"))
        else:
            logger.warning("No image URL for %s", r.get("name") or r.get("profile_url"))
    os.makedirs(OUT_DIR, exist_ok=True)
    csv_path = os.path.join(OUT_DIR, "gwlaw_faculty.csv")
    apkg_path = os.path.join(OUT_DIR, "gwlaw_faculty.apkg")
    export_csv(rows, csv_path)
    logger.info("Wrote CSV to %s", csv_path)
    try:
        export_apkg(rows, apkg_path)
    except Exception as e:
        print("APKG build failed, CSV is available:", e)
        logger.exception("APKG export failed")
    else:
        logger.info("Completed scrape successfully")

if __name__ == "__main__":
    main()
