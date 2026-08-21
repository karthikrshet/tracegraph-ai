import json
import time
import urllib.request
from pathlib import Path

# Trigger crawl on custom user domain
crawl_req = urllib.request.Request(
    "http://127.0.0.1:8000/api/crawl",
    data=json.dumps({"url": "https://karthikrajeshshet.vercel.app/", "max_depth": 3, "max_actions": 10, "same_domain_only": True}).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
crawl_res = json.loads(urllib.request.urlopen(crawl_req).read().decode("utf-8"))
crawl_id = crawl_res["crawl_id"]
print(f"Queued Crawl ID: {crawl_id}")

time.sleep(12)

crawls_dir = Path("./data/artifacts/crawls") / crawl_id
stat_res = json.loads(urllib.request.urlopen(f"http://127.0.0.1:8000/api/crawl/{crawl_id}").read().decode("utf-8"))
print(f"Crawl Status: {stat_res['status']}")
print(f"Pages Discovered: {stat_res['pages_discovered']}")
for p in stat_res.get("pages", []):
    print(f"  - [{p['id']}] Title: {p['title']} | URL: {p['url']}")

shots = sorted(list((crawls_dir / "screenshots").glob("*.png")))
doms = sorted(list((crawls_dir / "dom").glob("*.html")))
print(f"Screenshots on Disk ({len(shots)}): {[s.name for s in shots]}")
print(f"DOM Snapshots on Disk ({len(doms)}): {[d.name for d in doms]}")
