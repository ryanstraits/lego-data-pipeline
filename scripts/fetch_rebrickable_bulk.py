"""
Pulls Rebrickable's free bulk catalog CSVs (sets, minifigs, inventory_minifigs),
filters down to the themes we care about (data/themes.csv), and diffs against
what we already have in data/minifigs_by_set.csv to find NEW sets and NEW
(rebrickable) fig numbers since last run.

Output:
  data/_new_sets.csv           -- sets seen for the first time this run
  data/_new_rebrickable_figs.csv -- rebrickable fig_nums seen for the first
                                    time this run, with the set(s) they came from
  data/sets_seen.csv           -- running list of every set_num we've processed
                                   (state file, committed back to the repo)

Rebrickable doesn't publish a permanently-fixed URL for these files, so we
scrape the current link off the downloads page rather than hardcoding a URL
that might go stale.
"""

import csv
import gzip
import io
import re
import requests

DOWNLOADS_PAGE = "https://rebrickable.com/downloads/"
DATA_DIR = "data"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def _find_download_url(filename):
    resp = requests.get(DOWNLOADS_PAGE, timeout=30, headers=HEADERS)
    resp.raise_for_status()
    # Look for an href ending in e.g. ".../sets.csv.gz" (possibly with a
    # query string / hash after it).
    pattern = re.compile(
        r'href=["\'](https?://[^"\']*' + re.escape(filename) + r'\.gz[^"\']*)["\']'
    )
    match = pattern.search(resp.text)
    if not match:
        raise RuntimeError(
            f"Couldn't find a download link for {filename} on the Rebrickable "
            f"downloads page. The page layout may have changed -- check "
            f"{DOWNLOADS_PAGE} manually."
        )
    return match.group(1)


def _download_gz_csv(filename):
    url = _find_download_url(filename)
    print(f"  Downloading {filename} from {url}")
    resp = requests.get(url, timeout=60, headers=HEADERS)
    resp.raise_for_status()
    with gzip.GzipFile(fileobj=io.BytesIO(resp.content)) as gz:
        text = gz.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def load_active_theme_names():
    names = set()
    with open(f"{DATA_DIR}/themes.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["active"].strip().lower() == "yes":
                names.add(row["rebrickable_theme_name"].strip().lower())
    return names


def build_theme_id_to_root_name(themes_rows):
    """
    Rebrickable's themes are hierarchical (e.g. 'Star Wars Episode 4/5/6' has
    a parent_id pointing to 'Star Wars'). A set's theme_id in sets.csv is
    almost always a specific sub-theme, not the parent -- so to filter by
    'Star Wars' we need to walk each theme up to its root and match on that
    root's name, not match theme_id directly against our config.
    """
    by_id = {row["id"]: row for row in themes_rows}

    def root_name(theme_id, _depth=0):
        row = by_id.get(theme_id)
        if row is None or _depth > 10:  # guard against unexpected cycles
            return None
        parent_id = row.get("parent_id") or ""
        if not parent_id:
            return row["name"]
        return root_name(parent_id, _depth + 1)

    return {tid: root_name(tid) for tid in by_id}


def load_sets_seen():
    try:
        with open(f"{DATA_DIR}/sets_seen.csv", newline="") as f:
            return set(row["set_num"] for row in csv.DictReader(f))
    except FileNotFoundError:
        return set()


def main():
    print("Fetching Rebrickable bulk data...")
    sets_rows = _download_gz_csv("sets")
    rb_themes_rows = _download_gz_csv("themes")
    inv_minifigs_rows = _download_gz_csv("inventory_minifigs")
    inventories_rows = _download_gz_csv("inventories")

    # inventory_minifigs links to inventories.csv (inventory_id -> set_num),
    # not directly to set_num, so build that lookup first.
    inv_to_set = {row["id"]: row["set_num"] for row in inventories_rows}

    theme_id_to_root = build_theme_id_to_root_name(rb_themes_rows)
    active_names = load_active_theme_names()

    theme_set_nums = {
        row["set_num"] for row in sets_rows
        if (theme_id_to_root.get(row.get("theme_id", "")) or "").strip().lower() in active_names
    }

    sets_seen_before = load_sets_seen()
    new_sets = theme_set_nums - sets_seen_before
    print(f"  {len(theme_set_nums)} sets match active themes; {len(new_sets)} are new this run")

    # Find fig appearances in newly-seen sets
    new_fig_rows = []
    for row in inv_minifigs_rows:
        set_num = inv_to_set.get(row["inventory_id"])
        if set_num in new_sets:
            new_fig_rows.append({
                "set_num": set_num,
                "rebrickable_fig_num": row["fig_num"],
                "quantity": row["quantity"],
            })

    with open(f"{DATA_DIR}/_new_sets.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["set_num"])
        for s in sorted(new_sets):
            w.writerow([s])

    with open(f"{DATA_DIR}/_new_rebrickable_figs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["set_num", "rebrickable_fig_num", "quantity"])
        w.writeheader()
        w.writerows(new_fig_rows)

    # Update the running state file
    all_seen = sets_seen_before | theme_set_nums
    with open(f"{DATA_DIR}/sets_seen.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["set_num"])
        for s in sorted(all_seen):
            w.writerow([s])

    print(f"Done. {len(new_sets)} new sets, {len(new_fig_rows)} new fig-in-set rows written.")


if __name__ == "__main__":
    main()
