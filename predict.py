"""
predict.py — 诚实的"参考预测"工具(向市场收缩)
================================================================
定位:这个模型打不过 Pinnacle,所以它不是选号器,而是"二次意见 + 分歧探测器"。
做法:用历史赛果拟合 Dixon-Coles 独立模型 -> 得到模型概率;
      把它和"市场去水位后的公允概率"按 α 混合(shrink to market):
          最终概率 = α·模型 + (1-α)·市场
      α 越小越信市场。回测证明模型有负 CLV,所以默认 α=0.3(以市场为主、模型微调)。
输出:模型 / 市场 / 混合 三栏对照 + 分歧标记。分歧大 = 值得你人工再看一眼的场次。

用法举例:
    python predict.py --home "Arsenal" --away "Chelsea" --league E0 \
        --h 2.10 --d 3.50 --a 3.40 --over 1.90 --under 1.95 [--alpha 0.3]

依赖 data/matches_clean.csv(由 download_data.py 生成)。
"""
import argparse, os, csv, datetime as dt
import numpy as np
from model_dc import DixonColes

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def devig(odds):
    inv = [1.0 / o for o in odds]
    s = sum(inv)
    return [x / s for x in inv]


def to_ord(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).toordinal()
        except (ValueError, TypeError):
            continue
    return None


def load_history(league, max_hist=760):
    path = os.path.join(DATA, "matches_clean.csv")
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    games = []
    for r in rows:
        if league and r.get("League") != league:
            continue
        o = to_ord(r.get("Date", ""))
        try:
            hg, ag = int(r["FTHG"]), int(r["FTAG"])
        except (ValueError, KeyError):
            continue
        if o is None:
            continue
        games.append({"home": r["HomeTeam"], "away": r["AwayTeam"],
                      "hg": hg, "ag": ag, "t": o})
    games.sort(key=lambda g: g["t"])
    return games[-max_hist:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", required=True)
    ap.add_argument("--away", required=True)
    ap.add_argument("--league", default="E0")
    ap.add_argument("--h", type=float, required=True, help="主胜欧赔")
    ap.add_argument("--d", type=float, required=True, help="平欧赔")
    ap.add_argument("--a", type=float, required=True, help="客胜欧赔")
    ap.add_argument("--over", type=float, default=None, help="大2.5欧赔")
    ap.add_argument("--under", type=float, default=None, help="小2.5欧赔")
    ap.add_argument("--alpha", type=float, default=0.3,
                    help="模型权重(0=纯市场,1=纯模型)。默认0.3,以市场为主。")
    args = ap.parse_args()

    hist = load_history(args.league)
    if len(hist) < 80:
        print(f"历史样本太少({len(hist)}),先用 download_data.py 拉 {args.league} 的数据。")
        return
    ref = max(g["t"] for g in hist) + 3
    model = DixonColes(xi=0.0018).fit(hist, ref_time=ref)

    for t in (args.home, args.away):
        if t not in model.idx:
            print(f"⚠ '{t}' 不在 {args.league} 历史里(队名要和数据完全一致,如 'Man United')。")
            print("  可用队名示例:", ", ".join(list(model.idx)[:8]), "...")
            return

    mp = model.probs(args.home, args.away)            # 模型概率
    mk = dict(zip("HDA", devig([args.h, args.d, args.a])))  # 市场去水位
    a = args.alpha

    def blend(m, k):
        return a * m + (1 - a) * k

    print("=" * 64)
    print(f"{args.home} vs {args.away}  ({args.league})   α={a} (模型权重)")
    print("=" * 64)
    print(f"{'盘口':<8}{'模型':>9}{'市场':>9}{'混合':>9}{'分歧':>9}")
    rows = [("主胜 H", mp["H"], mk["H"]),
            ("平  D", mp["D"], mk["D"]),
            ("客胜 A", mp["A"], mk["A"])]
    if args.over and args.under:
        mko = devig([args.over, args.under])[0]
        rows.append(("大2.5", mp["Over25"], mko))
        rows.append(("小2.5", mp["Under25"], 1 - mko))
    flags = []
    for name, m, k in rows:
        b = blend(m, k)
        diff = (m - k) * 100
        mark = "  ←分歧大" if abs(diff) >= 6 else ""
        if abs(diff) >= 6:
            flags.append(name)
        print(f"{name:<8}{m*100:>8.1f}%{k*100:>8.1f}%{b*100:>8.1f}%{diff:>+8.1f}%{mark}")
    print("-" * 64)
    print("混合列 = 建议参考概率(以市场为主、模型微调)。")
    if flags:
        print(f"⚑ 模型与市场分歧≥6%的盘口: {', '.join(flags)}")
        print("  → 这几项通常是模型错;但若你手上有市场没有的信息(首发/伤停/动机),值得人工再判一次。")
    else:
        print("模型与市场基本一致,没什么可挖的,跟随市场即可。")
    print("\n提醒:本工具是参考/二次意见,不是 edge。回测显示该模型对 Pinnacle 为负 CLV。")


if __name__ == "__main__":
    main()
