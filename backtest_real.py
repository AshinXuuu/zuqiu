"""
真实数据回测:英超 2024-25 赛季前 68 场(数据 football-data.co.uk)
检验"用收盘赔率解码出的概率"在真实赛果上到底准不准。
每场字段: 主, 客, 主进, 客进,
          开盘Pinnacle[H,D,A], 开盘大/小2.5,
          收盘Pinnacle[H,D,A], 收盘大/小2.5
"""
import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

# home, away, fthg, ftag, psh,psd,psa, pO,pU, psch,pscd,psca, pcO,pcU
M = [
("Man United","Fulham",1,0, 1.63,4.38,5.3, 1.56,2.56, 1.65,4.23,5.28, 1.63,2.38),
("Ipswich","Liverpool",0,2, 8.18,5.84,1.34, 1.41,3.0, 8.14,6.09,1.34, 1.37,3.3),
("Arsenal","Wolves",2,0, 1.16,8.56,16.22, 1.46,2.79, 1.15,9.05,18.76, 1.41,2.98),
("Everton","Brighton",0,3, 2.73,3.36,2.71, 1.83,2.05, 3.15,3.41,2.4, 1.93,1.97),
("Newcastle","Southampton",1,0, 1.35,5.7,8.25, 1.4,3.09, 1.42,5.3,7.26, 1.46,2.85),
("Nott'm Forest","Bournemouth",1,1, 2.47,3.42,2.97, 1.79,2.11, 2.24,3.5,3.37, 1.89,2.02),
("West Ham","Aston Villa",1,2, 2.49,3.65,2.8, 1.59,2.46, 2.54,3.51,2.86, 1.72,2.21),
("Brentford","Crystal Palace",2,1, 2.5,3.4,2.95, 1.83,2.05, 2.92,3.24,2.66, 2.09,1.83),
("Chelsea","Man City",0,2, 4.19,3.93,1.84, 1.52,2.62, 3.86,3.91,1.97, 1.58,2.51),
("Leicester","Tottenham",1,1, 5.09,4.39,1.63, 1.53,2.61, 4.64,4.33,1.71, 1.54,2.61),
("Brighton","Man United",2,1, 2.51,3.66,2.76, 1.6,2.45, 2.42,3.76,2.86, 1.54,2.6),
("Crystal Palace","West Ham",0,2, 2.17,3.68,3.33, 1.76,2.15, 1.97,3.84,3.84, 1.67,2.32),
("Fulham","Leicester",2,1, 1.84,3.67,4.56, 1.9,1.99, 1.88,3.81,4.26, 1.87,2.04),
("Man City","Ipswich",4,1, 1.08,13.21,25.71, 1.29,3.54, 1.1,11,31, 1.29,3.36),
("Southampton","Nott'm Forest",0,1, 2.59,3.28,2.92, 2.01,1.88, 2.33,3.54,3.11, 1.85,2.07),
("Tottenham","Everton",4,0, 1.45,4.87,7.03, 1.54,2.59, 1.37,5.66,8.0, 1.43,2.95),
("Aston Villa","Arsenal",0,2, 4.55,3.98,1.77, 1.75,2.15, 4.85,4.04,1.74, 1.76,2.15),
("Bournemouth","Newcastle",1,1, 3.05,3.73,2.28, 1.61,2.43, 2.63,3.66,2.68, 1.58,2.49),
("Wolves","Chelsea",2,6, 4.46,4.03,1.78, 1.65,2.33, 3.91,3.94,1.93, 1.62,2.41),
("Liverpool","Brentford",2,0, 1.25,7.05,10.11, 1.36,3.23, 1.22,7.75,12.5, 1.33,3.46),
("Arsenal","Brighton",1,1, 1.34,5.87,8.1, 1.54,2.59, 1.37,5.48,8.43, 1.56,2.56),
("Brentford","Southampton",3,1, 1.79,3.9,4.51, 1.74,2.18, 1.82,3.91,4.46, 1.82,2.07),
("Everton","Bournemouth",2,3, 2.82,3.38,2.62, 1.93,1.96, 3.14,3.45,2.39, 1.88,2.03),
("Ipswich","Fulham",1,1, 3.14,3.53,2.32, 1.83,2.06, 3.07,3.43,2.43, 1.93,1.97),
("Leicester","Aston Villa",1,2, 4.8,4.09,1.71, 1.68,2.27, 4.01,3.87,1.92, 1.8,2.1),
("Nott'm Forest","Wolves",1,1, 2.02,3.7,3.71, 1.85,2.04, 2.0,3.7,3.88, 1.9,2.01),
("West Ham","Man City",1,3, 7.69,5.64,1.37, 1.49,2.72, 7.7,5.25,1.41, 1.56,2.57),
("Chelsea","Crystal Palace",1,1, 1.63,4.4,5.06, 1.53,2.61, 1.68,4.24,5.05, 1.56,2.55),
("Newcastle","Tottenham",2,1, 2.5,3.96,2.62, 1.41,3.04, 2.53,3.89,2.66, 1.42,3.0),
("Man United","Liverpool",0,3, 3.93,4.31,1.82, 1.44,2.89, 3.51,4.11,2.0, 1.46,2.86),
("Southampton","Man United",0,3, 4.5,4.13,1.74, 1.6,2.41, 4.2,4.12,1.82, 1.56,2.55),
("Brighton","Ipswich",0,0, 1.38,5.13,8.05, 1.56,2.49, 1.53,4.61,6.22, 1.68,2.3),
("Crystal Palace","Leicester",2,2, 1.62,4.13,5.48, 1.76,2.11, 1.67,4.02,5.43, 1.88,2.03),
("Fulham","West Ham",1,1, 2.4,3.53,2.97, 1.72,2.18, 2.36,3.41,3.21, 1.86,2.05),
("Liverpool","Nott'm Forest",0,1, 1.21,7.23,12.71, 1.41,2.95, 1.22,7.11,12.95, 1.4,3.06),
("Man City","Brentford",2,1, 1.17,8.43,14.62, 1.36,3.17, 1.21,7.2,13.92, 1.45,2.85),
("Aston Villa","Everton",3,2, 1.51,4.45,6.48, 1.69,2.23, 1.68,4.0,5.44, 1.82,2.08),
("Bournemouth","Chelsea",0,1, 3.32,3.97,2.06, 1.46,2.81, 3.17,3.79,2.23, 1.5,2.7),
("Tottenham","Arsenal",0,1, 3.03,3.62,2.32, 1.59,2.44, 2.77,3.49,2.63, 1.68,2.29),
("Wolves","Newcastle",1,2, 3.41,3.71,2.1, 1.57,2.49, 3.6,3.73,2.07, 1.68,2.29),
("West Ham","Chelsea",0,3, 3.59,3.93,1.99, 1.53,2.6, 3.59,3.94,2.01, 1.52,2.59),
("Aston Villa","Wolves",3,1, 1.59,4.47,5.44, 1.58,2.47, 1.67,4.21,5.16, 1.68,2.3),
("Fulham","Newcastle",3,1, 2.89,3.54,2.47, 1.71,2.22, 3.02,3.57,2.41, 1.7,2.25),
("Leicester","Everton",1,1, 2.54,3.43,2.88, 1.9,1.99, 2.1,3.52,3.69, 1.81,2.13),
("Liverpool","Bournemouth",3,0, 1.28,6.36,9.45, 1.36,3.2, 1.25,6.85,10.91, 1.33,3.41),
("Southampton","Ipswich",1,1, 2.27,3.5,3.24, 1.8,2.09, 2.42,3.48,3.06, 1.81,2.08),
("Tottenham","Brentford",3,1, 1.55,4.77,5.48, 1.44,2.89, 1.48,5.1,6.23, 1.39,3.14),
("Crystal Palace","Man United",0,0, 2.92,3.76,2.35, 1.62,2.41, 2.8,3.55,2.57, 1.68,2.27),
("Brighton","Nott'm Forest",2,2, 1.79,3.91,4.51, 1.85,2.04, 1.84,3.82,4.45, 1.83,2.07),
("Man City","Arsenal",2,2, 1.85,3.66,4.54, 2.05,1.85, 1.81,3.66,4.91, 2.03,1.88),
("Newcastle","Man City",1,1, 5.18,4.54,1.6, 1.5,2.67, 4.9,4.23,1.69, 1.62,2.42),
("Arsenal","Leicester",4,2, 1.18,8.27,14.09, 1.54,2.57, 1.2,6.8,17.5, 1.6,2.42),
("Brentford","West Ham",1,1, 2.23,3.63,3.22, 1.65,2.33, 2.26,3.56,3.27, 1.67,2.32),
("Chelsea","Brighton",4,2, 1.75,4.3,4.32, 1.51,2.66, 1.81,4.2,4.15, 1.48,2.77),
("Everton","Crystal Palace",2,1, 2.76,3.35,2.69, 1.86,2.03, 2.79,3.35,2.7, 1.93,1.98),
("Nott'm Forest","Fulham",0,1, 2.49,3.32,3.03, 2.01,1.88, 2.65,3.16,3.0, 1.85,2.09),
("Wolves","Liverpool",1,2, 8.09,5.63,1.36, 1.48,2.73, 8.72,5.95,1.33, 1.4,3.06),
("Ipswich","Aston Villa",2,2, 4.34,3.77,1.85, 1.74,2.18, 3.64,3.59,2.1, 1.83,2.11),
("Man United","Tottenham",0,3, 2.42,3.9,2.75, 1.45,2.88, 2.15,3.89,3.27, 1.45,2.91),
("Bournemouth","Southampton",3,1, 1.65,4.37,5.01, 1.49,2.7, 1.49,4.69,6.79, 1.59,2.49),
("Crystal Palace","Liverpool",0,1, 6.38,4.71,1.5, 1.62,2.39, 5.14,4.1,1.69, 1.7,2.26),
("Arsenal","Southampton",3,1, 1.13,9.46,19.13, 1.38,3.16, 1.16,8.18,18.71, 1.45,2.84),
("Brentford","Wolves",5,3, 2.14,3.62,3.44, 1.81,2.08, 2.11,3.61,3.6, 1.79,2.13),
("Leicester","Bournemouth",1,0, 3.35,3.63,2.17, 1.73,2.2, 3.7,3.81,2.02, 1.65,2.36),
("Man City","Fulham",3,2, 1.23,7.15,10.66, 1.47,2.74, 1.26,6.52,11.37, 1.52,2.65),
("West Ham","Ipswich",4,1, 1.81,4.02,4.29, 1.71,2.22, 1.92,3.84,4.05, 1.74,2.2),
("Everton","Newcastle",0,0, 3.18,3.59,2.27, 1.73,2.19, 3.71,3.77,2.0, 1.72,2.22),
("Aston Villa","Man United",0,0, 2.22,3.87,3.09, 1.55,2.57, 2.23,3.84,3.13, 1.49,2.72),
]

