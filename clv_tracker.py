"""
clv_tracker.py — 个人逐注 CLV 记分卡
================================================================
唯一能告诉你"我的模型+人工判断到底有没有在加价值"的工具。
你只需在下注时记两个数:进场赔率、(临场)收盘赔率;赛后补一个胜负。

CLV(收盘线价值) = 进场赔率 / 收盘赔率 − 1
  > 0  你买到了比收盘更长的价 = 过程在赢
  持续为正(几百注后 t 显著) = 你真有 edge,可以继续
  ≈0 或为负 = 你只是在复述/落后市场,该停

用法:
  记一注(赛前,先不填结果):
    python clv_tracker.py add --match "Arsenal vs Chelsea" --pick H \
        --entry 2.10 --close 2.00 --stake 1
  赛后补结果(win/lose/push):
    python clv_tracker.py result --id 7 --outcome win
  看记分卡:
    python clv_tracker.py report

数据存在 data/bets.csv,纯文本,随时可用 Excel 打开。
"""
import argparse, os, csv, math
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
BETS = os.path.join(DATA, "bets.csv")
COLS = ["id", "date", "match", "market", "pick", "entry", "close", "stake", "outcome"]


def _load():
    if not os.path.exists(BETS):
        return []
    return list(csv.DictReader(open(BETS, encoding="utf-8")))


def _save(rows):
    os.makedirs(DATA, exist_ok=True)
    with open(BETS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)


def cmd_add(a):
    rows = _load()
    nid = (max((int(r["id"]) for r in rows), default=0) + 1)
    import datetime as dt
    rows.append({"id": nid, "date": dt.date.today().isoformat(),
                 "match": a.match, "market": a.market, "pick": a.pick,
                 "entry": a.entry, "close": a.close, "stake": a.stake,
                 "outcome": ""})
    _save(rows)
    clv = (a.entry / a.close - 1) * 100 if a.close else float("nan")
    print(f"已记录 #{nid}: {a.match} [{a.pick}] 进场{a.entry} 收盘{a.close} "
          f"-> CLV {clv:+.2f}%。赛后用 result --id {nid} --outcome win/lose/push 补结果。")


def cmd_result(a):
    rows = _load()
    for r in rows:
        if int(r["id"]) == a.id:
            r["outcome"] = a.outcome
            _save(rows)
            print(f"#{a.id} 结果已更新为 {a.outcome}。")
            return
    print(f"没找到 #{a.id}。")


def _tstat(x):
    n = len(x)
    if n < 2:
        return float("nan")
    m = sum(x) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd > 0 else float("nan")


def cmd_report(a):
    rows = _load()
    if not rows:
        print("还没有任何下注记录。先用 add 记一注。")
        return
    clvs, pnls, settled = [], [], 0
    for r in rows:
        try:
            entry, close = float(r["entry"]), float(r["close"])
            stake = float(r["stake"] or 1)
        except ValueError:
            continue
        if close > 1:
            clvs.append(entry / close - 1)
        oc = (r["outcome"] or "").lower()
        if oc in ("win", "lose", "push"):
            settled += 1
            if oc == "win":
                pnls.append((entry - 1) * stake)
            elif oc == "lose":
                pnls.append(-stake)
            else:
                pnls.append(0.0)
    n = len(rows)
    print("=" * 60)
    print(f"个人 CLV 记分卡  ·  共 {n} 注(已结算 {settled})")
    print("=" * 60)
    if clvs:
        avg = sum(clvs) / len(clvs) * 100
        t = _tstat(clvs)
        pos = sum(1 for c in clvs if c > 0)
        print(f"平均 CLV   {avg:+.2f}%   (t={t:+.2f}, 正CLV占比 {pos}/{len(clvs)})")
    if pnls:
        roi = sum(pnls) / sum(float(r['stake'] or 1) for r in rows
                              if (r['outcome'] or '').lower() in ('win', 'lose', 'push')) * 100
        print(f"已结算 ROI {roi:+.2f}%   (盈亏合计 {sum(pnls):+.2f} 单位)")
    print("-" * 60)
    # 判读
    if not clvs:
        return
    avg = sum(clvs) / len(clvs)
    t = _tstat(clvs)
    if len(clvs) < 100:
        print(f"样本还小({len(clvs)}注)。几百注以上 CLV 才开始可信,继续记。")
    elif avg > 0 and (t == t and t > 2):
        print("✓ CLV 显著为正 = 你确实在比收盘市场更早看到价值。过程对,继续。")
    elif avg <= 0:
        print("✗ CLV 不为正 = 你在复述或落后市场,没在加价值。认真考虑停手或改方法。")
    else:
        print("CLV 略正但还不显著,继续累积样本再判。")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add"); p.add_argument("--match", required=True)
    p.add_argument("--market", default="1X2"); p.add_argument("--pick", required=True)
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--close", type=float, required=True)
    p.add_argument("--stake", type=float, default=1); p.set_defaults(func=cmd_add)
    p = sub.add_parser("result"); p.add_argument("--id", type=int, required=True)
    p.add_argument("--outcome", required=True, choices=["win", "lose", "push"])
    p.set_defaults(func=cmd_result)
    p = sub.add_parser("report"); p.set_defaults(func=cmd_report)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
