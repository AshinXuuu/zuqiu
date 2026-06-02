"""
backtest_value.py — 价值下注回测引擎(ROI + CLV + 统计检验)
================================================================
回答唯一重要的问题:这套预测到底"赚不赚 / 有没有 edge"。

两种模式(自动选择):

  模式 A  [真·edge 检验]  —— 需要 data/matches_clean.csv 且含足够历史
      walk-forward:每场只用"开赛前"的历史赛果拟合 Dixon-Coles 独立模型,
      模型概率 vs 市场开盘公允概率 -> 标出 value -> flat 注 ->
      用真实赛果算 ROI,并用收盘价算 CLV。模型独立于赔率,这才算真正比市场准。

  模式 B  [CLV 机制演示]  —— 仅有现成 68 场样本(epl_2425_sample.csv)时
      以"收盘公允概率"为真值,检验开盘价是否系统性可被击穿。
      注意:此模式按构造就会得到正 CLV,它只演示机制、跑通流程,
      不能证明独立 edge(那需要模式 A 的模型)。报告里会明确标注。

统计:ROI、注数、命中率、平均 CLV、CLV 的 t 统计、ROI 的 bootstrap 95% 区间。
分盘口拆解(1X2 / 大小球;有数据时含亚盘)。
"""
import os, csv, math, datetime as dt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# ----------------------------------------------------------------------
def devig(odds):
    """多项比例法去水位:返回公允概率(同顺序)。"""
    inv = [1.0 / o for o in odds]
    s = sum(inv)
    return [x / s for x in inv]

def to_ord(datestr):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(datestr, fmt).toordinal()
        except (ValueError, TypeError):
            continue
    return None

def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

# ----------------------------------------------------------------------
def bootstrap_ci(per_bet_pnl, n_boot=5000, seed=42):
    rng = np.random.default_rng(seed)
    arr = np.array(per_bet_pnl, float)
    if len(arr) == 0:
        return (float("nan"), float("nan"))
    means = arr[rng.integers(0, len(arr), size=(n_boot, len(arr)))].mean(axis=1)
    return (np.percentile(means, 2.5), np.percentile(means, 97.5))

def tstat(x):
    a = np.array(x, float)
    if len(a) < 2 or a.std(ddof=1) == 0:
        return float("nan")
    return a.mean() / (a.std(ddof=1) / math.sqrt(len(a)))

class Ledger:
    """记录一组下注,计算 ROI / 命中 / CLV / 统计。"""
    def __init__(self, name):
        self.name = name
        self.pnl = []      # 每注盈亏(flat 1 单位)
        self.clv = []      # 每注 CLV (小数)
        self.hits = 0
    def add(self, won, entry_odds, close_odds):
        self.pnl.append((entry_odds - 1.0) if won else -1.0)
        if close_odds and close_odds > 1:
            self.clv.append(entry_odds / close_odds - 1.0)
        self.hits += int(won)
    def report(self):
        n = len(self.pnl)
        if n == 0:
            return f"  [{self.name}] 0 注"
        roi = np.mean(self.pnl) * 100
        lo, hi = bootstrap_ci(self.pnl)
        avg_clv = np.mean(self.clv) * 100 if self.clv else float("nan")
        t = tstat(self.clv) if self.clv else float("nan")
        hr = self.hits / n * 100
        return (f"  [{self.name}] 注数 {n:4d} | 命中 {hr:5.1f}% | "
                f"ROI {roi:+6.2f}% (95%CI {lo*100:+.1f}~{hi*100:+.1f}%) | "
                f"平均CLV {avg_clv:+5.2f}% (t={t:+.2f})")

# ----------------------------------------------------------------------
def run_mode_B(path, edge_thr=0.02):
    """CLV 机制演示:收盘=真值,找开盘 value。"""
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    overall = Ledger("全部")
    m1x2 = Ledger("1X2 ")
    mou = Ledger("大小球")
    for r in rows:
        fh, fa = int(r["FTHG"]), int(r["FTAG"])
        res = "H" if fh > fa else ("A" if fa > fh else "D")
        over = (fh + fa) >= 3
        # 1X2
        oH, oD, oA = fnum(r["PSH"]), fnum(r["PSD"]), fnum(r["PSA"])
        cH, cD, cA = fnum(r["PSCH"]), fnum(r["PSCD"]), fnum(r["PSCA"])
        if None not in (oH, oD, oA, cH, cD, cA):
            fairC = dict(zip("HDA", devig([cH, cD, cA])))       # 收盘真值
            openO = dict(zip("HDA", [oH, oD, oA]))               # 开盘可投赔率
            closeO = dict(zip("HDA", [cH, cD, cA]))
            for sel in "HDA":
                edge = fairC[sel] * openO[sel] - 1.0
                if edge > edge_thr:
                    won = (sel == res)
                    overall.add(won, openO[sel], closeO[sel])
                    m1x2.add(won, openO[sel], closeO[sel])
        # 大小球 2.5
        oO, oU = fnum(r["PO"]), fnum(r["PU"])
        cO, cU = fnum(r["PCO"]), fnum(r["PCU"])
        if None not in (oO, oU, cO, cU):
            fairC = dict(zip(["O", "U"], devig([cO, cU])))
            openO = {"O": oO, "U": oU}
            closeO = {"O": cO, "U": cU}
            for sel in ("O", "U"):
                edge = fairC[sel] * openO[sel] - 1.0
                if edge > edge_thr:
                    won = (over if sel == "O" else (not over))
                    overall.add(won, openO[sel], closeO[sel])
                    mou.add(won, openO[sel], closeO[sel])
    print("="*78)
    print(f"模式 B · CLV 机制演示(收盘为真值,价值阈值 {edge_thr*100:.0f}%) · 样本 {len(rows)} 场")
    print("="*78)
    for L in (overall, m1x2, mou):
        print(L.report())
    print("\n说明:模式 B 按构造倾向于正 CLV(我们专挑开盘比收盘长的注),")
    print("它只验证'流程跑通 + 跟随线步进能否盈利',不等于独立 edge。")
    print("要证明真 edge,请用 download_data.py 拉历史后跑模式 A。")

