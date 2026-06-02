"""
赔率 -> 比分概率分布   演示
方法: 1X2 + 大小球2.5 先去水位(de-vig)得到市场公允概率,
      再用 Dixon-Coles 修正的双泊松模型拟合出 home/away 期望进球,
      最后展开成完整比分概率表。
"""
import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

# ---------------------------------------------------------------
# 输入: 一场比赛的市场赔率 (代表性主流盘口, 主队中等热门)
# 例: 某队主场, 让球 -0.5/-1, 总进球中性偏高
match = "示例: 主队(中等热门) vs 客队"
odds = {
    "H": 1.95, "D": 3.60, "A": 4.00,   # 胜 / 平 / 负 (欧赔)
    "Over25": 1.90, "Under25": 1.95,   # 大/小 2.5 球
}

# ---------------------------------------------------------------
# 1) 去水位: 按比例法 (multiplicative de-vig)
def devig(prices):
    raw = {k: 1.0/v for k, v in prices.items()}
    s = sum(raw.values())
    return {k: v/s for k, v in raw.items()}, s

p_1x2, overround_1x2 = devig({"H": odds["H"], "D": odds["D"], "A": odds["A"]})
p_ou,  overround_ou  = devig({"O": odds["Over25"], "U": odds["Under25"]})

# ---------------------------------------------------------------
# 2) Dixon-Coles 双泊松: 用 lambda_h, lambda_a, rho 拟合市场公允概率
MAXG = 12
grid = np.arange(0, MAXG+1)

def dc_tau(i, j, lh, la, rho):
    if i == 0 and j == 0: return 1 - lh*la*rho
    if i == 0 and j == 1: return 1 + lh*rho
    if i == 1 and j == 0: return 1 + la*rho
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

def implied(lh, la, rho):
    M = score_matrix(lh, la, rho)
    H = np.tril(M, -1).sum()          # home goals > away  -> 主胜
    A = np.triu(M, 1).sum()           # away > home        -> 客胜
    D = np.trace(M)                   # 平
    # 总进球 >2.5  => 3+ 球
    tot = np.add.outer(grid, grid)
    Over = M[tot >= 3].sum()
    Under = M[tot <= 2].sum()
    return H, D, A, Over, Under

def loss(x):
    lh, la, rho = x
    if lh <= 0 or la <= 0: return 1e6
    H, D, A, Over, Under = implied(lh, la, rho)
    tgt = [p_1x2["H"], p_1x2["D"], p_1x2["A"], p_ou["O"]]
    got = [H, D, A, Over]
    return sum((a-b)**2 for a, b in zip(tgt, got))

res = minimize(loss, x0=[1.4, 1.1, -0.05],
               method="Nelder-Mead",
               options={"xatol":1e-6, "fatol":1e-10, "maxiter":5000})
lh, la, rho = res.x
M = score_matrix(lh, la, rho)

# ---------------------------------------------------------------
# 3) 输出
H, D, A, Over, Under = implied(lh, la, rho)
print("="*60)
print(match)
print("="*60)
print(f"输入欧赔   主胜 {odds['H']}  平 {odds['D']}  客胜 {odds['A']} | 大2.5 {odds['Over25']}  小2.5 {odds['Under25']}")
print(f"水位(overround): 1X2={overround_1x2:.3f}  大小球={overround_ou:.3f}")
print()
print("去水位后的市场公允概率  vs  模型拟合后:")
print(f"  主胜  市场 {p_1x2['H']*100:5.1f}%   模型 {H*100:5.1f}%")
print(f"  平    市场 {p_1x2['D']*100:5.1f}%   模型 {D*100:5.1f}%")
print(f"  客胜  市场 {p_1x2['A']*100:5.1f}%   模型 {A*100:5.1f}%")
print(f"  大2.5 市场 {p_ou['O']*100:5.1f}%   模型 {Over*100:5.1f}%")
print()
print(f"拟合出的期望进球:  主队 lambda_h = {lh:.2f}   客队 lambda_a = {la:.2f}   (rho={rho:.3f})")
print()

# top scorelines
flat = []
for i in grid:
    for j in grid:
        flat.append(((int(i), int(j)), M[i, j]))
flat.sort(key=lambda t: -t[1])

print("最可能的比分 TOP 12:")
print(f"{'比分':>6} {'概率':>8}   {'累计':>8}")
cum = 0
for (i, j), p in flat[:12]:
    cum += p
    print(f"{i:>2}-{j:<2} {p*100:7.1f}%   {cum*100:7.1f}%")

print()
top_score, top_p = flat[0]
print(f">> 最可能比分是 {top_score[0]}-{top_score[1]}, 但只有 {top_p*100:.1f}% 概率")
print(f">> 即使全押这一个比分, 期望命中率也就 ~{top_p*100:.0f}%")
print(f">> TOP3 比分加起来才 {sum(p for _,p in flat[:3])*100:.1f}%, TOP5 才 {sum(p for _,p in flat[:5])*100:.1f}%")

# correct-score "fair" odds for the favourite scoreline
print(f">> 对照: 这个最可能比分的公允赔率约 {1/top_p:.1f} (赔率越高=越难猜中)")
