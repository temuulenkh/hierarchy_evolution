"""
Scrape the Native American Ethnobotany Database (http://naeb.brit.org/).

Usage
-----
# Scrape tribe listing:
python3 scrape_naeb.py tribes

# Scrape species occurrences by genus:
python3 scrape_naeb.py quercus --genus Quercus --output naeb_quercus.csv
"""

import argparse
import csv
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL    = "http://naeb.brit.org"
SPECIES_URL = BASE_URL + "/uses/species/"
USES_URL    = BASE_URL + "/uses/"
TRIBES_URL  = BASE_URL + "/uses/tribes/"
HEADERS     = {"User-Agent": "Mozilla/5.0 (research scraper; contact: researcher)"}
DELAY       = 0.5


# ---------------------------------------------------------------------------
# Tribes
# ---------------------------------------------------------------------------

def scrape_tribes(session, output):
    tribes = []
    for page in range(1, 7):
        resp = session.get(f"{TRIBES_URL}?page={page}", headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=re.compile(r"^/uses/tribes/\d+/$")):
            tribe_id   = int(re.search(r"/uses/tribes/(\d+)/", a["href"]).group(1))
            tribe_name = a.get_text(strip=True)
            tribes.append({"tribe_id": tribe_id, "tribe_name": tribe_name})
            print(f"  {tribe_id:3d}  {tribe_name}")
        time.sleep(DELAY)

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["tribe_id", "tribe_name"])
        writer.writeheader()
        writer.writerows(tribes)

    print(f"\nSaved {len(tribes)} tribes → {output}")


# ---------------------------------------------------------------------------
# Quercus (genus occurrences)
# ---------------------------------------------------------------------------

def get_species_ids_for_genus(session, genus, max_pages=50):
    species_list = []
    genus_first  = genus[0].upper()
    print(f"Scanning species listing for genus '{genus}'...")

    for page in range(1, max_pages + 1):
        resp = session.get(SPECIES_URL, params={"page": page}, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        links      = soup.find_all("a", href=re.compile(r"/uses/species/\d+/"))
        page_names = [a.get_text(strip=True) for a in links]

        for a in links:
            m    = re.search(r"/uses/species/(\d+)/", a["href"])
            name = a.get_text(strip=True)
            if m and (name.startswith(genus + " ") or name.startswith(genus + "\xa0")):
                species_list.append((int(m.group(1)), name))

        last_name = page_names[-1] if page_names else ""
        n_hits    = sum(1 for n in page_names if n.startswith(genus))
        print(f"  page {page:3d}: {len(page_names):3d} species, "
              f"{n_hits} {genus}  (total: {len(species_list)})  last: {last_name[:45]}")

        if not page_names:
            break
        if last_name and last_name[0].upper() > genus_first:
            break
        time.sleep(DELAY)

    seen, unique = set(), []
    for sid, name in species_list:
        if sid not in seen:
            seen.add(sid)
            unique.append((sid, name))
    return unique


def get_use_ids_for_species(session, species_id):
    url  = f"{SPECIES_URL}{species_id}/"
    resp = session.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    use_ids = []
    for a in soup.find_all("a", href=re.compile(r"^/uses/\d+/$")):
        m = re.search(r"/uses/(\d+)/", a["href"])
        if m:
            use_ids.append(int(m.group(1)))
    return use_ids


def scrape_detail_page(session, use_id):
    url  = f"{USES_URL}{use_id}/"
    resp = session.get(url, headers=HEADERS, timeout=20)
    if resp.status_code != 200:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")

    containers = soup.find_all("div", class_="container")
    container  = containers[-1] if containers else None
    if not container:
        return None

    source = ""
    for strong in container.find_all("strong"):
        if "Use documented by" in strong.get_text():
            parts = []
            node  = strong.next_sibling
            while node and not (hasattr(node, "name") and node.name in ("hr", "p")):
                if isinstance(node, str):
                    text = node.strip()
                    if text:
                        parts.append(text)
                node = node.next_sibling
            raw    = " ".join(parts)
            source = re.sub(r"\s*View all documented uses.*", "", raw).strip()
            break

    fields = {}
    notes  = ""
    hr     = container.find("hr")
    if hr:
        chunks = []
        node   = hr.next_sibling
        while node:
            if hasattr(node, "name") and node.name == "p":
                break
            if isinstance(node, str):
                chunks.append(node)
            elif hasattr(node, "name") and node.name == "br":
                chunks.append("\n")
            node = node.next_sibling
        text_block = "".join(chunks)

        m = re.search(r"Notes:\s*(.*)", text_block, re.DOTALL)
        if m:
            notes = m.group(1).strip()

        for line in text_block.splitlines():
            line = line.strip()
            if line.startswith("Notes"):
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                fields[key.strip()] = val.strip()

    return {
        "scientific_name": fields.get("Scientific name", ""),
        "common_name":     fields.get("Common names", ""),
        "family":          fields.get("Family", ""),
        "culture":         fields.get("Native American Tribe", ""),
        "use_category":    fields.get("Use category", ""),
        "use_subcategory": fields.get("Use sub-category", ""),
        "notes":           notes,
        "source":          source,
    }


def scrape_genus(session, genus, output):
    species_list = get_species_ids_for_genus(session, genus)
    print(f"\nFound {len(species_list)} {genus} species. Collecting use IDs...\n")

    all_use_ids  = []
    seen_species = set()
    for i, (sid, name) in enumerate(species_list, 1):
        print(f"[{i}/{len(species_list)}] {name} (id={sid})")
        use_ids = get_use_ids_for_species(session, sid)
        new_ids = [uid for uid in use_ids if uid not in seen_species]
        seen_species.update(new_ids)
        all_use_ids.extend(new_ids)
        print(f"  → {len(use_ids)} uses  (total unique: {len(all_use_ids)})")
        time.sleep(DELAY)

    print(f"\nScraping {len(all_use_ids)} detail pages...\n")

    fieldnames = [
        "scientific_name", "common_name", "family",
        "culture", "use_category", "use_subcategory", "notes", "source",
    ]
    all_rows = []
    seen_ids = set()

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for i, use_id in enumerate(all_use_ids, 1):
            if use_id in seen_ids:
                continue
            seen_ids.add(use_id)
            rec = scrape_detail_page(session, use_id)
            if rec:
                writer.writerow(rec)
                all_rows.append(rec)
            if i % 50 == 0:
                print(f"  {i}/{len(all_use_ids)} scraped ({len(all_rows)} records written)")
            time.sleep(DELAY)

    print(f"\nDone. Saved {len(all_rows)} records → {output}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scrape the NAEB database.")
    sub    = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("tribes", help="Scrape the full tribe listing.")

    p_genus = sub.add_parser("quercus", help="Scrape species occurrences by genus.")
    p_genus.add_argument("--genus",  default="Quercus", metavar="NAME",
                         help="Genus to scrape (default: Quercus).")
    p_genus.add_argument("--output", default="naeb_quercus.csv",
                         help="Output CSV filename.")

    args    = parser.parse_args()
    session = requests.Session()
    out_dir = Path(__file__).parent.parent

    if args.command == "tribes":
        scrape_tribes(session, out_dir / "naeb_tribes.csv")
    elif args.command == "quercus":
        scrape_genus(session, args.genus, out_dir / args.output)


if __name__ == "__main__":
    main()
