"""
Minimal BrickLink Store API v2 client.

BrickLink's API uses OAuth 1.0a (three-legged, but for a personal store the
tokens are permanent once generated in BrickLink's API console). Auth needs
four values, all pulled from environment variables / GitHub Secrets:

    BRICKLINK_CONSUMER_KEY
    BRICKLINK_CONSUMER_SECRET
    BRICKLINK_TOKEN_VALUE
    BRICKLINK_TOKEN_SECRET

Get these from: https://www.bricklink.com/v2/api/register_consumer.page
(Register a consumer, then generate a token for your own store.)
"""

import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import random
import string
import requests

BASE_URL = "https://api.bricklink.com/api/store/v1"

# BrickLink's daily cap. We track calls made this run and stop safely
# short of it rather than letting a 403 kill the whole job partway through.
DAILY_CALL_LIMIT = 5000
SAFETY_MARGIN = 100  # leave headroom in case other tools hit the same key today


class BrickLinkClient:
    def __init__(self):
        self.consumer_key = _require_env("BRICKLINK_CONSUMER_KEY")
        self.consumer_secret = _require_env("BRICKLINK_CONSUMER_SECRET")
        self.token_value = _require_env("BRICKLINK_TOKEN_VALUE")
        self.token_secret = _require_env("BRICKLINK_TOKEN_SECRET")
        self.calls_made = 0

    def _oauth_header(self, method, url, params=None):
        params = params or {}
        oauth_params = {
            "oauth_consumer_key": self.consumer_key,
            "oauth_token": self.token_value,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_nonce": "".join(random.choices(string.ascii_letters + string.digits, k=32)),
            "oauth_version": "1.0",
        }

        all_params = {**params, **oauth_params}
        sorted_params = sorted(all_params.items())
        param_string = "&".join(
            f"{urllib.parse.quote(str(k), safe='')}={urllib.parse.quote(str(v), safe='')}"
            for k, v in sorted_params
        )
        base_string = "&".join([
            method.upper(),
            urllib.parse.quote(url, safe=""),
            urllib.parse.quote(param_string, safe=""),
        ])
        signing_key = f"{urllib.parse.quote(self.consumer_secret, safe='')}&{urllib.parse.quote(self.token_secret, safe='')}"
        signature = base64.b64encode(
            hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
        ).decode()
        oauth_params["oauth_signature"] = signature

        header = "OAuth " + ", ".join(
            f'{k}="{urllib.parse.quote(str(v), safe="")}"' for k, v in oauth_params.items()
        )
        return header

    def get_price_guide(self, item_type, item_no, new_or_used="U", guide_type="stock"):
        """
        item_type: 'MINIFIG' for minifigs
        new_or_used: 'N' or 'U'
        guide_type: 'stock' (currently listed) or 'sold' (last 6 months sold)
        Returns dict with avg_price, min_price, max_price, unit_quantity, etc.
        or None if the item has no price guide data / call failed.
        """
        if self.calls_made >= DAILY_CALL_LIMIT - SAFETY_MARGIN:
            raise RuntimeError(
                f"Stopping before hitting BrickLink's daily call cap "
                f"({self.calls_made} calls made this run)."
            )

        url = f"{BASE_URL}/items/{item_type}/{item_no}/price"
        params = {"guide_type": guide_type, "new_or_used": new_or_used}
        header = self._oauth_header("GET", url, params)
        resp = requests.get(url, params=params, headers={"Authorization": header}, timeout=15)
        self.calls_made += 1

        if resp.status_code != 200:
            print(f"  [warn] price lookup failed for {item_no} ({resp.status_code}): {resp.text[:200]}")
            return None

        data = resp.json().get("data")
        if not data:
            return None

        return {
            "avg_price": data.get("avg_price"),
            "min_price": data.get("min_price"),
            "max_price": data.get("max_price"),
            "qty_avg_price": data.get("qty_avg_price"),
            "unit_quantity": data.get("unit_quantity"),
            "total_quantity": data.get("total_quantity"),
        }

    def get_item(self, item_type, item_no):
        """
        Catalog metadata for a single item (name, category, release year,
        weight) -- BrickLink has no bulk "download the whole catalog"
        endpoint, only this per-item lookup, so catalog data has to be
        built up the same way the price guide is: one call per item.
        Returns None if the item has no catalog entry / call failed.
        """
        if self.calls_made >= DAILY_CALL_LIMIT - SAFETY_MARGIN:
            raise RuntimeError(
                f"Stopping before hitting BrickLink's daily call cap "
                f"({self.calls_made} calls made this run)."
            )

        url = f"{BASE_URL}/items/{item_type}/{item_no}"
        header = self._oauth_header("GET", url)
        resp = requests.get(url, headers={"Authorization": header}, timeout=15)
        self.calls_made += 1

        if resp.status_code != 200:
            print(f"  [warn] item lookup failed for {item_no} ({resp.status_code}): {resp.text[:200]}")
            return None

        data = resp.json().get("data")
        if not data:
            return None

        return {
            "name": data.get("name"),
            "category_id": data.get("category_id"),
            "year_released": data.get("year_released"),
            "weight": data.get("weight"),
        }


def _require_env(name):
    val = os.environ.get(name)
    if not val:
        raise EnvironmentError(
            f"Missing required environment variable: {name}. "
            f"Set it as a GitHub Actions secret."
        )
    return val
