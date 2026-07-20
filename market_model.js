/* ============================================================
   market_model.js — 数学层:de-vig + Dixon-Coles 双泊松
   无任何 DOM / 平台依赖,浏览器、Node、小程序均可直接复用。

   浏览器:  <script src="market_model.js"></script> 后全局可用
   Node:    const MM = require('./market_model.js')
   小程序:  const MM = require('market_model.js')

   接口:
     devig(oddsArr)           -> {p:[...], overround}   按比例去水位
     scoreMatrix(lh,la,rho)   -> 归一化比分概率矩阵 (0..MAXG)×(0..MAXG)
     implied(M,line)          -> {H,D,A,Over}           矩阵→胜平负/大球概率
     ahHomeProb(M,line)       -> 亚盘主队覆盖概率(支持 .25/.75 盘,push 记 0.5)
     fit(target,line)         -> {lh,la,rho,e}          市场公允概率反推参数
     topScores(M,n)           -> [[i,j,p]...]           概率最高的 n 个比分
     predictFromOdds(od)      -> {pH,pD,pA,pOver,lh,la,line,top} | null
                                 od = {H,D,A,line,over,under,ahLine?,ahHome?,ahAway?}
   ============================================================ */
(function(root, factory){
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api; // Node / 小程序
  for (var k in api) root[k] = api[k];                                       // 浏览器全局
})(typeof globalThis !== 'undefined' ? globalThis : this, function(){
"use strict";

const MAXG = 10;
const fact = [1]; for(let i=1;i<=MAXG;i++) fact[i]=fact[i-1]*i;
function pois(k,l){ return Math.exp(-l)*Math.pow(l,k)/fact[k]; }

/* Dixon-Coles 低比分修正因子 */
function tau(i,j,lh,la,rho){
  if(i===0&&j===0) return 1-lh*la*rho;
  if(i===0&&j===1) return 1+lh*rho;
  if(i===1&&j===0) return 1+la*rho;
  if(i===1&&j===1) return 1-rho;
  return 1;
}

function scoreMatrix(lh,la,rho){
  const ph=[],pa=[];
  for(let k=0;k<=MAXG;k++){ph[k]=pois(k,lh);pa[k]=pois(k,la);}
  const M=[]; let s=0;
  for(let i=0;i<=MAXG;i++){M[i]=[];for(let j=0;j<=MAXG;j++){
    let v=ph[i]*pa[j]*tau(i,j,lh,la,rho); M[i][j]=v; s+=v;}}
  for(let i=0;i<=MAXG;i++)for(let j=0;j<=MAXG;j++)M[i][j]/=s;
  return M;
}

function implied(M,line){
  let H=0,D=0,A=0,Over=0;
  for(let i=0;i<=MAXG;i++)for(let j=0;j<=MAXG;j++){
    const p=M[i][j];
    if(i>j)H+=p; else if(i<j)A+=p; else D+=p;
    if(i+j>line)Over+=p;
  }
  return {H,D,A,Over};
}

/* 按比例去水位(两侧对称盘如大小球/让球适用) */
function devig(arr){
  const inv=arr.map(o=>1/o), s=inv.reduce((a,b)=>a+b,0);
  return {p:inv.map(x=>x/s), overround:s};
}

/* 幂法去水位:p_i = (1/o_i)^k,解 k 使 Σp=1。
   等比例法会高估长赔(favorite-longshot bias),幂法把更多水位从热门端扣除,
   对含冷门的 1X2 更准。o 全部 ≥1 且 overround>1 时 k>1。 */
function devigPower(arr){
  const inv=arr.map(o=>1/o), s0=inv.reduce((a,b)=>a+b,0);
  if(s0<=1) return {p:inv.map(x=>x/s0), overround:s0, k:1};
  const f=k=>inv.reduce((a,x)=>a+Math.pow(x,k),0)-1;
  let lo=1, hi=5;
  for(let i=0;i<60;i++){ const mid=(lo+hi)/2; if(f(mid)>0) lo=mid; else hi=mid; }
  const k=(lo+hi)/2;
  let p=inv.map(x=>Math.pow(x,k));
  const s=p.reduce((a,b)=>a+b,0);
  return {p:p.map(x=>x/s), overround:s0, k};
}

/* Shin 法去水位(内幕交易者模型),赛马/足球 1X2 文献常用,效果与幂法接近 */
function devigShin(arr){
  const pi=arr.map(o=>1/o), S=pi.reduce((a,b)=>a+b,0);
  if(S<=1) return {p:pi.map(x=>x/S), overround:S, z:0};
  const probs=z=>pi.map(x=>(Math.sqrt(z*z+4*(1-z)*x*x/S)-z)/(2*(1-z)));
  const g=z=>probs(z).reduce((a,b)=>a+b,0)-1;   // z=0 时 =√S-1>0,随 z 递减
  let lo=0, hi=0.4;
  for(let i=0;i<60;i++){ const mid=(lo+hi)/2; if(g(mid)>0) lo=mid; else hi=mid; }
  const z=(lo+hi)/2, p=probs(z), s=p.reduce((a,b)=>a+b,0);
  return {p:p.map(x=>x/s), overround:S, z};
}

/* 让球(亚盘):主队让 line 时,backing 主队的公允覆盖概率(push 记 0.5,支持 .25/.75 盘) */
function ahHomeProb(M,line){
  const md={};
  for(let i=0;i<=MAXG;i++)for(let j=0;j<=MAXG;j++){const m=i-j; md[m]=(md[m]||0)+M[i][j];}
  function half(h0){ let win=0,push=0;
    for(const k in md){ const v=(+k)+h0; if(v>1e-9)win+=md[k]; else if(Math.abs(v)<1e-9)push+=md[k]; }
    return win+0.5*push; }
  const q=Math.round(line*4);
  return (q%2!==0)?0.5*(half(line-0.25)+half(line+0.25)):half(line);
}

/* 拟合:两阶段搜索 (lh,la,rho) 匹配市场公允概率(含可选让球)
   阶段1 固定 rho 粗扫 λ 平面(rho 对 1X2/大小球影响很小);
   阶段2 围绕最优点做 3D 局部细化。
   与旧版 4 轮全 3D 网格精度一致(误差 <1e-3),计算量约为其 1/10。 */
function fit(target,line){
  function sse(lh,la,rho){
    const M=scoreMatrix(lh,la,rho);
    const m=implied(M,line);
    let e=(m.H-target.H)**2+(m.D-target.D)**2+(m.A-target.A)**2+(m.Over-target.Over)**2;
    if(target.ah!=null) e+=2*(ahHomeProb(M,target.ahLine)-target.ah)**2;  // 让球权重稍高,强化强弱差
    return e;
  }
  const R0=-0.06;
  let best={lh:1.4,la:1.1,rho:R0,e:1e9};
  /* 阶段1:rho 固定,coarse→fine 扫 (lh,la) */
  let loH=0.10,hiH=4.5,loA=0.10,hiA=3.2;
  for(let pass=0;pass<3;pass++){
    const n=(pass===0?24:12);
    for(let a=0;a<=n;a++){const lh=loH+(hiH-loH)*a/n;
      for(let b=0;b<=n;b++){const la=loA+(hiA-loA)*b/n;
        const e=sse(lh,la,R0);
        if(e<best.e)best={lh,la,rho:R0,e};
      }}
    const dH=(hiH-loH)/n, dA=(hiA-loA)/n;
    loH=Math.max(0.05,best.lh-dH);hiH=best.lh+dH;
    loA=Math.max(0.05,best.la-dA);hiA=best.la+dA;
  }
  /* 阶段2:围绕最优点 3D 局部细化(rho 放开) */
  let loR=-0.18,hiR=0.05;
  loH=Math.max(0.05,best.lh-0.12);hiH=best.lh+0.12;
  loA=Math.max(0.05,best.la-0.12);hiA=best.la+0.12;
  for(let pass=0;pass<3;pass++){
    const nH=6,nA=6,nR=7;
    for(let a=0;a<=nH;a++){const lh=loH+(hiH-loH)*a/nH;
      for(let b=0;b<=nA;b++){const la=loA+(hiA-loA)*b/nA;
        for(let c=0;c<=nR;c++){const rho=loR+(hiR-loR)*c/nR;
          const e=sse(lh,la,rho);
          if(e<best.e)best={lh,la,rho,e};
        }}}
    const dH=(hiH-loH)/nH, dA=(hiA-loA)/nA, dR=(hiR-loR)/nR;
    loH=Math.max(0.05,best.lh-dH);hiH=best.lh+dH;
    loA=Math.max(0.05,best.la-dA);hiA=best.la+dA;
    loR=best.rho-dR;hiR=best.rho+dR;
  }
  return best;
}

/* 概率最高的 n 个比分 */
function topScores(M,n){
  const flat=[];
  for(let i=0;i<=MAXG;i++)for(let j=0;j<=MAXG;j++)flat.push([i,j,M[i][j]]);
  flat.sort((a,b)=>b[2]-a[2]);
  return flat.slice(0,n||10);
}

/* ===== 自学习形状校正 =====
   市场盘口锁定了 {胜/平/负}×{大/小} 六类的边际概率;泊松假设决定的是
   六类内部各比分的分布形状。adjustMatrix 用 3 个从历史赛果学到的参数
   对形状做乘性倾斜,再按六类精确归一回原边际 —— 不改变市场概率,
   只重新分配同类内的比分权重(TOP3 更贴近真实比分分布)。
   adj = {low, high, narrow}:
     low    低比分倾斜(总进球 ≤1 的格子)
     high   高比分倾斜(总进球 ≥5 的格子)
     narrow 一球小胜倾斜(净胜 1 球且总进球 ≤3:1-0/2-1/0-1/1-2) */
function adjustMatrix(M, adj, line){
  if(!adj) return M;
  const a=+adj.low||0, b=+adj.high||0, c=+adj.narrow||0;
  if(!a&&!b&&!c) return M;
  const cls=(i,j)=>(i>j?0:(i===j?1:2))+((i+j>line)?0:3);   // 六类:{H,D,A}×{大,小}
  const target=[0,0,0,0,0,0];
  for(let i=0;i<=MAXG;i++)for(let j=0;j<=MAXG;j++) target[cls(i,j)]+=M[i][j];
  const A=[];
  for(let i=0;i<=MAXG;i++){A[i]=[];for(let j=0;j<=MAXG;j++){
    let w=0;
    if(i+j<=1) w+=a;
    if(i+j>=5) w+=b;
    if(Math.abs(i-j)===1&&i+j<=3) w+=c;
    A[i][j]=M[i][j]*Math.exp(w);
  }}
  const cur=[0,0,0,0,0,0];
  for(let i=0;i<=MAXG;i++)for(let j=0;j<=MAXG;j++) cur[cls(i,j)]+=A[i][j];
  for(let i=0;i<=MAXG;i++)for(let j=0;j<=MAXG;j++){
    const k=cls(i,j); if(cur[k]>0) A[i][j]*=target[k]/cur[k];
  }
  return A;
}

/* 从赔率反推比分矩阵(fit 的完整输出,学习器要用) */
function matrixFromOdds(od,opts){
  const oH=+od.H,oD=+od.D,oA=+od.A,oOver=+od.over,oUnder=+od.under,line=+od.line;
  if(!(oH>1&&oD>1&&oA>1&&oOver>1&&oUnder>1)) return null;
  const method=(opts&&opts.devig1x2)||'power';
  const dv=method==='shin'?devigShin:(method==='prop'?devig:devigPower);
  const d1=dv([oH,oD,oA]), d2=devig([oOver,oUnder]);
  const target={H:d1.p[0],D:d1.p[1],A:d1.p[2],Over:d2.p[0]};
  if(od.ahLine!=null&&+od.ahHome>1&&+od.ahAway>1){ target.ah=devig([+od.ahHome,+od.ahAway]).p[0]; target.ahLine=+od.ahLine; }
  const f=fit(target,line);
  return {M:scoreMatrix(f.lh,f.la,f.rho), line:line, lh:f.lh, la:f.la, rho:f.rho, e:f.e};
}

/* 从一组盘口赔率生成完整预测快照(纯函数)
   opts.devig1x2: 'power'(默认)| 'shin' | 'prop' —— 1X2 去水位方法
   opts.adjust:   自学习形状校正参数 {low,high,narrow}(可选) */
function predictFromOdds(od,opts){
  const r=matrixFromOdds(od,opts);
  if(!r) return null;
  let M=r.M;
  if(opts&&opts.adjust) M=adjustMatrix(M,opts.adjust,r.line);
  const im=implied(M,r.line);
  return {pH:+im.H.toFixed(4),pD:+im.D.toFixed(4),pA:+im.A.toFixed(4),pOver:+im.Over.toFixed(4),
          lh:+r.lh.toFixed(3),la:+r.la.toFixed(3),line:r.line,
          adj:(opts&&opts.adjust)?1:0,
          top:topScores(M,6).map(t=>[t[0],t[1],+t[2].toFixed(4)])};
}

return {MAXG,pois,tau,scoreMatrix,implied,devig,devigPower,devigShin,ahHomeProb,fit,topScores,
        adjustMatrix,matrixFromOdds,predictFromOdds};
});
