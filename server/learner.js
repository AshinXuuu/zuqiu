/* ============================================================
   learner.js — 比分分布形状自学习(零依赖)

   原理:市场盘口锁定 {胜平负}×{大小} 六类边际,学习的只是六类内部
   各比分的分布形状(3 个倾斜参数 low/high/narrow,见 market_model.adjustMatrix)。
   防自欺:
   - 按时间 70/30 切训练/验证,参数只在训练集上选;
   - 验证集平均对数似然比基线(不校正)提升 < 门槛 → 拒绝启用;
   - 样本 <150 场不学。

   用法:const {learn}=require('./learner.js');
        const report=learn(historyArray);   // [{odds,hg,ag,ts}...]
   ============================================================ */
'use strict';
const path = require('path');
let MM;
try { MM = require(path.join(__dirname, 'market_model.js')); }          // 服务器:/opt/odds-proxy/
catch(e){ MM = require(path.join(__dirname, '..', 'market_model.js')); } // 本地仓库:outputs/

const MIN_SAMPLE = 150;
const MIN_GAIN = 0.005;          // 验证集平均对数似然至少提升这么多才启用
const GRID = [-0.3,-0.2,-0.1,0,0.1,0.2,0.3];

function learn(hist){
  const done = (hist||[])
    .filter(h => h && h.odds && h.hg!=null && h.ag!=null)
    .sort((x,y)=>(x.ts||0)-(y.ts||0));
  if (done.length < MIN_SAMPLE)
    return {ok:false, sample:done.length,
      message:'样本不足:已有赛果 '+done.length+' 场,需 ≥'+MIN_SAMPLE+' 场。继续积累即可。'};

  /* 每场先算一次基础矩阵(耗时主要在这) */
  const items = [];
  for (const h of done){
    const r = MM.matrixFromOdds(h.odds);
    if (!r) continue;
    const hg = Math.min(MM.MAXG, +h.hg), ag = Math.min(MM.MAXG, +h.ag);
    items.push({M:r.M, line:r.line, hg:hg, ag:ag});
  }
  if (items.length < MIN_SAMPLE)
    return {ok:false, sample:items.length, message:'可用样本不足('+items.length+' 场盘口可拟合)。'};

  const nTrain = Math.floor(items.length*0.7);
  const train = items.slice(0, nTrain), val = items.slice(nTrain);

  function avgLL(set, adj){
    let s=0, n=0;
    for (const it of set){
      const M = adj ? MM.adjustMatrix(it.M, adj, it.line) : it.M;
      const p = M[it.hg][it.ag];
      s += Math.log(Math.max(p, 1e-9)); n++;
    }
    return s/n;
  }
  function top3Rate(set, adj){
    let hit=0;
    for (const it of set){
      const M = adj ? MM.adjustMatrix(it.M, adj, it.line) : it.M;
      const top = MM.topScores(M,3);
      if (top.some(t=>t[0]===it.hg&&t[1]===it.ag)) hit++;
    }
    return hit/set.length;
  }

  /* 训练集上网格搜索 */
  let best={low:0,high:0,narrow:0}, bestLL=avgLL(train,null);
  for (const a of GRID) for (const b of GRID) for (const c of GRID){
    if (!a && !b && !c) continue;
    const ll = avgLL(train, {low:a,high:b,narrow:c});
    if (ll > bestLL){ bestLL=ll; best={low:a,high:b,narrow:c}; }
  }

  /* 验证集裁决 */
  const valBase = avgLL(val, null);
  const valNew  = avgLL(val, best);
  const gain = valNew - valBase;
  const applied = gain >= MIN_GAIN && (best.low||best.high||best.narrow);
  const rep = {
    ok: true, sample: items.length, train: train.length, val: val.length,
    params: best, valBase: +valBase.toFixed(4), valNew: +valNew.toFixed(4),
    valGain: +gain.toFixed(4), applied: !!applied,
    top3Base: +(top3Rate(val,null)*100).toFixed(1),
    top3New:  +(top3Rate(val,best)*100).toFixed(1),
    message: applied
      ? ('已启用校正 low='+best.low+' high='+best.high+' narrow='+best.narrow
         +'(验证集似然 +'+gain.toFixed(4)+'/场,TOP3 '+ (top3Rate(val,null)*100).toFixed(1)+'%→'+(top3Rate(val,best)*100).toFixed(1)+'%)')
      : ('验证集提升不足(+'+gain.toFixed(4)+'/场,门槛 '+MIN_GAIN+'),按泊松基线更稳,未启用校正。这是正常结果,继续积累样本。')
  };
  return rep;
}

module.exports = { learn: learn, MIN_SAMPLE: MIN_SAMPLE };
