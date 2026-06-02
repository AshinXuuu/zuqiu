"""
score_from_market.py — 用 Pinnacle 多盘口反推"公允比分概率分布"
================================================================
思路:Pinnacle 主盘口(胜平负/大小球/让球)是最聪明的市场。把它们同时去水位,
      用 Dixon-Coles 双泊松拟合出 (λ主, λ客, rho),展开成完整比分概率表。
      盘口喂得越多,比分分布被钉得越准。

定位:这是"能拿到的最好的比分概率",但它是 Pinnacle 的镜子 —— 打不过 Pinnacle。
真正的用法:把它当"公允比分赔率"的尺子,去量**软盘**(bet365 等)的比分赔率。
            软盘哪个比分赔率 > 公允赔率 ×(1+阈值),那里才可能有 edge。

用法:
  只看公允比分分布:
    python score_from_market.py --h 2.10 --d 3.50 --a 3.40 \
        --over 1.90 --under 1.95 --ahline -0.25 --ahhome 1.95 --ahaway 1.95
  贴入软盘比分赔率找 value(可多个):
    python score_from_market.py --h 2.10 --d 3.50 --a 3.40 --over 1.90 --under 1.95 \
        --soft "1-0:8.5" "2-1:9.0" "1-1:6.5" --edge 0.05

让球/大小球可省略(至少要给 1X2)。让球线 ahline 用主队让球(负=主队让球)。
"""
import argparse
import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

MAXG = 10
grid = np.arange(0, MAXG + 1)


def devig(odds):
    inv = [1.0 / o for o in odds]
    s = sum(inv)
    return [x / s for x in inv]


def dc_tau(i, j, lh, la, rho):
    if i == 0 and j == 0: return 1 - lh * la * rho
    if i == 0 and j == 1: return 1 + lh * rho
    if i == 1 and j == 0: return 1 + la * rho
    if i == 1 and j == 1: return 1 - rho
    return 1.0


def score_matrix(lh, la, rho):
    ph = poisson.pmf(grid, lh)
    pa = poisson.pmf(grid, la)
    M = np.outer(ph, pa)
    for i in (0, 1):
        for j in (0, 1):
            M[i, j] *= dc_tau(i, j, lh, la, rho)
    return M / M.sum()


def margin_dist(M):
    """净胜球(主-客)分布。"""
    d = {}
    for i in grid:
        for j in grid:
            m = int(i - j)
            d[m] = d.get(m, 0.0) + M[i, j]
    return d


def ah_home_prob(M, line):
    """主队让球 line(负=让出)时,backing 主队的'公允覆盖概率'(push 记 0.5),
       支持 .25/.75 四分之一盘(拆成相邻两条线各半)。"""
    md = margin_dist(M)

    def half(h0):  # h0 为整数或 .5
        win = sum(p for m, p in md.items() if m + h0 > 0)
        push = sum(p for m, p in md.items() if abs(m + h0) < 1e-9)
        return win + 0.5 * push

    # 判断是否四分之一盘
    q = round(line * 4)
    if q % 2 != 0:  # 四分之一盘
        return 0.5 * (half(line - 0.25) + half(line + 0.25))
    return half(line)


