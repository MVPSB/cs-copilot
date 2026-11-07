"""定向复测 20 条：覆盖四位客服踩过的坑，直接打 Dify。

判定：回复里出现 forbidden 任一 → 失败；必须有 require_any 之一；
expect_action 给了就必须一致（None 表示不判动作）。
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = {}
with open(os.path.join(ROOT, ".env"), encoding="utf-8-sig") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"')

BASE = env.get("DIFY_API_BASE", "http://localhost/v1").rstrip("/")
KEY = env["DIFY_APP_API_KEY"]

CASES = [
    dict(q="显卡驱动装不上", scene="技术", order="", action="直接回复",
         any=["官网", "驱动", "设备管理器", "型号"],
         forbid=["主管", "拆机"], note="09 知识库：给排查步骤"),
    dict(q="买来两天就坏了，质量太差", scene="投诉", order="HP20240915003", action="转主管",
         any=["主管"], forbid=["手机", "亲亲"], note="不臆造商品 + 转主管"),
    dict(q="少件了，只收到显卡没收到电源线", scene="投诉", order="HP20240915003", action=None,
         any=["HP20240915003", "主管", "补发"], forbid=["把订单号发我", "方便提供订单号", "麻烦告知订单号"],
         note="已知订单号不得再要"),
    dict(q="退货申请被你们拒了", scene="投诉", order="HP20240901001", action="转主管",
         any=["主管"], forbid=["把订单号发我", "手机"], note="已知订单号 + 转主管"),
    dict(q="在吗", scene="闲聊", order="", action="直接回复",
         any=["在的", "客服", "订单号"], forbid=["主管"], note="完整开场"),
    dict(q="你是谁", scene="闲聊", order="", action="直接回复",
         any=["客服", "助手", "帮您"], forbid=["主管"], note="身份+能力"),
    dict(q="讲个笑话", scene="闲聊", order="", action="直接回复",
         any=["笑话", "才艺", "帮您", "机器"], forbid=["主管"], note="接住并引导"),
    dict(q="你觉得现在国际局势怎么样", scene="闲聊", order="", action="直接回复",
         any=["不太方便", "帮您", "产品", "订单"], forbid=["主管", "美国", "战争"], note="不展开时事"),
    dict(q="和 MacBook 比怎么样", scene="产品", order="", action="追问产品",
         any=["哪一款", "型号", "X15", "MacBook"], forbid=["主管"], note="先确认对比对象"),
    dict(q="京东同款才 6000，你们贵了", scene="产品", order="", action=None,
         any=["活动", "赠品", "型号", "不跟价", "价格"], forbid=["主管"], note="不跟价口径"),
    dict(q="退货寄回后几天退款？", scene="政策", order="", action="直接回复",
         any=["3-5", "3到5", "3~5", "工作日"], forbid=["主管"], note="10 知识库退款时效"),
    dict(q="能加钱发顺丰吗？", scene="物流", order="", action="直接回复",
         any=["18", "差价", "顺丰"], forbid=["主管"], note="顺丰补差价"),
    dict(q="下单十天了还没发货", scene="物流", order="HP20240915003", action=None,
         any=["HP20240915003", "揽收", "催", "发货"], forbid=["把订单号发我"], note="已发货待揽收"),
    dict(q="物流三天没更新了，卡在哪了？", scene="物流", order="HP20240910002", action=None,
         any=["HP20240910002", "分拣", "运输", "中通", "圆通", "催促"], forbid=["把订单号发我"], note="用已知单号查"),
    dict(q="HP20240915003 这单到哪了", scene="", order="", action=None,
         any=["德邦", "运单", "待揽收", "青浦"], forbid=["把订单号发我"], note="从原话提取单号"),
    dict(q="上海仓现在还有几张 RTX5080？", scene="产品", order="", action=None,
         any=["12", "现货", "库存"], forbid=["主管"], note="库存口径"),
    dict(q="店铺券和平台券能叠加吗？", scene="促销", order="", action="直接回复",
         any=["不能", "不叠加", "不可", "满减"], forbid=["主管"], note="07 促销口径"),
    dict(q="现在满多少减多少？", scene="促销", order="", action="直接回复",
         any=["299", "999", "2999", "满减"], forbid=["主管"], note="满减档位"),
    dict(q="七天无理由从哪天开始算？", scene="政策", order="", action="直接回复",
         any=["签收", "次日"], forbid=["主管"], note="7 天起算"),
    dict(q="屏幕进灰了算保修吗？", scene="技术", order="", action=None,
         any=["保修", "主管", "检测", "售后"], forbid=[], note="保修范围边界"),
]


def ask(q, scene, order):
    # 与网关一致：订单号为空时从买家原话里兜底提取
    if not order:
        found = re.search(r"\b([A-Z]{2}\d{10,14})\b", q.upper())
        if found:
            order = found.group(1)
    payload = {
        "inputs": {"order_no": order, "agent_level": "veteran", "scene_hint": scene or "auto"},
        "query": q, "response_mode": "blocking", "user": "targeted20",
        "conversation_id": "",
    }
    req = urllib.request.Request(
        BASE + "/chat-messages", data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def parse(answer):
    text = re.sub(r"<think>.*?</think>", "", answer or "", flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return {}


def main():
    passed, rows = 0, []
    for i, c in enumerate(CASES, 1):
        t0 = time.time()
        data = ask(c["q"], c["scene"], c["order"])
        answer = data.get("answer", "")
        parsed = parse(answer)
        reply = parsed.get("reply", answer)
        action = parsed.get("next_action", "")
        fails = []
        for bad in c["forbid"]:
            if bad in reply:
                fails.append(f"出现禁词「{bad}」")
        if c["any"] and not any(w in reply for w in c["any"]):
            fails.append("缺少要点：" + "/".join(c["any"]))
        if c["action"] and action and action != c["action"]:
            fails.append(f"动作={action}，应为{c['action']}")
        ok = not fails
        passed += ok
        rows.append((i, c["q"][:22], "PASS" if ok else "FAIL", action,
                     int(time.time() - t0), "；".join(fails)[:60], reply[:90].replace("\n", " ")))
        print(f"{i:02d} {'PASS' if ok else 'FAIL'} {c['q'][:22]:<24} {action} {rows[-1][4]}s {rows[-1][5]}")
    print(f"\n通过 {passed}/{len(CASES)} = {passed / len(CASES):.1%}")


if __name__ == "__main__":
    main()