MAXG=10; grid=np.arange(0,MAXG+1)
def dc_tau(i,j,lh,la,rho):
    if i==0 and j==0: return 1-lh*la*rho
    if i==0 and j==1: return 1+lh*rho
    if i==1 and j==0: return 1+la*rho
    if i==1 and j==1: return 1-rho
    return 1.0
def smatrix(lh,la,rho):
    ph=poisson.pmf(grid,lh); pa=poisson.pmf(grid,la)
    Mx=np.outer(ph,pa)
    for i in (0,1):
        for j in (0,1): Mx[i,j]*=dc_tau(i,j,lh,la,rho)
    return Mx/Mx.sum()
def implied(lh,la,rho):
    Mx=smatrix(lh,la,rho)
    H=np.tril(Mx,-1).sum(); A=np.triu(Mx,1).sum(); D=np.trace(Mx)
    tot=np.add.outer(grid,grid); Over=Mx[tot>=3].sum()
    return H,D,A,Over
def devig(o):
    inv=[1/x for x in o]; s=sum(inv); return [x/s for x in inv]
def fit(tH,tD,tA,tOver):
    def loss(x):
        lh,la,rho=x
        if lh<=0 or la<=0: return 1e6
        H,D,A,Over=implied(lh,la,rho)
        return (H-tH)**2+(D-tD)**2+(A-tA)**2+(Over-tOver)**2
    r=minimize(loss,[1.4,1.1,-0.05],method="Nelder-Mead",
               options={"xatol":1e-6,"fatol":1e-10,"maxiter":4000})
    return r.x

