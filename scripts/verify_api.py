import json
import urllib.request

# Requirements test
req_data = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/requirements").read().decode("utf-8"))
reqs = req_data["requirements"]
covered = sum(1 for r in reqs if r["coverage_status"] == "COVERED")
partial = sum(1 for r in reqs if r["coverage_status"] == "PARTIAL")
absent = sum(1 for r in reqs if r["coverage_status"] == "ABSENT")
unverified = sum(1 for r in reqs if r["coverage_status"] == "UNVERIFIED")
print(f"4-State Matrix: COVERED={covered}, PARTIAL={partial}, UNVERIFIED={unverified}, ABSENT={absent}")

# PR #14000 test
cal_data = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/report/14000?repo=calcom%2Fcal.com").read().decode("utf-8"))
print("\nPR #14000 UI Elements:")
for ui in cal_data.get("impacted_ui_elements", []):
    print(f"  - {ui['label']}: {ui['confidence']*100:.1f}% ({ui['confidence']})")
print("PR #14000 Requirements:")
for r in cal_data.get("impacted_requirements", []):
    print(f"  - {r['item_id']}: {r['confidence']*100:.1f}% ({r['confidence']})")

# PR #6857 test
sal_data = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/report/6857?repo=saleor%2Fsaleor-dashboard").read().decode("utf-8"))
print("\nPR #6857 UI Elements:")
for ui in sal_data.get("impacted_ui_elements", []):
    print(f"  - {ui['label']}: {ui['confidence']*100:.1f}% ({ui['confidence']})")
print("PR #6857 Requirements:")
for r in sal_data.get("impacted_requirements", []):
    print(f"  - {r['item_id']}: {r['confidence']*100:.1f}% ({r['confidence']})")
