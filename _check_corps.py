"""临时脚本：查 Dracarys. 联盟的成员军团列表"""
import requests

# 1. 获取 Dracarys. 联盟的成员军团 ID 列表
r = requests.get(
    "https://esi.evetech.net/latest/alliances/99009163/corporations/",
    headers={"User-Agent": "EVE-Killboard/1.0"},
)
corp_ids = r.json()
print(f"Dracarys. 联盟成员军团数: {len(corp_ids)}")

# 2. 分批查询军团名称
all_corp_names = {}
for i in range(0, len(corp_ids), 1000):
    batch = corp_ids[i:i+1000]
    r = requests.post(
        "https://esi.evetech.net/latest/universe/names/",
        json=batch,
        headers={"User-Agent": "EVE-Killboard/1.0"},
    )
    for item in r.json():
        if item.get("category") == "corporation":
            all_corp_names[item["id"]] = item["name"]

# 3. 打印所有成员军团
print("\n=== Dracarys. 成员军团列表 ===")
for cid in corp_ids:
    name = all_corp_names.get(cid, "???")
    print(f"  {cid}: {name}")

# 4. 查找特定军团
targets = ["Tech Builds", "Chaos arbiter", "Phoenix City", "Unprofitable Ventures Inc."]
print("\n=== 目标军团查找 ===")
for name in targets:
    found = False
    for cid, cname in all_corp_names.items():
        if name.lower() in cname.lower():
            print(f"  找到: {cid}: {cname}")
            found = True
    if not found:
        print(f"  未找到: {name}")
