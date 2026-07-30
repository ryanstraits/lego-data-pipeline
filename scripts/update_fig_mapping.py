"""
For any Rebrickable fig numbers discovered by fetch_rebrickable_bulk.py
(data/_new_rebrickable_figs.csv), resolve them to a BrickLink minifig ID:

  1. Check the cached crosswalk (data/fig_bricklink_map.csv). If there's a
     TRUSTED entry (match_score >= CONFIDENCE_THRESHOLD), use it.
  2. Otherwise, call Rebrickable's live API for that fig's external_ids and
     look for a BrickLink reference. This is the authoritative source, but
     it costs one API call per fig -- which is fine here because we only
     ever do it for genuinely new figs, not the whole catalog.
  3. Anything still unresolved gets logged to data/_unmapped_figs.csv for
     manual review rather than silently dropped.

Appends newly resolved figs to data/minifigs_by_set.csv (the BrickLink-ID
keyed table Power Query reads) and to data/fig_bricklink_map.csv (so we
don't have to look them up again next time).
"""

import csv
import os
import requests

DATA_DIR = "data"
CONFIDENCE_THRESHOLD = 85.0
REBRICKABLE_API_KEY = os.environ.get("REBRICKABLE_API_KEY", "")


def load_new_figs():
    try:
        with open(f"{DATA_DIR}/_new_rebrickable_figs.csv", newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def load_fig_map():
    cache = {}
    try:
        with open(f"{DATA_DIR}/fig_bricklink_map.csv", newline="") as f:
            for row in csv.DictReader(f):
                cache[row["rebrickable_fig_num"]] = row
    except FileNotFoundError:
        pass
    return cache


def live_lookup(rebrickable_fig_num):
    """Ask Rebrickable directly for this fig's external IDs (incl. BrickLink)."""
    if not REBRICKABLE_API_KEY:
        raise EnvironmentError("REBRICKABLE_API_KEY is not set.")
    url = f"https://rebrickable.com/api/v3/lego/minifigs/{rebrickable_fig_num}/"
    resp = requests.get(url, headers={"Authorization": f"key {REBRICKABLE_API_KEY}"}, timeout=15)
    if resp.status_code != 200:
        print(f"  [warn] Rebrickable lookup failed for {rebrickable_fig_num}: {resp.status_code}")
        return None
    data = resp.json()
    external_ids = data.get("external_ids") or {}
    bl_ids = external_ids.get("BrickLink") or []
    if not bl_ids:
        return None
    return bl_ids[0]  # take the first if multiple are listed


def main():
    new_figs = load_new_figs()
    if not new_figs:
        print("No new Rebrickable figs to map this run.")
        return

    unique_rb_ids = sorted(set(r["rebrickable_fig_num"] for r in new_figs))
    print(f"Resolving {len(unique_rb_ids)} new Rebrickable fig(s) to BrickLink IDs...")

    fig_map = load_fig_map()
    resolved = {}   # rebrickable_fig_num -> bricklink_minifig_id
    unmapped = []

    for rb_id in unique_rb_ids:
        cached = fig_map.get(rb_id)
        if cached and cached["trusted"].strip().lower() == "yes":
            resolved[rb_id] = cached["bricklink_minifig_id"]
            continue

        bl_id = live_lookup(rb_id)
        if bl_id:
            resolved[rb_id] = bl_id
            fig_map[rb_id] = {
                "rebrickable_fig_num": rb_id,
                "bricklink_minifig_id": bl_id,
                "match_score": "100",  # authoritative source, not a fuzzy guess
                "trusted": "yes",
            }
        else:
            unmapped.append(rb_id)

    # Append newly resolved fig-in-set rows to the main table
    with open(f"{DATA_DIR}/minifigs_by_set.csv", "a", newline="") as f:
        w = csv.writer(f)
        for row in new_figs:
            rb_id = row["rebrickable_fig_num"]
            if rb_id in resolved:
                w.writerow([row["set_num"], resolved[rb_id], row["quantity"]])

    # Rewrite the fig map cache with anything newly resolved added in
    with open(f"{DATA_DIR}/fig_bricklink_map.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rebrickable_fig_num", "bricklink_minifig_id", "match_score", "trusted"])
        w.writeheader()
        for row in fig_map.values():
            w.writerow(row)

    if unmapped:
        with open(f"{DATA_DIR}/_unmapped_figs.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["rebrickable_fig_num"])
            for rb_id in unmapped:
                w.writerow([rb_id])
        print(f"  {len(unmapped)} fig(s) could not be resolved -- see data/_unmapped_figs.csv")

    print(f"Done. {len(resolved)} resolved, {len(unmapped)} unmapped.")


if __name__ == "__main__":
    main()
