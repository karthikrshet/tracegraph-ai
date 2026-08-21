import json
import time
import urllib.request
from pathlib import Path

# Trigger crawl
crawl_req = urllib.request.Request(
    "http://127.0.0.1:8000/api/crawl",
    data=json.dumps({"url": "https://demo.saleor.io/en-US", "max_depth": 3, "max_actions": 10}).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
crawl_res = json.loads(urllib.request.urlopen(crawl_req).read().decode("utf-8"))
crawl_id = crawl_res["crawl_id"]
print(f"Queued Crawl ID: {crawl_id}")

time.sleep(8)

crawls_dir = Path("./data/artifacts/crawls") / crawl_id
shots = sorted(list((crawls_dir / "screenshots").glob("*.png")))
doms = sorted(list((crawls_dir / "dom").glob("*.html")))
jsonls = sorted(list(crawls_dir.glob("*.json*")))

print(f"\nDisk Verification for {crawls_dir}:")
print(f"  - Screenshot PNGs ({len(shots)}): {[s.name for s in shots]}")
print(f"  - DOM HTML Files ({len(doms)}): {[d.name for d in doms]}")
print(f"  - JSON/JSONL Datasets ({len(jsonls)}): {[j.name for j in jsonls]}")

# Test HTTP fetch
if shots:
    shot_url = f"http://127.0.0.1:8000/artifacts/crawls/{crawl_id}/screenshots/{shots[0].name}"
    res_shot = urllib.request.urlopen(shot_url)
    print(f"\nHTTP GET {shot_url} -> Status {res_shot.status}, Type: {res_shot.headers.get('Content-Type')}")

if doms:
    dom_url = f"http://127.0.0.1:8000/artifacts/crawls/{crawl_id}/dom/{doms[0].name}"
    res_dom = urllib.request.urlopen(dom_url)
    print(f"HTTP GET {dom_url} -> Status {res_dom.status}, Type: {res_dom.headers.get('Content-Type')}")
