"""
Builds the price-lookup scope = (your figs, data/my_figs.csv)
                               + (every fig belonging to an active theme,
                                  derived from data/minifigs_by_set.csv +
                                  data/themes.csv' bricklink_prefix column)
then pulls BrickLink price guide data (avg/min/max, used condition) for
every fig in that scope and writes data/prices.csv -- the file Power Query
points at.

This is the piece that costs BrickLink API calls, so everything upstream
(theme filtering, fig resolution) exists to keep this scope as small as
the real requirement, not the whole ~17-18k fig catalog.
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


def load_theme_scoped_figs(active_prefixes):
    figs = set()
    with open(f"{DATA_DIR}/minifigs_by_set.csv", newline="") as f:
        for row in csv.DictReader(f):
            fig_id = row["bricklink_minifig_id"]
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


def main():
    my_figs = load_my_figs()
    active_prefixes = load_active_prefixes()
    theme_figs = load_theme_scoped_figs(active_prefixes)

    scope = sorted(my_figs | theme_figs)
    print(f"Price scope: {len(my_figs)} of your figs + {len(theme_figs)} theme figs "
          f"= {len(scope)} unique figs to price this run.")

    client = BrickLinkClient()
    existing = load_existing_prices()
    results = dict(existing)  # keep last month's values for anything that fails this run

    for i, fig_id in enumerate(scope, 1):
        price_data = client.get_price_guide("MINIFIG", fig_id, new_or_used="U", guide_type="stock")
        if price_data:
            results[fig_id] = {
                "bricklink_minifig_id": fig_id,
                "avg_price": price_data["avg_price"],
                "min_price": price_data["min_price"],
                "max_price": price_data["max_price"],
            }
        if i % 100 == 0:
            print(f"  ...{i}/{len(scope)} priced ({client.calls_made} API calls made)")

    with open(f"{DATA_DIR}/prices.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["bricklink_minifig_id", "avg_price", "min_price", "max_price"])
        w.writeheader()
        for fig_id in sorted(results):
            w.writerow(results[fig_id])

    print(f"Done. {client.calls_made} BrickLink API calls made. "
          f"data/prices.csv written with {len(results)} priced figs.")


if __name__ == "__main__":
    main()