# ----------------------------------------------------------------------
def run_mode_A(path, warmup=120, xi=0.0018, edge_thr=0.03, refit_every=20,
               max_hist=760):
    """真·edge 检验:walk-forward 独立模型 vs 市场开盘价。
    refit_every: 每个联赛每隔多少场重新拟合一次(球队强弱变化慢,不必每场重训)。
    max_hist:    每次拟合只用最近 max_hist 场(~2 个赛季)。古早战绩无意义,
                 且能把拟合开销封顶,速度稳定。"""
    import sys, time
    from model_dc import DixonColes
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    # 解析 + 排序
    games = []
    for r in rows:
        o = to_ord(r.get("Date", ""))
        fh, fa = fnum(r["FTHG"]), fnum(r["FTAG"])
        if o is None or fh is None or fa is None:
            continue
        games.append({**r, "_t": o, "hg": int(fh), "ag": int(fa),
                      "home": r["HomeTeam"], "away": r["AwayTeam"],
                      "league": r.get("League", "X")})
    games.sort(key=lambda g: g["_t"])

    overall = Ledger("全部")
    m1x2, mou = Ledger("1X2 "), Ledger("大小球")
    # 按联赛分别累积历史
    hist = {}
    cache = {}          # league -> (model, 上次拟合时的历史长度)
    n_pred = 0
    t0 = time.time()
    total = len(games)
    for gi, g in enumerate(games):
        if gi % 500 == 0:
            print(f"  ...进度 {gi}/{total}  已下注 {len(overall.pnl)} 注  "
                  f"({time.time()-t0:.0f}s)", flush=True)
        lg = g["league"]
        h = hist.setdefault(lg, [])
        if len(h) >= warmup:
            try:
                model, fitted_at = cache.get(lg, (None, -10**9))
                if model is None or (len(h) - fitted_at) >= refit_every:
                    train = h[-max_hist:]
                    model = DixonColes(xi=xi).fit(
                        [{"home": x["home"], "away": x["away"], "hg": x["hg"],
                          "ag": x["ag"], "t": x["_t"]} for x in train],
                        ref_time=g["_t"])
                    cache[lg] = (model, len(h))
                if g["home"] in model.idx and g["away"] in model.idx:
                    p = model.probs(g["home"], g["away"])
                    n_pred += 1
                    fh, fa = g["hg"], g["ag"]
                    res = "H" if fh > fa else ("A" if fa > fh else "D")
                    over = (fh + fa) >= 3
                    # 1X2 value vs 开盘 Pinnacle
                    oH, oD, oA = fnum(g["PSH"]), fnum(g["PSD"]), fnum(g["PSA"])
                    cH, cD, cA = fnum(g["PSCH"]), fnum(g["PSCD"]), fnum(g["PSCA"])
                    if None not in (oH, oD, oA, cH, cD, cA):
                        openO = {"H": oH, "D": oD, "A": oA}
                        closeO = {"H": cH, "D": cD, "A": cA}
                        for sel in "HDA":
                            if p[sel] * openO[sel] - 1 > edge_thr:
                                won = (sel == res)
                                overall.add(won, openO[sel], closeO[sel])
                                m1x2.add(won, openO[sel], closeO[sel])
                    # 大小球
                    oO, oU = fnum(g["PO"]), fnum(g["PU"])
                    cO, cU = fnum(g["PCO"]), fnum(g["PCU"])
                    if None not in (oO, oU, cO, cU):
                        openO = {"O": oO, "U": oU}
                        closeO = {"O": cO, "U": cU}
                        pm = {"O": p["Over25"], "U": p["Under25"]}
                        for sel in ("O", "U"):
                            if pm[sel] * openO[sel] - 1 > edge_thr:
                                won = (over if sel == "O" else (not over))
                                overall.add(won, openO[sel], closeO[sel])
                                mou.add(won, openO[sel], closeO[sel])
            except Exception as e:
                pass
        h.append(g)

    print("="*78)
    print(f"模式 A · 真·edge 检验(walk-forward DC 模型 vs 开盘 Pinnacle)")
    print(f"样本 {len(games)} 场 | 预测 {n_pred} 场 | 衰减xi={xi} | 价值阈值 {edge_thr*100:.0f}%")
    print("="*78)
    for L in (overall, m1x2, mou):
        print(L.report())
    print("\n判读:平均 CLV 持续为正 = 你比收盘市场更早看到价值(真 edge 的最强证据)。")
    print("      ROI 95%CI 跨 0 = 样本还不够,别急着下结论;CLV 比 ROI 更早可信。")

# ----------------------------------------------------------------------
def main():
    clean = os.path.join(DATA, "matches_clean.csv")
    sample = os.path.join(DATA, "epl_2425_sample.csv")
    if os.path.exists(clean) and sum(1 for _ in open(clean, encoding="utf-8")) > 400:
        run_mode_A(clean)
    elif os.path.exists(sample):
        run_mode_B(sample)
    else:
        print("没找到数据。先跑 download_data.py 生成 data/matches_clean.csv,")
        print("或确认 data/epl_2425_sample.csv 存在。")

if __name__ == "__main__":
    main()
