"""一次性回填所有 system_region_cache 缺失的安全等级。"""
import requests
import time
from src.storage.database import get_db_read, set_system_region

with get_db_read() as conn:
    rows = conn.execute(
        "SELECT system_id, region_name FROM system_region_cache WHERE security_status IS NULL"
    ).fetchall()

print(f"Found {len(rows)} systems missing security_status")
session = requests.Session()
success = 0
for i, r in enumerate(rows):
    try:
        resp = session.get(
            f"https://esi.evetech.net/latest/universe/systems/{r['system_id']}/",
            timeout=10,
        )
        resp.raise_for_status()
        info = resp.json()
        ss = info.get("security_status")
        if ss is not None:
            ss = round(ss, 2)
            set_system_region(r["system_id"], r["region_name"], security_status=ss)
            success += 1
        if (i + 1) % 100 == 0:
            print(f"  Progress: {i+1}/{len(rows)} ({success} updated)")
            time.sleep(1)
    except Exception as e:
        if (i + 1) % 50 == 0:
            print(f"  Error at {i+1}: {e}")
print(f"Done! Updated {success}/{len(rows)} systems")
