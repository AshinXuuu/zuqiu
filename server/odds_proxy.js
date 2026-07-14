#!/usr/bin/env node
/* ============================================================
   odds_proxy.js — The Odds API 缓存代理(零依赖,Node ≥14)

   作用:
   1. API key 只存在服务器上,前端/小程序不再暴露 key
   2. 同一请求 10 分钟内所有访客共享缓存 —— 免费额度从
      「每个访客都烧一次」变成「全站每 10 分钟最多一次」
   3. 上游挂了/额度尽了自动退回旧缓存(有多旧用多旧),站点不白屏

   启动:
     ODDS_API_KEY=你的key node odds_proxy.js
     # 或把 key 写进同目录 key.txt(一行),然后 node odds_proxy.js

   环境变量:
     ODDS_API_KEY   上游 key(优先);否则读 ./key.txt
     PORT           监听端口,默认 8787
     ODDS_UPSTREAM  上游主机,默认 api.the-odds-api.com(测试用)

   路由(与 the-odds-api v4 一致,前端只需把域名换成本站 /api):
     GET /ping                        探活,返回 {ok:true}
     GET /v4/sports/                  联赛列表(缓存 24h)
     GET /v4/sports/{sk}/odds/?...    赔率(缓存 10min)
     GET /v4/sports/{sk}/scores/?...  赛果(缓存 10min)
   ============================================================ */
'use strict';
const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');

const PORT = +(process.env.PORT || 8787);
const UPSTREAM = process.env.ODDS_UPSTREAM || 'api.the-odds-api.com';
const UPSTREAM_TLS = !process.env.ODDS_UPSTREAM;          // 自定义上游(测试)走 http
const CACHE_FILE = path.join(__dirname, 'cache.json');

/* key 池:优先 keys.json(管理后台维护,可多个),否则 ODDS_API_KEY / key.txt。
   额度用尽(401/429)自动切下一个,并记住上次可用的。 */
function loadKeys(){
  try{ const a=JSON.parse(fs.readFileSync(path.join(__dirname,'keys.json'),'utf8'));
    if (Array.isArray(a) && a.length) return a.map(String); }catch(e){}
  if (process.env.ODDS_API_KEY) return [process.env.ODDS_API_KEY.trim()];
  try { const k=fs.readFileSync(path.join(__dirname,'key.txt'),'utf8').trim(); if(k) return [k]; } catch(e){}
  return [];
}
let lastGoodKey = 0;
if (!loadKeys().length) console.warn('警告:当前没有配置任何 API key(keys.json / ODDS_API_KEY / key.txt),等配置后自动生效');

/* 缓存:内存 Map + 落盘(重启不丢) */
const TTL = { odds: 10*60e3, scores: 10*60e3, sports: 24*3600e3 };
let cache = {};
try { cache = JSON.parse(fs.readFileSync(CACHE_FILE,'utf8')) || {}; } catch(e){}
let saveTimer = null;
function persist(){
  if (saveTimer) return;
  saveTimer = setTimeout(function(){
    saveTimer = null;
    fs.writeFile(CACHE_FILE, JSON.stringify(cache), function(){});
  }, 2000);
}

/* 路由白名单:只放行这三类只读请求,防止代理被当通用跳板 */
const ROUTES = [
  { re: /^\/v4\/sports\/?$/,                          kind: 'sports' },
  { re: /^\/v4\/sports\/([a-z0-9_]+)\/odds\/?$/,      kind: 'odds'   },
  { re: /^\/v4\/sports\/([a-z0-9_]+)\/scores\/?$/,    kind: 'scores' },
];
/* 查询参数白名单(apiKey 一律由服务端注入,忽略客户端传的) */
const OK_PARAMS = ['regions','markets','oddsFormat','daysFrom','dateFormat','bookmakers'];

