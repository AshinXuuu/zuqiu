"""
scan_value.py — 批量软盘错价扫描器
================================================================
逻辑:以 Pinnacle(最聪明的市场)去水位后的概率为"公允基准",
      把每一家软盘(bet365 等)的每个盘口拿来比,
      凡是 软盘赔率 × 公允概率 − 1 > 阈值 的,就是正期望(value)机会,排序列出。

覆盖盘口:胜平负(h2h)、大小球(totals)、让球/亚盘(spreads)——
        都是低水位、软盘最容易报错的盘口(不含精确比分,The Odds API 不提供)。

省额度:The Odds API 每次拉取耗额度。建议:
   1) 先拉一次并存盘:  python scan_value.py --key 你的KEY --save odds.json
   2) 之后反复扫存盘:  python scan_value.py --json odds.json --edge 0.04
   (扫存盘不耗额度;赔率会变,实际下注前再拉新的)

用法示例:
   python scan_value.py --key 你的KEY                 # 直接拉世界杯并扫
   python scan_value.py --key 你的KEY --regions eu,uk,us --save odds.json
   python scan_value.py --json odds.json --edge 0.05  # 扫存盘,阈值5%
依赖:仅标准库(urllib)。
"""
import argparse, json, sys, urllib.request, urllib.parse, ssl

SHARP = "pinnacle"   # 公允基准取这家

def ssl_ctx():
    import ssl
    try:
        import certifi; return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        c = ssl.create_default_context(); c.check_hostname=False; c.verify_mode=ssl.CERT_NONE; return c

def fetch(key, sport, regions, markets):
    base = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    q = urllib.parse.urlencode({"apiKey":key,"regions":regions,"markets":markets,
                                "oddsFormat":"decimal"})
    req = urllib.request.Request(base+"?"+q, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30, context=ssl_ctx()) as r:
        rem = r.headers.get("x-requests-remaining")
        data = json.loads(r.read().decode("utf-8"))
    return data, rem

def devig(prices):
    """多项比例法去水位 -> 公允概率(同顺序)。"""
    inv=[1.0/p for p in prices]; s=sum(inv); return [x/s for x in inv]

def fair_from_pinnacle(ev):
    """返回 dict: (market_key, point, outcome_name) -> 公允概率。point 用 round 到2位或 None。"""
    bk = next((b for b in ev.get("bookmakers",[]) if b.get("key")==SHARP), None)
    if not bk: return None
    fair={}
    for m in bk.get("markets",[]):
        mk=m.get("key"); outs=m.get("outcomes",[])
        if mk=="h2h":
            names=[o["name"] for o in outs]; prices=[o["price"] for o in outs]
            if len(prices)>=2 and all(p>1 for p in prices):
                for nm,fp in zip(names, devig(prices)):
                    fair[(mk,None,nm)]=fp
        elif mk in ("totals","spreads"):
            # 配对去水位:大小球同一 point(如 2.5);让球两边 point 正负相反(主-1/客+1),按绝对值配对
            bypt={}
            for o in outs:
                pt=round(float(o.get("point",0)),2)
                gkey = pt if mk=="totals" else abs(pt)
                bypt.setdefault(gkey,[]).append(o)
            for _,pair in bypt.items():
                if len(pair)==2 and all(o["price"]>1 for o in pair):
                    fps=devig([pair[0]["price"],pair[1]["price"]])
                    for o,fp in zip(pair,fps):
                        fair[(mk,round(float(o.get("point",0)),2),o["name"])]=fp
    return fair

def scan(data, edge_thr=0.03, cap=0.25):
    rows=[]
    for ev in data:
        fair=fair_from_pinnacle(ev)
        if not fair: continue
        home=ev.get("home_team","?"); away=ev.get("away_team","?")
        for bk in ev.get("bookmakers",[]):
            if bk.get("key")==SHARP: continue          # 软盘才比
            for m in bk.get("markets",[]):
                mk=m.get("key")
                for o in m.get("outcomes",[]):
                    pt = None if mk=="h2h" else round(float(o.get("point",0)),2)
                    fp = fair.get((mk,pt,o["name"]))
                    if fp is None: continue
                    price=o.get("price",0)
                    if price<=1: continue
                    edge=fp*price-1
                    if edge>edge_thr:
                        rows.append({
                            "match":f"{home} vs {away}","book":bk.get("title",bk.get("key")),
                            "market":mk,"sel":sel_label(mk,o,pt),
                            "price":price,"fair":1/fp,"edge":edge,
                            "suspect": edge>cap})
    rows.sort(key=lambda r:-r["edge"])
    return rows

def sel_label(mk,o,pt):
    if mk=="h2h": return o["name"]
    if mk=="totals": return f"{o['name']} {pt}"          # Over/Under 2.5
    if mk=="spreads":
        s=f"+{pt}" if pt>0 else str(pt)
        return f"{o['name']} {s}"                          # 让球
    return o["name"]

MK_ZH={"h2h":"胜平负","totals":"大小球","spreads":"让球"}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--key", help="The Odds API key(直接拉取时用)")
    ap.add_argument("--json", help="读取已存盘的赔率 JSON(省额度)")
    ap.add_argument("--save", help="拉取后把原始赔率存到此文件")
    ap.add_argument("--sport", default="soccer_fifa_world_cup")
    ap.add_argument("--regions", default="eu,uk")
    ap.add_argument("--markets", default="h2h,totals,spreads")
    ap.add_argument("--edge", type=float, default=0.03, help="价值阈值,默认3%")
    args=ap.parse_args()

    if args.json:
        data=json.load(open(args.json,encoding="utf-8")); rem=None
    elif args.key:
        try:
            data,rem=fetch(args.key,args.sport,args.regions,args.markets)
        except Exception as e:
            print("拉取失败:",e); sys.exit(1)
        if args.save:
            json.dump(data,open(args.save,"w",encoding="utf-8"),ensure_ascii=False)
            print(f"已存盘 -> {args.save}")
    else:
        print("请用 --key 你的KEY 拉取,或 --json 文件 扫描存盘。"); sys.exit(1)

    rows=scan(data, edge_thr=args.edge)
    print("="*72)
    print(f"价值扫描:{len(data)} 场比赛 · 基准=Pinnacle · 阈值 {args.edge*100:.0f}%"
          + (f" · 剩余额度 {rem}" if rem else ""))
    print("="*72)
    if not rows:
        print("没有超过阈值的机会。多数情况如此 —— 没机会就别下,这是对的。")
        return
    print(f"{'edge':>6}  {'盘口':<6} {'选项':<16} {'软盘':<14} {'赔率':>6} {'公允':>6}  比赛")
    for r in rows:
        flag=" ⚠可疑(可能旧价/漏盘)" if r["suspect"] else ""
        print(f"{r['edge']*100:>+5.1f}%  {MK_ZH.get(r['market'],r['market']):<6} "
              f"{r['sel']:<16} {r['book']:<14} {r['price']:>6.2f} {r['fair']:>6.2f}  {r['match']}{flag}")
    print()
    print("提醒:下注前手动看一眼该场赛前队伍新闻,排除'软盘旧价没跟上伤停'造成的假机会;")
    print("      正EV≠这注会赢,需多注 + 记 CLV 验证;优先低水位的 让球/大小球。")

if __name__=="__main__":
    main()
