"""查被杀排行中这些角色的 victim_alliance_id 是否真的为 Dracarys."""
import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "data", "killmail.db")
if not os.path.exists(db_path):
    # try alternative path
    db_path = os.path.join(os.path.dirname(__file__), "data", "killboard.db")

print(f"DB path: {db_path}")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

names = [
    "Bunk Helper", "Bunk Boi", "Sprouty 0007",
    "qa69464488", "Huang YuTing005",
    "lingdu9", "jueduilingdu", "MrWPRG", "MrPRW", "Rendering alone"
]

placeholders = ",".join("?" * len(names))
cur.execute(
    f"""SELECT k.victim_character_name, k.victim_corporation_name, 
              k.victim_corporation_id, k.victim_alliance_id, k.victim_alliance_name
       FROM killmails k 
       WHERE k.victim_character_name IN ({placeholders})
       GROUP BY k.victim_character_id""",
    names
)
rows = cur.fetchall()
print(f"\n=== 角色 alliance_id 查询 ===")
for r in rows:
    print(f"  {r['victim_character_name']:25s} | corp={r['victim_corporation_name']:30s}({r['victim_corporation_id']}) | ally_id={r['victim_alliance_id']} | ally_name={r['victim_alliance_name']}")

# Also check what alliance_ids exist for these corps
corp_names = ["Tech Builds", "Chaos arbiter", "Phoenix City", "Unprofitable Ventures Inc."]
placeholders2 = ",".join("?" * len(corp_names))
cur.execute(
    f"""SELECT DISTINCT k.victim_corporation_name, k.victim_alliance_id, k.victim_alliance_name
       FROM killmails k
       WHERE k.victim_corporation_name IN ({placeholders2})
       GROUP BY k.victim_corporation_name, k.victim_alliance_id""",
    corp_names
)
rows2 = cur.fetchall()
print(f"\n=== 这些军团的 alliance_id ===")
for r in rows2:
    print(f"  corp={r['victim_corporation_name']:30s} | ally_id={r['victim_alliance_id']} | ally_name={r['victim_alliance_name']}")

conn.close()
