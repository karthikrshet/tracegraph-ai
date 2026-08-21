import json
import urllib.request

res = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/crawl/crawl_20260821_185058").read().decode("utf-8"))
print(f"Crawl ID: {res['id']}")
print(f"Start URL: {res['start_url']}")
print(f"Status: {res['status']}")
print(f"Discovered Pages ({len(res.get('pages', []))}):")
for p in res.get("pages", []):
    print(f"  - [{p['id']}] Title: {p['title']} | URL: {p['url']}")
print(f"Discovered Transitions ({len(res.get('transitions', []))}):")
for t in res.get("transitions", []):
    print(f"  - [{t['id']}] {t['from_page_id']} --({t['action_label']})--> {t['to_page_id']}")
