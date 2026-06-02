"""
model_dc.py — Dixon-Coles 双泊松 + 时间衰减,基于历史赛果估计球队攻防强度。
这是一个 *独立于赔率* 的模型:它只看过去的进球数,不看市场价格。
因此它产出的概率可以拿去和市场比,才有资格谈"我比市场准"=edge。

核心:
  每队两个参数:attack[i] (进攻), defense[i] (防守);外加全局 home(主场优势)、rho(低分修正)。
  λ_home = exp(home + attack[h] + defense[a])
  λ_away = exp(       attack[a] + defense[h])
  Dixon-Coles 对 0-0,1-0,0-1,1-1 做低分相关性修正(rho)。
  时间衰减:越久远的比赛权重越低 weight = exp(-xi * 天数差)。

只依赖 numpy + scipy。
"""
import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson


def dc_tau(i, j, lh, la, rho):
    if i == 0 and j == 0: return 1 - lh * la * rho
    if i == 0 and j == 1: return 1 + lh * rho
    if i == 1 and j == 0: return 1 + la * rho
    if i == 1 and j == 1: return 1 - rho
    return 1.0


class DixonColes:
    def __init__(self, xi=0.0018):
        # xi: 时间衰减率。0.0018/天 ≈ 半衰期~1年。0=不衰减。
        self.xi = xi
        self.teams = []
        self.idx = {}
        self.params = None

    def _unpack(self, p, n):
        atk = p[:n]
        dfn = p[n:2 * n]
        home = p[2 * n]
        rho = p[2 * n + 1]
        return atk, dfn, home, rho

    def fit(self, matches, ref_time=None):
        """
        matches: list of dict,字段 home, away, hg(主进球), ag(客进球), t(序号或天数,用于衰减)
        ref_time: 衰减参考时点(通常=要预测那场的时间)。None=用最大 t。
        """
        teams = sorted({m["home"] for m in matches} | {m["away"] for m in matches})
        self.teams = teams
        self.idx = {t: k for k, t in enumerate(teams)}
        n = len(teams)
        if ref_time is None:
            ref_time = max(m["t"] for m in matches)

        H = np.array([self.idx[m["home"]] for m in matches])
        A = np.array([self.idx[m["away"]] for m in matches])
        HG = np.array([m["hg"] for m in matches], float)
        AG = np.array([m["ag"] for m in matches], float)
        W = np.exp(-self.xi * (ref_time - np.array([m["t"] for m in matches], float)))

        # 预算低分修正用的掩码(向量化,避免每次迭代 python 循环 -> 快数倍)
        m00 = (HG == 0) & (AG == 0)
        m01 = (HG == 0) & (AG == 1)
        m10 = (HG == 1) & (AG == 0)
        m11 = (HG == 1) & (AG == 1)

        def negll(p):
            atk, dfn, home, rho = self._unpack(p, n)
            # sum-to-zero 约束防止不可辨识
            atk = atk - atk.mean()
            lh = np.exp(home + atk[H] + dfn[A])
            la = np.exp(atk[A] + dfn[H])
            ll = (HG * np.log(lh) - lh) + (AG * np.log(la) - la)
            # 低分修正项(向量化)
            tau = np.ones_like(lh)
            tau[m00] = 1 - lh[m00] * la[m00] * rho
            tau[m01] = 1 + lh[m01] * rho
            tau[m10] = 1 + la[m10] * rho
            tau[m11] = 1 - rho
            tau = np.clip(tau, 1e-9, None)
            ll = ll + np.log(tau)
            return -np.sum(W * ll)

        x0 = np.concatenate([np.zeros(n), np.zeros(n), [0.25], [-0.05]])
        bnds = [(-3, 3)] * (2 * n) + [(-1, 1), (-0.2, 0.2)]
        res = minimize(negll, x0, method="L-BFGS-B", bounds=bnds,
                       options={"maxiter": 400})
        atk, dfn, home, rho = self._unpack(res.x, n)
        atk = atk - atk.mean()
        self.params = (atk, dfn, home, rho)
        return self

    def lambdas(self, home_team, away_team):
        atk, dfn, home, rho = self.params
        h, a = self.idx[home_team], self.idx[away_team]
        lh = np.exp(home + atk[h] + dfn[a])
        la = np.exp(atk[a] + dfn[h])
        return lh, la, rho

    def score_matrix(self, home_team, away_team, maxg=10):
        lh, la, rho = self.lambdas(home_team, away_team)
        grid = np.arange(0, maxg + 1)
        ph = poisson.pmf(grid, lh)
        pa = poisson.pmf(grid, la)
        M = np.outer(ph, pa)
        for i in (0, 1):
            for j in (0, 1):
                M[i, j] *= dc_tau(i, j, lh, la, rho)
        return M / M.sum()

    def probs(self, home_team, away_team, maxg=10):
        """返回 1X2 + 大小球2.5 概率。"""
        M = self.score_matrix(home_team, away_team, maxg)
        grid = np.arange(0, maxg + 1)
        pH = np.tril(M, -1).sum()
        pA = np.triu(M, 1).sum()
        pD = np.trace(M)
        tot = np.add.outer(grid, grid)
        pOver = M[tot >= 3].sum()
        return {"H": pH, "D": pD, "A": pA, "Over25": pOver, "Under25": 1 - pOver}
