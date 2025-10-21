# scrape_gwlaw_anki.py
import os, re, time, random, csv, hashlib, logging
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

def get(url):
    logger.debug("Requesting %s", url)
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    logger.debug("Received %s (%s)", url, r.status_code)
    return r

def faculty_list_pages(start=BASE):
    page = 0
    while True:
        url = start if page == 0 else f"{start}?page={page}"
        try:
            resp = get(url)
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status == 404:
                logger.info("Reached end of pagination at page %d", page)
                break
            raise
        soup = BeautifulSoup(resp.text, "html.parser")
        yield soup, url
        page += 1
        time.sleep(random.uniform(1.5, 3.0))

def parse_faculty_cards(soup, page_url):
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
        # Title is usually a paragraph or div following the name
        title = ""
        title_candidate = card.find(class_=re.compile("(?i)title")) or card.find("p")
        if title_candidate:
            title = clean_text(title_candidate.get_text())
        img = card.find("img")
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

def clean_text(txt):
    txt = re.sub(r"\s+", " ", txt or "").strip()
    return txt

def fetch_profile(profile_url):
    resp = get(profile_url)
    soup = BeautifulSoup(resp.text, "html.parser")
    # Name and title
    h1 = soup.find(["h1","h2"], string=True)
    name = clean_text(h1.get_text()) if h1 else ""
    # Title line often sits near the H1
    title = ""
    if h1:
        for sib in h1.next_siblings:
            if getattr(sib, "name", None) in ["p","div"]:
                t = clean_text(sib.get_text())
                if t and len(t) < 300:
                    title = t
                    break
    # Bio: first substantial paragraph after title/name
    bio = ""
    for p in soup.select("p"):
        t = clean_text(p.get_text())
        if t and len(t) > 120 and "Contact:" not in t:
            bio = t
            break
    # Research profiles and publications
    pubs = []
    # On-page “Publications” anchor
    pub_hdr = soup.find(id=re.compile("(?i)publications")) or soup.find(string=re.compile("(?i)^Publications$"))
    if pub_hdr:
        # Collect following list items or paragraphs
        container = pub_hdr.parent if hasattr(pub_hdr, "parent") else soup
        for li in container.find_all(["li","p"]):
            t = clean_text(li.get_text())
            if 5 < len(t) < 500:
                pubs.append(t)
            if len(pubs) >= 3:
                break
    # If empty, try Scholarly Commons or SSRN
    if len(pubs) == 0:
        sc = soup.find("a", href=re.compile(r"scholarship\.law\.gwu\.edu|papers\.ssrn\.com"))
        if sc:
            try:
                pubs = fetch_latest_from_profile(sc.get("href"))
            except Exception:
                pubs = []
    # Image: prefer explicit img under profile header
    img = soup.select_one("img")
    img_url = urljoin(profile_url, img.get("src")) if img and img.get("src") else None
    return {
        "name": name,
        "title": title,
        "bio": bio,
        "img_url": img_url,
        "publications": pubs[:3]
    }

def fetch_latest_from_profile(url):
    # Simple best-effort: fetch first 3 items from profile page
    resp = get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    items = []
    for sel in ["li", ".article-title", "h3", "p"]:
        for node in soup.select(sel):
            t = clean_text(node.get_text())
            if t and len(t) > 10:
                items.append(t)
            if len(items) >= 3:
                break
        if len(items) >= 3:
            break
    return items[:3]

def download_image(url):
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

def scrape_all():
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
        # prefer list card title if profile title missing
        if not data["title"]:
            data["title"] = prof.get("title","")
        # prefer list card image if profile image missing
        if not data["img_url"]:
            data["img_url"] = prof.get("img_url")
        record = {**prof, **data}
        if not record.get("bio"):
            logger.warning("Missing bio for %s", record.get("name") or record["profile_url"])
        if not record.get("publications"):
            logger.warning("Missing publications for %s", record.get("name") or record["profile_url"])
        out.append(record)
        time.sleep(random.uniform(1.5, 3.0))
    return out

def export_csv(rows, path):
    fields = ["FrontImage","Name","Title","Bio","Publications","SourceURL","ImageSource"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            pubs = " • ".join(r.get("publications") or [])
            w.writerow({
                "FrontImage": r.get("image_filename") or "",
                "Name": r.get("name",""),
                "Title": r.get("title",""),
                "Bio": r.get("bio",""),
                "Publications": pubs,
                "SourceURL": r.get("profile_url",""),
                "ImageSource": r.get("img_url",""),
            })

def export_apkg(rows, path):
    model = genanki.Model(
        1607392319,
        "GW Faculty Photo→Back",
        fields=[
            {"name":"FrontImage"},
            {"name":"Name"},
            {"name":"Title"},
            {"name":"Bio"},
            {"name":"Publications"},
            {"name":"SourceURL"},
        ],
        templates=[{
            "name":"Card 1",
            "qfmt":"<div style='text-align:center;'>{{FrontImage}}</div>",
            "afmt":"{{FrontSide}}<hr><h2>{{Name}}</h2><div><i>{{Title}}</i></div><div style='margin-top:8px;'>{{Bio}}</div><div style='margin-top:8px;'><b>Latest publications</b><br>{{Publications}}</div><div style='margin-top:8px;'><a href='{{SourceURL}}'>Profile</a></div>",
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
            fields=[front_html, r.get("name",""), r.get("title",""), r.get("bio",""), " • ".join(r.get("publications") or []), r.get("profile_url","")],
            tags=["gwlaw","full-time-faculty", (r.get("name","")[:1] or "_").lower()]
        )
        deck.add_note(note)
    pkg = genanki.Package(deck)
    pkg.media_files = media
    pkg.write_to_file(path)
    logger.info("Wrote Anki package with %d notes to %s", len(rows), path)

def main():
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