# 累加器
exact_hit=0; outcome_hit=0
brier=0.0; logloss=0.0
ll_open=0.0; ll_close=0.0
over_pred=0.0; over_actual=0
calib=[]  # (pred_prob, hit) 对每个 H/D/A 结果
n=len(M)
for row in M:
    home,away,fh,fa = row[0],row[1],row[2],row[3]
    psh,psd,psa, pO,pU = row[4],row[5],row[6],row[7],row[8]
    psch,pscd,psca, pcO,pcU = row[9],row[10],row[11],row[12],row[13]

    # 收盘公允概率
    mH,mD,mA = devig([psch,pscd,psca])
    fairOver = devig([pcO,pcU])[0]
    lh,la,rho = fit(mH,mD,mA,fairOver)
    Mx = smatrix(lh,la,rho)
    pH,pD,pA,pOver = implied(lh,la,rho)

    # 实际结果
    res = 'H' if fh>fa else ('A' if fa>fh else 'D')
    yH,yD,yA = int(res=='H'),int(res=='D'),int(res=='A')

    # 1) 精确比分命中
    pred_score = np.unravel_index(np.argmax(Mx[:7,:7]), (7,7))
    if (pred_score[0],pred_score[1])==(fh,fa): exact_hit+=1
    # 2) 最可能赛果(胜平负)命中
    probs={'H':pH,'D':pD,'A':pA}
    if max(probs,key=probs.get)==res: outcome_hit+=1
    # 3) Brier / logloss (多分类 1X2)
    brier += (pH-yH)**2+(pD-yD)**2+(pA-yA)**2
    py = {'H':pH,'D':pD,'A':pA}[res]
    logloss += -np.log(max(py,1e-9))
    # 4) 校准:把每个结果当一个二元预测
    calib += [(pH,yH),(pD,yD),(pA,yA)]
    # 5) 大小球
    over_pred += pOver
    over_actual += int(fh+fa>=3)
    # 6) 开盘 vs 收盘 log-loss(检验"收盘更聪明")
    oH,oD,oA = devig([psh,psd,psa])
    ll_open  += -np.log(max({'H':oH,'D':oD,'A':oA}[res],1e-9))
    ll_close += -np.log(max({'H':mH,'D':mD,'A':mA}[res],1e-9))

