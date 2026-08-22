"""
Builds the price-lookup scope = (your figs, data/my_figs.csv)
                               + (every fig in data/bricklink_minifig_catalog.csv
                                  whose ID prefix matches an active theme in
                                  data/themes.csv' bricklink_prefix column)
then pulls BrickLink price guide data (avg/min/max, used condition) for
every fig in that scope and writes data/prices.csv -- the file Power Query
points at.

The catalog file is BrickLink's own catalog data (periodically re-exported
from bricklink.com and handed over manually -- BrickLink's API has no bulk
catalog-download endpoint, only per-item lookups, so this can't be kept
current automatically). Scoping by catalog rather than by
data/minifigs_by_set.csv (which only contains figs Rebrickable has already
linked to a discovered set) means newly-released figs show up here as soon
as the catalog export is refreshed, without waiting on Rebrickable to catch
up. Any scope fig missing from the catalog (e.g. something added to
my_figs.csv since the last export) still gets a live per-item lookup below.

This is the piece that costs BrickLink API calls, so everything upstream
(theme filtering, fig resolution) exists to keep this scope as small as
the real requirement, not the whole ~19k fig catalog.
"""

import csv
from bricklink_client import BrickLinkClient

DATA_DIR = "data"


def load_my_figs():
    with open(f"{DATA_DIR}/my_figs.csv", newline="") as f:
        return {row["bricklink_minifig_id"] for row in csv.DictReader(f)}


def load_active_prefixes():
    with open(f"{DATA_DIR}/themes.csv", newline="") as f:
        return {
            row["bricklink_prefix"].strip().lower()
            for row in csv.DictReader(f)
            if row["active"].strip().lower() == "yes"
        }


def load_theme_scoped_figs(catalog, active_prefixes):
    figs = set()
    for fig_id in catalog:
        prefix = "".join(ch for ch in fig_id if ch.isalpha())
        if prefix.lower() in active_prefixes:
            figs.add(fig_id)
    return figs


def load_existing_prices():
    try:
        with open(f"{DATA_DIR}/prices.csv", newline="") as f:
            return {row["bricklink_minifig_id"]: row for row in csv.DictReader(f)}
    except FileNotFoundError:
        return {}


def load_existing_catalog():
    try:
        with open(f"{DATA_DIR}/bricklink_minifig_catalog.csv", newline="") as f:
            return {row["ITEMID"]: row for row in csv.DictReader(f)}
    except FileNotFoundError:
        return {}


def main():
    my_figs = load_my_figs()
    active_prefixes = load_active_prefixes()
    catalog = load_existing_catalog()
    theme_figs = load_theme_scoped_figs(catalog, active_prefixes)

    existing = load_existing_prices()
    # Never-priced figs go first. If scope exceeds the daily call cap and
    # the run stops early (see below), this guarantees genuinely new figs
    # still get reached instead of silently starving forever behind
    # whatever happens to sort earlier alphabetically -- already-priced
    # figs just keep last month's value for one more cycle in that case.
    scope = sorted(my_figs | theme_figs, key=lambda fig_id: (fig_id in existing, fig_id))
    new_count = sum(1 for fig_id in scope if fig_id not in existing)
    print(f"Price scope: {len(my_figs)} of your figs + {len(theme_figs)} theme figs "
          f"= {len(scope)} unique figs to price this run ({new_count} never priced before).")

    client = BrickLinkClient()
    results = dict(existing)  # keep last month's values for anything that fails this run

    catalog_lookups_done = 0
    stopped_early = False

    for i, fig_id in enumerate(scope, 1):
        try:
            price_data = client.get_price_guide("MINIFIG", fig_id, new_or_used="U", guide_type="stock")
        except RuntimeError as e:
            print(f"  [stopping] {e} -- {len(scope) - i + 1} figs left unpriced this run, "
                  f"they'll be picked up next run.")
            stopped_early = True
            break

        if price_data:
            results[fig_id] = {
                "bricklink_minifig_id": fig_id,
                "avg_price": price_data["avg_price"],
                "min_price": price_data["min_price"],
                "max_price": price_data["max_price"],
            }

        # Catalog metadata (name/year/category/weight) rarely changes once
        # set, so only look up figs we don't already have cached -- this is
        # the same "only pay for genuinely new items" pattern as the price
        # loop above, just with a cache that persists indefinitely instead
        # of refreshing every run.
        if fig_id not in catalog:
            try:
                item_data = client.get_item("MINIFIG", fig_id)
            except RuntimeError as e:
                print(f"  [stopping] {e}")
                stopped_early = True
                break
            if item_data:
                catalog[fig_id] = {
                    "ITEMID": fig_id,
                    "ITEMNAME": item_data["name"],
                    "CATEGORY": item_data["category_id"],
                    "ITEMYEAR": item_data["year_released"],
                    "ITEMWEIGHT": item_data["weight"],
                }
                catalog_lookups_done += 1

        if i % 100 == 0:
            print(f"  ...{i}/{len(scope)} priced ({client.calls_made} API calls made)")

    with open(f"{DATA_DIR}/prices.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["bricklink_minifig_id", "avg_price", "min_price", "max_price"])
        w.writeheader()
        for fig_id in sorted(results):
            w.writerow(results[fig_id])

    with open(f"{DATA_DIR}/bricklink_minifig_catalog.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ITEMID", "ITEMNAME", "CATEGORY", "ITEMYEAR", "ITEMWEIGHT"])
        w.writeheader()
        for fig_id in sorted(catalog):
            w.writerow(catalog[fig_id])

    status = "Stopped early (daily call cap)" if stopped_early else "Done"
    print(f"{status}. {client.calls_made} BrickLink API calls made "
          f"({catalog_lookups_done} new catalog entries). "
          f"data/prices.csv written with {len(results)} priced figs, "
          f"data/bricklink_minifig_catalog.csv has {len(catalog)} entries.")


if __name__ == "__main__":
    main()