function upstreamGet(pathAndQuery, cb){
  const mod = UPSTREAM_TLS ? https : http;
  const req = mod.get({ host: UPSTREAM.split(':')[0],
    port: UPSTREAM.includes(':') ? +UPSTREAM.split(':')[1] : (UPSTREAM_TLS?443:80),
    path: pathAndQuery, headers: {'accept':'application/json'} }, function(res){
    let body='';
    res.on('data', d=>body+=d);
    res.on('end', ()=>cb(null, res.statusCode, body, {
      remaining: res.headers['x-requests-remaining'],
      used: res.headers['x-requests-used'] }));
  });
  req.on('error', err=>cb(err));
  req.setTimeout(15000, function(){ req.destroy(new Error('upstream timeout')); });
}

const server = http.createServer(function(req, res){
  const u = new URL(req.url, 'http://x');
  /* CORS:站点同域下用不到,但留着方便本地调试/小程序 web-view */
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Expose-Headers', 'x-requests-remaining, x-cache');
  if (req.method === 'OPTIONS') { res.writeHead(204); return res.end(); }
  if (req.method !== 'GET') { res.writeHead(405); return res.end('{"message":"GET only"}'); }

  if (u.pathname === '/ping'){
    res.writeHead(200, {'content-type':'application/json'});
    return res.end('{"ok":true}');
  }

  const route = ROUTES.find(r => r.re.test(u.pathname));
  if (!route){ res.writeHead(404, {'content-type':'application/json'});
    return res.end('{"message":"not found"}'); }

  /* 规范化缓存键:路径 + 白名单参数(排序) */
  const q = new URLSearchParams();
  OK_PARAMS.forEach(k => { const v=u.searchParams.get(k); if(v!=null) q.set(k, v); });
  q.sort && q.sort();
  const ckey = u.pathname + '?' + q.toString();
  const ttl = TTL[route.kind];
  const hit = cache[ckey];
  const now = Date.now();

  function send(status, body, extra, tag){
    const h = {'content-type':'application/json', 'x-cache': tag};
    if (extra && extra.remaining != null) h['x-requests-remaining'] = extra.remaining;
    res.writeHead(status, h);
    res.end(body);
  }

  if (hit && now - hit.ts < ttl) return send(200, hit.body, hit.extra, 'HIT');

  /* 未命中/过期 → 打上游,key 池按序尝试(额度尽/无效自动切下一个) */
  const keys = loadKeys();
  if (!keys.length){
    if (hit) return send(200, hit.body, hit.extra, 'STALE');
    res.writeHead(500, {'content-type':'application/json'});
    return res.end('{"message":"服务端未配置 API key"}');
  }
  (function attempt(n){
    const idx = (lastGoodKey + n) % keys.length;
    q.set('apiKey', keys[idx]);
    upstreamGet(u.pathname + '?' + q.toString(), function(err, status, body, extra){
      if (!err && status === 200){
        lastGoodKey = idx;
        cache[ckey] = { ts: now, body: body, extra: extra };
        persist();
        return send(200, body, extra, n>0 ? 'MISS-KEY'+(idx+1) : 'MISS');
      }
      /* 额度尽/无效 → 换下一个 key 再试 */
      if (!err && (status===401 || status===429) && n+1 < keys.length){
        console.warn('key #'+(idx+1)+' 失效('+status+'),切换下一个');
        return attempt(n+1);
      }
      /* 全部失败:有旧缓存就退回旧的,没有才透传错误 */
      if (hit) return send(200, hit.body, hit.extra, 'STALE');
      if (err){ res.writeHead(502, {'content-type':'application/json'});
        return res.end(JSON.stringify({message:'upstream error: '+err.message})); }
      return send(status, body, extra, 'PASS');
    });
  })(0);
});

server.listen(PORT, '127.0.0.1', function(){
  console.log('odds_proxy 监听 127.0.0.1:'+PORT+'  上游 '+UPSTREAM+'  key 池 '+loadKeys().length+' 个');
});