print("="*58)
print(f"真实回测:英超 2024-25 前 {n} 场(收盘 Pinnacle 赔率)")
print("="*58)
print(f"精确比分命中率   {exact_hit}/{n} = {exact_hit/n*100:.1f}%   (理论上限~12%)")
print(f"最可能赛果命中   {outcome_hit}/{n} = {outcome_hit/n*100:.1f}%")
print(f"多分类 Brier     {brier/n:.3f}   (越低越好, 0.67≈瞎猜三选一)")
print(f"Log-loss(收盘)   {logloss/n:.3f}")
print()
print(f"大小球: 模型预测大球均值 {over_pred/n*100:.1f}%  vs  实际大球率 {over_actual/n*100:.1f}%")
print()
print(f"开盘 log-loss {ll_open/n:.4f}  vs  收盘 log-loss {ll_close/n:.4f}"
      f"   -> 收盘{'更准 ✓' if ll_close<ll_open else '没更准 ✗'}")
print()

# 校准表
print("概率校准(把每场 H/D/A 当独立预测, 共 %d 个):" % len(calib))
print(f"{'预测区间':>10} {'数量':>5} {'预测均值':>9} {'实际频率':>9} {'偏差':>7}")
bins=[(0,.1),(.1,.2),(.2,.3),(.3,.5),(.5,.7),(.7,1.01)]
for lo,hi in bins:
    g=[(p,y) for p,y in calib if lo<=p<hi]
    if not g: continue
    pm=np.mean([p for p,_ in g]); ac=np.mean([y for _,y in g])
    print(f"{int(lo*100):>4}-{int(hi*100) if hi<=1 else 100:>3}% {len(g):>5} "
          f"{pm*100:>8.1f}% {ac*100:>8.1f}% {(ac-pm)*100:>+6.0f}%")