def fit(targets):
    """targets: list of (kind, value, weight)。kind∈{H,D,A,Over,AH}。"""
    def implied(lh, la, rho):
        M = score_matrix(lh, la, rho)
        H = np.tril(M, -1).sum()
        A = np.triu(M, 1).sum()
        D = np.trace(M)
        tot = np.add.outer(grid, grid)
        Over = M[tot >= 3].sum()
        return M, H, D, A, Over

    def loss(x):
        lh, la, rho = x
        if lh <= 0 or la <= 0:
            return 1e6
        M, H, D, A, Over = implied(lh, la, rho)
        s = 0.0
        for kind, val, w in targets:
            if kind == "H": s += w * (H - val) ** 2
            elif kind == "D": s += w * (D - val) ** 2
            elif kind == "A": s += w * (A - val) ** 2
            elif kind == "Over": s += w * (Over - val) ** 2
            elif kind[0] == "AH":
                p = ah_home_prob(M, kind[1])
                s += w * (p - val) ** 2
        return s

    r = minimize(loss, [1.4, 1.1, -0.05], method="Nelder-Mead",
                 options={"xatol": 1e-6, "fatol": 1e-10, "maxiter": 6000})
    return r.x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--h", type=float, required=True)
    ap.add_argument("--d", type=float, required=True)
    ap.add_argument("--a", type=float, required=True)
    ap.add_argument("--over", type=float, default=None)
    ap.add_argument("--under", type=float, default=None)
    ap.add_argument("--ahline", type=float, default=None, help="主队让球线,如 -0.25")
    ap.add_argument("--ahhome", type=float, default=None)
    ap.add_argument("--ahaway", type=float, default=None)
    ap.add_argument("--soft", nargs="+", default=[],
                    help='软盘比分赔率,格式 "主-客:赔率",如 "2-1:9.0"')
    ap.add_argument("--edge", type=float, default=0.05, help="软盘 value 阈值")
    args = ap.parse_args()

    targets = []
    pH, pD, pA = devig([args.h, args.d, args.a])
    targets += [("H", pH, 1.0), ("D", pD, 1.0), ("A", pA, 1.0)]
    if args.over and args.under:
        pO = devig([args.over, args.under])[0]
        targets.append(("Over", pO, 1.0))
    if args.ahline is not None and args.ahhome and args.ahaway:
        pAHh = devig([args.ahhome, args.ahaway])[0]
        targets.append((("AH", args.ahline), pAHh, 1.0))

    lh, la, rho = fit(targets)
    M = score_matrix(lh, la, rho)

    # 反算各盘口,核对拟合质量
    H = np.tril(M, -1).sum(); A = np.triu(M, 1).sum(); D = np.trace(M)
    tot = np.add.outer(grid, grid); Over = M[tot >= 3].sum()
    print("=" * 60)
    print(f"拟合期望进球: λ主={lh:.2f}  λ客={la:.2f}  rho={rho:.3f}")
    print("市场(去水位) vs 模型复现 —— 越接近说明分布越忠实于 Pinnacle:")
    print(f"  主胜 {pH*100:5.1f}% / {H*100:5.1f}% | 平 {pD*100:5.1f}% / {D*100:5.1f}%"
          f" | 客胜 {pA*100:5.1f}% / {A*100:5.1f}%")
    if args.over and args.under:
        print(f"  大2.5 {devig([args.over,args.under])[0]*100:5.1f}% / {Over*100:5.1f}%")
    if args.ahline is not None and args.ahhome and args.ahaway:
        print(f"  让球({args.ahline}) 主覆盖 "
              f"{devig([args.ahhome,args.ahaway])[0]*100:5.1f}% / {ah_home_prob(M,args.ahline)*100:5.1f}%")

    # 比分概率表
    flat = sorted(((int(i), int(j), M[i, j]) for i in grid for j in grid),
                  key=lambda t: -t[2])
    print("\n最可能比分 TOP 10  (公允概率 / 公允赔率):")
    cum = 0
    for i, j, p in flat[:10]:
        cum += p
        print(f"  {i}-{j}   {p*100:5.2f}%   公允赔率 {1/p:6.2f}   累计 {cum*100:4.1f}%")

    # 软盘 value
    if args.soft:
        print("\n软盘比分找 value(公允概率 × 软盘赔率 − 1):")
        idx = {(i, j): M[i, j] for i in grid for j in grid}
        hits = []
        for s in args.soft:
            try:
                sc, od = s.split(":")
                i, j = map(int, sc.split("-")); od = float(od)
            except ValueError:
                print(f"  跳过格式错误: {s}"); continue
            p = idx.get((i, j), 0.0)
            edge = p * od - 1
            tag = "  ✓有value" if edge > args.edge else ""
            if edge > args.edge: hits.append((sc, edge))
            print(f"  {sc}: 软盘{od}  公允{1/p:.2f}  edge {edge*100:+.1f}%{tag}")
        if hits:
            print("\n→ 软盘报价明显长于公允的比分:",
                  ", ".join(f"{s}({e*100:+.0f}%)" for s, e in hits))
            print("  这才是潜在 edge 所在。但仍须:样本累积、记录 CLV、注意软盘限额。")
        else:
            print("\n没有软盘比分超过阈值,这场没 edge,别下。")

    print("\n提醒:本表是 Pinnacle 的镜子,不能用来'打 Pinnacle';只用于量软盘的错价。")


if __name__ == "__main__":
    main()
