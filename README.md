# LEGO Data Pipeline

Monthly, self-updating data for BrickStud: new sets/figs pulled from
Rebrickable, current BrickLink pricing for your figs + a few themes you
track. Runs on GitHub Actions (free tier), no laptop needs to stay on.

## What it produces

| File | What it is | Refreshed |
|---|---|---|
| `data/prices.csv` | avg/min/max BrickLink price per fig in scope | every run |
| `data/minifigs_by_set.csv` | set_num → BrickLink minifig_id → quantity | grows as new sets appear |
| `data/bricklink_minifig_catalog.csv` | BrickLink ID → name/category/year/weight | grows as new figs enter scope |
| `data/sets_seen.csv` | every set_num processed so far (state file) | grows |
| `data/fig_bricklink_map.csv` | Rebrickable fig_num → BrickLink ID cache | grows |

Point Power Query at the **raw GitHub URL** for whichever file you want,
e.g.:

```
https://raw.githubusercontent.com/<you>/<repo>/main/data/prices.csv
```

Refreshing that query in Excel pulls whatever the last workflow run
committed -- no manual download needed.

## One-time setup

### 1. Create the repo
Push this folder to a new GitHub repo (private is fine -- Actions works
the same either way).

### 2. Get a Rebrickable API key
Free, from your Rebrickable account settings. Add it as a repo secret:
`Settings > Secrets and variables > Actions > New repository secret`
- `REBRICKABLE_API_KEY`

### 3. Get BrickLink API credentials
Register a consumer at
https://www.bricklink.com/v2/api/register_consumer.page, then generate a
token for your own store (this gives you 4 values). Add each as a secret:
- `BRICKLINK_CONSUMER_KEY`
- `BRICKLINK_CONSUMER_SECRET`
- `BRICKLINK_TOKEN_VALUE`
- `BRICKLINK_TOKEN_SECRET`

### 4. Confirm the workflow has push permission
`Settings > Actions > General > Workflow permissions` → set to
**"Read and write permissions"**. Without this, the last step (committing
data back) will fail silently.

## Editing scope over time

- **Add/remove figs you own**: edit `data/my_figs.csv` directly (one
  BrickLink minifig ID per row), commit.
- **Add/remove a theme to track**: edit `data/themes.csv`. `active=yes/no`
  toggles it without deleting the row. `rebrickable_theme_name` must match
  Rebrickable's theme name (check https://rebrickable.com/themes/ if
  unsure); `bricklink_prefix` is only used to identify figs from that theme
  in the BrickLink-ID-keyed tables (e.g. `sw` for Star Wars, `njo` for
  Ninjago).

## Known limitations / things to sanity-check after the first run

- **`fig_bricklink_map.csv` starting cache is fuzzy-matched**, seeded from
  a third-party crosswalk (median confidence ~85). Rows marked
  `trusted=no` are NOT used automatically -- new figs in that state get a
  live, authoritative lookup instead. Worth spot-checking a handful of
  `trusted=yes` rows against BrickLink directly the first time, since a
  bad cached match would silently misprice a fig.
- **Rebrickable's per-fig `external_ids` lookup isn't guaranteed to have a
  BrickLink reference for every fig** -- some genuinely don't have one on
  Rebrickable's side yet. These land in `data/_unmapped_figs.csv` for you
  to check manually rather than being dropped invisibly.
- **BrickLink's 5,000 calls/day cap**: current scope (your figs + a handful
  of themes) should be comfortably under this in one run. If you add many
  more themes later, watch the "calls made" log line -- the script stops
  itself safely short of the cap rather than getting a 403 mid-run, but
  that means a large scope could take more than one monthly run to fully
  refresh.
- **Rebrickable's exact CSV download URLs aren't fixed** -- the fetch
  script scrapes the current link off their downloads page each run. If
  Rebrickable changes that page's layout, this step will fail with a clear
  error rather than silently pulling stale data.
