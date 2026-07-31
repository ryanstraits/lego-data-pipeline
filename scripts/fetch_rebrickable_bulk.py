"""
Pulls Rebrickable set/theme/minifig data via the official REST API, filters
down to the themes we care about (data/themes.csv), and diffs against what
we already have in data/sets_seen.csv to find NEW sets and NEW (rebrickable)
fig numbers since last run.

Output:
  data/_new_sets.csv           -- sets seen for the first time this run
  data/_new_rebrickable_figs.csv -- rebrickable fig_nums seen for the first
                                    time this run, with the set(s) they came from
  data/sets_seen.csv           -- running list of every set_num we've processed
                                   (state file, committed back to the repo)

Earlier versions of this script scraped Rebrickable's /downloads/ page for
bulk CSV.gz dumps, but that page is now behind an active Cloudflare JS
challenge that a plain HTTP client can't solve. The REST API used here
(themes/sets list endpoints + per-set minifigs sub-resource) isn't behind
that challenge and covers the same data at a similar request cost --
~1 call for themes, ~28 paginated calls to list all sets, plus one call per
newly-discovered set to fetch its minifigs.
"""

import csv
import os
import time
import requests

DATA_DIR = "data"
API_BASE = "https://rebrickable.com/api/v3/lego"
REBRICKABLE_API_KEY = os.environ.get("REBRICKABLE_API_KEY", "")
PAGE_SIZE = 1000
SLEEP_INTERVAL = 0.4  # between per-set minifig lookups, to stay well under any rate limit
MAX_RETRIES = 5


def _headers():
    if not REBRICKABLE_API_KEY:
        raise EnvironmentError("REBRICKABLE_API_KEY is not set.")
    return {"Authorization": f"key {REBRICKABLE_API_KEY}"}


def _get_with_retries(url, params):
    for attempt in range(MAX_RETRIES):
        resp = requests.get(url, headers=_headers(), params=params, timeout=30)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 5 * (attempt + 1)))
            print(f"  [rate limited] waiting {wait}s before retrying...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"Repeated 429s from {url}, giving up after {MAX_RETRIES} retries.")


def _paginated(url, params):
    """Walk a DRF-style paginated endpoint, yielding each result row."""
    params = dict(params, page_size=PAGE_SIZE)
    while url:
        resp = _get_with_retries(url, params)
        data = resp.json()
        for row in data["results"]:
            yield row
        url = data.get("next")
        params = None  # 'next' already has the query string baked in


def fetch_all_themes():
    return list(_paginated(f"{API_BASE}/themes/", {}))


def fetch_all_sets():
    return list(_paginated(f"{API_BASE}/sets/", {}))


def fetch_set_minifigs(set_num):
    """
    Rebrickable represents each minifig as its own "set" with a fig-NNNNNN
    number, so this sub-resource's rows carry that number under the
    "set_num" key -- not to be confused with the real set's set_num.
    """
    rows = list(_paginated(f"{API_BASE}/sets/{set_num}/minifigs/", {}))
    return [
        {
            "set_num": set_num,
            "rebrickable_fig_num": row["set_num"],
            "quantity": row["quantity"],
        }
        for row in rows
    ]


def load_active_theme_names():
    names = set()
    with open(f"{DATA_DIR}/themes.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["active"].strip().lower() == "yes":
                names.add(row["rebrickable_theme_name"].strip().lower())
    return names


def build_theme_id_to_root_name(themes_rows):
    """
    Rebrickable's themes are hierarchical (e.g. 'Star Wars: Rebels' has a
    parent_id pointing to 'Star Wars'). A set's theme_id is almost always a
    specific sub-theme, not the parent -- so to filter by 'Star Wars' we need
    to walk each theme up to its root and match on that root's name, not
    match theme_id directly against our config.
    """
    by_id = {row["id"]: row for row in themes_rows}

    def root_name(theme_id, _depth=0):
        row = by_id.get(theme_id)
        if row is None or _depth > 10:  # guard against unexpected cycles
            return None
        parent_id = row.get("parent_id")
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
    print("Fetching Rebrickable theme + set data via API...")
    themes_rows = fetch_all_themes()
    sets_rows = fetch_all_sets()

    theme_id_to_root = build_theme_id_to_root_name(themes_rows)
    active_names = load_active_theme_names()

    theme_set_nums = {
        row["set_num"] for row in sets_rows
        if (theme_id_to_root.get(row.get("theme_id")) or "").strip().lower() in active_names
    }

    sets_seen_before = load_sets_seen()
    new_sets = theme_set_nums - sets_seen_before
    print(f"  {len(theme_set_nums)} sets match active themes; {len(new_sets)} are new this run")

    new_fig_rows = []
    for i, set_num in enumerate(sorted(new_sets), 1):
        print(f"  [{i}/{len(new_sets)}] Fetching minifigs for {set_num}")
        new_fig_rows.extend(fetch_set_minifigs(set_num))
        time.sleep(SLEEP_INTERVAL)

    with open(f"{DATA_DIR}/_new_sets.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["set_num"])
        for s in sorted(new_sets):
            w.writerow([s])

    with open(f"{DATA_DIR}/_new_rebrickable_figs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["set_num", "rebrickable_fig_num", "quantity"])
        w.writeheader()
        w.writerows(new_fig_rows)

    all_seen = sets_seen_before | theme_set_nums
    with open(f"{DATA_DIR}/sets_seen.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["set_num"])
        for s in sorted(all_seen):
            w.writerow([s])

    print(f"Done. {len(new_sets)} new sets, {len(new_fig_rows)} new fig-in-set rows written.")


if __name__ == "__main__":
    main()
