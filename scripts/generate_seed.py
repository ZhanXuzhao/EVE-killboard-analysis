"""从当前数据库生成种子文件（星系星域缓存、ID名称缓存）。"""
import json
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "killboard.db"


def _repr_safe(obj):
    """安全地序列化对象（处理不可JSON序列化的类型）。"""
    return json.dumps(obj, ensure_ascii=False, default=str)


def generate_system_region_seed():
    """生成 system_region_cache 种子文件。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT system_id, region_name, security_status FROM system_region_cache"
    ).fetchall()
    conn.close()

    seed = {}
    for r in rows:
        seed[str(r["system_id"])] = {
            "region_name": r["region_name"],
            "security_status": r["security_status"],
        }

    out_path = DATA_DIR / "system_region_seed.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=1)
    print(f"✅ system_region_seed.json: {len(seed)} 条记录 → {out_path}")


def generate_id_name_seed():
    """生成 id_name_cache 种子文件（含 category）。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT entity_id, name, category FROM id_name_cache").fetchall()
    conn.close()

    seed = {}
    for r in rows:
        cat = r["category"]
        if cat:
            seed[str(r["entity_id"])] = {"name": r["name"], "category": cat}
        else:
            seed[str(r["entity_id"])] = r["name"]

    out_path = DATA_DIR / "id_name_seed.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=1)
    print(f"✅ id_name_seed.json: {len(seed)} 条记录 → {out_path}")


if __name__ == "__main__":
    generate_system_region_seed()
    generate_id_name_seed()
