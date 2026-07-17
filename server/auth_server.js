#!/usr/bin/env node
/* ============================================================
   auth_server.js — 邮箱验证码登录 + 邀请白名单(零依赖,Node ≥14)

   功能:
   - 只有白名单(受邀)邮箱能收验证码、登录
   - 6 位验证码,10 分钟有效,60 秒重发间隔,最多试错 5 次
   - 登录发 HttpOnly 会话 cookie(30 天),配合 nginx auth_request 保护整站
   - 管理员接口:邀请/移除邮箱、查看名单
   - 内置极简 SMTP 客户端(TLS),用你自己的邮箱发信,发件人显示 noreply

   配置(同目录 smtp.json):
     { "host":"smtp.yeah.net", "port":465, "secure":true,
       "user":"你的邮箱@yeah.net", "pass":"SMTP授权码",
       "from":"noreply <你的邮箱@yeah.net>" }
     注:多数邮箱要求发件地址=登录账号,只有显示名可以自定义为 noreply。

   环境变量:
     PORT       默认 8788
     DATA_DIR   数据目录,默认 ./data(whitelist.json / sessions.json)
     SMTP_MOCK  =1 时不真发信,验证码打到日志(联调用)

   路由(全部挂在 /auth 下,nginx 转发):
     POST /auth/request-code {email}
     POST /auth/verify       {email,code}   → Set-Cookie: sid=...
     GET  /auth/check                        → 204/401(给 nginx auth_request 用)
     GET  /auth/me                           → {email,admin}
     POST /auth/logout
     GET  /auth/admin/list                   (管理员)
     POST /auth/admin/invite {email}         (管理员)
     POST /auth/admin/remove {email}         (管理员)
   ============================================================ */
'use strict';
const http = require('http');
const tls = require('tls');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const net = require('net');

const PORT = +(process.env.PORT || 8788);
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const MOCK = process.env.SMTP_MOCK === '1';
const PROXY_BASE = process.env.PROXY_BASE || 'http://127.0.0.1:8787';  // odds_proxy 地址
const KEYS_FILE = process.env.KEYS_FILE || path.join(__dirname, 'keys.json');
const KEYTXT_FILE = path.join(__dirname, 'key.txt');
const SESSION_DAYS = 30;
const CODE_TTL = 10 * 60e3;
const RESEND_GAP = 60e3;
const MAX_TRIES = 5;

if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

/* ---------- 小工具 ---------- */
function loadJSON(f, def){ try { return JSON.parse(fs.readFileSync(path.join(DATA_DIR,f),'utf8')); } catch(e){ return def; } }
function saveJSON(f, obj){ fs.writeFileSync(path.join(DATA_DIR,f), JSON.stringify(obj, null, 2)); }
function normEmail(e){ return String(e||'').trim().toLowerCase(); }
function validEmail(e){ return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e) && e.length < 100; }
function json(res, status, obj, extraHeaders){
  const h = Object.assign({'content-type':'application/json; charset=utf-8'}, extraHeaders||{});
  res.writeHead(status, h); res.end(JSON.stringify(obj));
}
function readBody(req, cb){
  let b=''; req.on('data', d=>{ b+=d; if(b.length>10240) req.destroy(); });
  req.on('end', ()=>{ try{ cb(JSON.parse(b||'{}')); }catch(e){ cb(null); } });
}
function parseCookies(req){
  const out={}; (req.headers.cookie||'').split(';').forEach(p=>{
    const i=p.indexOf('='); if(i>0) out[p.slice(0,i).trim()]=p.slice(i+1).trim(); });
  return out;
}

/* ---------- 数据 ---------- */
/* whitelist.json:{admins:[...], users:[...]}。管理员天然在白名单内。 */
let wl = loadJSON('whitelist.json', null);
if (!wl){ wl = { admins: ['ashinxu@yeah.net'], users: [] }; saveJSON('whitelist.json', wl); }
function isInvited(e){ return wl.admins.includes(e) || wl.users.includes(e); }
function isAdmin(e){ return wl.admins.includes(e); }

let sessions = loadJSON('sessions.json', {});
let sessDirty = false;
setInterval(function(){          // 定期清过期会话 + 落盘
  const cut = Date.now() - SESSION_DAYS*864e5;
  for (const t in sessions) if (sessions[t].ts < cut){ delete sessions[t]; sessDirty = true; }
  if (sessDirty){ saveJSON('sessions.json', sessions); sessDirty = false; }
}, 60e3).unref();

const codes = new Map();   // email -> {code, exp, tries, lastSent}

/* ---------- 云端数据快照:管理员拉取,所有登录用户只读 ----------
   snapshot.json 只保留最新一份(几十~几百 KB,存磁盘不占内存) */
function httpGetJSON(url, cb){
  const req = http.get(url, function(res){
    let b=''; res.on('data', d=>b+=d);
    res.on('end', function(){ let j=null; try{ j=JSON.parse(b); }catch(e){}
      cb(null, res.statusCode, j, res.headers); });
  });
  req.on('error', function(e){ cb(e); });
  req.setTimeout(20000, function(){ req.destroy(new Error('timeout')); });
}
function refreshSnapshot(leagues, by, cb){
  const sks = (leagues||[]).filter(function(s){ return /^[a-z0-9_]{3,60}$/.test(s); }).slice(0,12);
  if (!sks.length) return cb(new Error('没有选择联赛'));
  const odds=[], scores=[], failed=[];
  let remaining=null, i=0;
  (function next(){
    if (i >= sks.length){
      const snap = { ts: Date.now(), by: by, leagues: sks, odds: odds, scores: scores,
                     failed: failed, remaining: remaining };
      saveJSON('snapshot.json', snap);
      return cb(null, snap);
    }
    const sk = sks[i++];
    httpGetJSON(PROXY_BASE+'/v4/sports/'+sk+'/odds/?regions=eu&markets=h2h,totals,spreads&oddsFormat=decimal',
      function(err, st, data, hdr){
        if (!err && st===200 && Array.isArray(data)){
          data.forEach(function(ev){ ev._sk=sk; }); odds.push.apply(odds, data);
          if (hdr && hdr['x-requests-remaining']!=null) remaining=hdr['x-requests-remaining'];
        } else failed.push(sk);
        httpGetJSON(PROXY_BASE+'/v4/sports/'+sk+'/scores/?daysFrom=3',
          function(err2, st2, data2){
            if (!err2 && st2===200 && Array.isArray(data2)){
              data2.forEach(function(ev){ ev._sk=sk; }); scores.push.apply(scores, data2);
            }
            next();
          });
      });
  })();
}

/* ---------- 定时自动拉取:按 settings.json 的 auto 配置,到点自动刷新快照
   两种模式:interval=每 N 小时;times=每天北京时间定点(如 10:00、18:00)。
   定点模式带补拉:到点时服务器不在线,恢复后发现"快照早于今天该时点"会立即补拉。 ---------- */
let lastAutoAttempt = 0;
/* 今天(北京,UTC+8 无夏令时)已到的时间点里,是否有快照没覆盖到的 → 该拉了 */
function dueAtTimes(times, snapTs){
  const now = Date.now(), off = 8*3600e3;
  const bjDayStart = Math.floor((now+off)/864e5)*864e5 - off;
  return (times||[]).some(function(t){
    const m = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec(String(t).trim());
    if (!m) return false;
    const slot = bjDayStart + (+m[1])*3600e3 + (+m[2])*60e3;
    return now >= slot && (!snapTs || snapTs < slot);
  });
}
setInterval(function(){
  const st = loadJSON('settings.json', null);
  if (!st || !st.auto || !st.auto.enabled) return;
  const a = st.auto;
  const snap = loadJSON('snapshot.json', null);
  let due;
  if (a.mode === 'times'){
    due = dueAtTimes(a.times, snap && snap.ts);
  } else {
    const hours = Math.min(48, Math.max(1, +a.hours || 6));
    due = !snap || Date.now() - snap.ts >= hours*3600e3;
  }
  if (!due) return;
  if (Date.now() - lastAutoAttempt < 10*60e3) return;             // 失败重试至少隔 10 分钟
  lastAutoAttempt = Date.now();
  refreshSnapshot(st.leagues || ['soccer_fifa_world_cup'], '自动定时', function(err, s2){
    console.log(err ? ('自动拉取失败: '+err.message)
                    : ('自动拉取完成: '+s2.odds.length+' 场赔率 / '+s2.scores.length+' 场赛果'));
  });
}, 60e3).unref();

/* ---------- key 池(keys.json,供 odds_proxy 轮换) ---------- */
function loadKeys(){
  try{ const a=JSON.parse(fs.readFileSync(KEYS_FILE,'utf8'));
    if(Array.isArray(a)) return a.map(String); }catch(e){}
  /* 从旧的 key.txt 迁移 */
  try{ const k=fs.readFileSync(KEYTXT_FILE,'utf8').trim();
    if(k){ fs.writeFileSync(KEYS_FILE, JSON.stringify([k],null,2)); return [k]; } }catch(e){}
  return [];
}
function saveKeys(a){ fs.writeFileSync(KEYS_FILE, JSON.stringify(a,null,2)); }
function maskKey(k){ return k.length>8 ? k.slice(0,4)+'****'+k.slice(-4) : '****'; }

/* ---------- 极简 SMTP 客户端(AUTH LOGIN) ---------- */
function loadSmtp(){
  try { return JSON.parse(fs.readFileSync(path.join(__dirname,'smtp.json'),'utf8')); }
  catch(e){ return null; }
}
function sendMail(to, subject, text, cb){
  if (MOCK){ console.log('[SMTP_MOCK] to='+to+' | '+subject+' | '+text); return cb(null); }
  const cfg = loadSmtp();
  if (!cfg || !cfg.host || !cfg.user || !cfg.pass) return cb(new Error('缺少 smtp.json 配置'));
  const from = cfg.from || cfg.user;
  const fromAddr = (from.match(/<([^>]+)>/)||[,from])[1];
  const secure = cfg.secure !== false;
  const port = cfg.port || (secure ? 465 : 25);
  const b64 = s => Buffer.from(s, 'utf8').toString('base64');

  const msg = [
    'From: ' + (from.includes('<') ? from : '"noreply" <'+from+'>'),
    'To: <' + to + '>',
    'Subject: =?UTF-8?B?' + b64(subject) + '?=',
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=utf-8',
    'Date: ' + new Date().toUTCString(),
    'Message-ID: <' + crypto.randomBytes(8).toString('hex') + '@' + fromAddr.split('@')[1] + '>',
    '', text, ''
  ].join('\r\n');

  /* 对话步骤:[发送内容(null=等服务器先开口), 期望状态码前缀] */
  const steps = [
    [null, '220'],
    ['EHLO localhost', '250'],
    ['AUTH LOGIN', '334'],
    [b64(cfg.user), '334'],
    [b64(cfg.pass), '235'],
    ['MAIL FROM:<' + fromAddr + '>', '250'],
    ['RCPT TO:<' + to + '>', '250'],
    ['DATA', '354'],
    [msg + '\r\n.', '250'],
    ['QUIT', '221'],
  ];
  let i = 0, buf = '', done = false;
  function finish(err){ if(done) return; done = true; try{ sock.destroy(); }catch(e){} cb(err||null); }
  const opts = { host: cfg.host, port: port };
  const sock = secure ? tls.connect(Object.assign({ servername: cfg.host }, opts)) : net.connect(opts);
  sock.setTimeout(15000, function(){ finish(new Error('SMTP 超时')); });
  sock.on('error', finish);
  sock.on('data', function(d){
    buf += d.toString();
    /* SMTP 应答可能多行(250-xxx),等最后一行 "码+空格" */
    const lines = buf.split('\r\n').filter(Boolean);
    const last = lines[lines.length-1] || '';
    if (!/^\d{3}([ ]|$)/.test(last)) return;
    const code = last.slice(0,3);
    buf = '';
    if (!code.startsWith(steps[i][1].slice(0,1)) || !last.startsWith(steps[i][1]))
      return finish(new Error('SMTP 第'+i+'步失败: '+last.slice(0,120)));
    i++;
    if (i >= steps.length) return finish(null);
    if (steps[i][0] !== null) sock.write(steps[i][0] + '\r\n');
  });
  /* 第 0 步等服务器问候,连接后不主动发 */
}

/* ---------- 会话 ---------- */
function getSession(req){
  const sid = parseCookies(req).sid;
  if (!sid || !sessions[sid]) return null;
  const s = sessions[sid];
  if (Date.now() - s.ts > SESSION_DAYS*864e5){ delete sessions[sid]; sessDirty=true; return null; }
  return { sid: sid, email: s.email };
}
function newSession(email){
  const sid = crypto.randomBytes(24).toString('hex');
  sessions[sid] = { email: email, ts: Date.now() };
  saveJSON('sessions.json', sessions);
  return sid;
}
function cookieHeader(sid, maxAge){
  return 'sid='+sid+'; Path=/; Max-Age='+maxAge+'; HttpOnly; Secure; SameSite=Lax';
}

/* ---------- HTTP 服务 ---------- */
const server = http.createServer(function(req, res){
  const u = new URL(req.url, 'http://x');
  const p = u.pathname;

  /* nginx auth_request 探针:命中率最高,放最前 */
  if (p === '/auth/check'){
    if (getSession(req)){ res.writeHead(204); return res.end(); }
    res.writeHead(401); return res.end();
  }
  if (p === '/auth/ping'){ return json(res, 200, {ok:true}); }

  if (p === '/auth/me' && req.method === 'GET'){
    const s = getSession(req);
    if (!s) return json(res, 401, {ok:false});
    return json(res, 200, {ok:true, email:s.email, admin:isAdmin(s.email)});
  }

  if (p === '/auth/request-code' && req.method === 'POST'){
    return readBody(req, function(body){
      const email = normEmail(body && body.email);
      if (!validEmail(email)) return json(res, 400, {ok:false, message:'邮箱格式不对'});
      if (!isInvited(email))  return json(res, 403, {ok:false, message:'该邮箱不在邀请名单里,请联系管理员'});
      const rec = codes.get(email);
      if (rec && Date.now() - rec.lastSent < RESEND_GAP)
        return json(res, 429, {ok:false, message:'发送太频繁,请 1 分钟后再试'});
      const code = String(crypto.randomInt(100000, 1000000));
      codes.set(email, { code: code, exp: Date.now()+CODE_TTL, tries: 0, lastSent: Date.now() });
      sendMail(email, '登录验证码 '+code,
        '您的登录验证码是:'+code+'\r\n10 分钟内有效。如果不是您本人操作,请忽略此邮件。',
        function(err){
          if (err){ console.error('发信失败:', err.message); codes.delete(email);
            return json(res, 502, {ok:false, message:'验证码发送失败,请稍后再试'}); }
          json(res, 200, {ok:true, message:'验证码已发送,请查收邮箱(含垃圾箱)'});
        });
    });
  }

  if (p === '/auth/verify' && req.method === 'POST'){
    return readBody(req, function(body){
      const email = normEmail(body && body.email);
      const code = String(body && body.code || '').trim();
      const rec = codes.get(email);
      if (!rec || Date.now() > rec.exp) return json(res, 400, {ok:false, message:'验证码已过期,请重新获取'});
      if (rec.tries >= MAX_TRIES){ codes.delete(email); return json(res, 429, {ok:false, message:'错误次数过多,请重新获取验证码'}); }
      if (rec.code !== code){ rec.tries++; return json(res, 400, {ok:false, message:'验证码不对'}); }
      codes.delete(email);
      if (!isInvited(email)) return json(res, 403, {ok:false, message:'该邮箱已被移出邀请名单'});
      const sid = newSession(email);
      return json(res, 200, {ok:true, email:email, admin:isAdmin(email)},
        {'set-cookie': cookieHeader(sid, SESSION_DAYS*86400)});
    });
  }

  if (p === '/auth/logout' && req.method === 'POST'){
    const s = getSession(req);
    if (s){ delete sessions[s.sid]; saveJSON('sessions.json', sessions); }
    return json(res, 200, {ok:true}, {'set-cookie': cookieHeader('x', 0)});
  }

  /* ---- 云端数据:登录用户读快照,管理员刷新 ---- */
  if (p === '/auth/data/snapshot' && req.method === 'GET'){
    const s = getSession(req);
    if (!s) return json(res, 401, {ok:false, message:'未登录'});
    const snap = loadJSON('snapshot.json', null);
    if (!snap) return json(res, 404, {ok:false, message:'还没有数据,请等管理员拉取'});
    return json(res, 200, snap);
  }
  if (p === '/auth/data/refresh' && req.method === 'POST'){
    const s = getSession(req);
    if (!s) return json(res, 401, {ok:false, message:'未登录'});
    if (!isAdmin(s.email)) return json(res, 403, {ok:false, message:'只有管理员能拉取数据'});
    return readBody(req, function(body){
      let leagues = body && Array.isArray(body.leagues) ? body.leagues : null;
      if (!leagues || !leagues.length){
        const st = loadJSON('settings.json', null);
        leagues = (st && st.leagues) || ['soccer_fifa_world_cup'];
      }
      saveJSON('settings.json', {leagues: leagues});
      refreshSnapshot(leagues, s.email, function(err, snap){
        if (err) return json(res, 502, {ok:false, message:'拉取失败:'+err.message});
        json(res, 200, snap);
      });
    });
  }

  /* ---- 管理员接口 ---- */
  if (p.startsWith('/auth/admin/')){
    const s = getSession(req);
    if (!s) return json(res, 401, {ok:false, message:'未登录'});
    if (!isAdmin(s.email)) return json(res, 403, {ok:false, message:'需要管理员权限'});

    if (p === '/auth/admin/list' && req.method === 'GET')
      return json(res, 200, {ok:true, admins: wl.admins, users: wl.users});

    /* key 池管理 */
    /* 定时拉取配置 */
    if (p === '/auth/admin/schedule' && req.method === 'GET'){
      const st = loadJSON('settings.json', {}) || {};
      const snap = loadJSON('snapshot.json', null);
      const a = st.auto || {};
      return json(res, 200, {ok:true,
        enabled: !!a.enabled, mode: a.mode==='times'?'times':'interval',
        hours: a.hours || 6, times: a.times || [],
        leagues: st.leagues || [],
        lastTs: snap ? snap.ts : null, lastBy: snap ? snap.by : null});
    }
    if (p === '/auth/admin/schedule' && req.method === 'POST'){
      return readBody(req, function(body){
        const st = loadJSON('settings.json', {}) || {};
        const hours = Math.min(48, Math.max(1, +(body && body.hours) || 6));
        const mode = (body && body.mode === 'times') ? 'times' : 'interval';
        let times = (body && Array.isArray(body.times)) ? body.times : [];
        times = times.map(function(s){ return String(s).trim(); })
          .filter(function(s){ return /^([01]?\d|2[0-3]):[0-5]\d$/.test(s); });
        times = Array.from(new Set(times)).sort().slice(0,6);
        if (mode==='times' && (body&&body.enabled) && !times.length)
          return json(res, 400, {ok:false, message:'定点模式至少要填一个有效时间(如 10:00)'});
        st.auto = { enabled: !!(body && body.enabled), mode: mode, hours: hours, times: times };
        saveJSON('settings.json', st);
        json(res, 200, {ok:true, message: !st.auto.enabled ? '已关闭自动拉取'
          : (mode==='times' ? ('已开启:每天北京时间 '+times.join('、')+' 自动拉取')
                            : ('已开启:每 '+hours+' 小时自动拉取一次'))});
      });
    }

    if (p === '/auth/admin/keys' && req.method === 'GET'){
      const ks = loadKeys();
      return json(res, 200, {ok:true, keys: ks.map(function(k,i){ return {i:i, masked:maskKey(k)}; })});
    }
    if (p === '/auth/admin/keys/add' && req.method === 'POST'){
      return readBody(req, function(body){
        const k = String(body && body.key || '').trim();
        if (!/^[a-z0-9]{16,64}$/i.test(k)) return json(res, 400, {ok:false, message:'key 格式不对'});
        const ks = loadKeys();
        if (ks.includes(k)) return json(res, 200, {ok:true, message:'已存在'});
        ks.push(k); saveKeys(ks);
        return json(res, 200, {ok:true, message:'已添加(共 '+ks.length+' 个)'});
      });
    }
    if (p === '/auth/admin/keys/remove' && req.method === 'POST'){
      return readBody(req, function(body){
        const i = body && body.i;
        const ks = loadKeys();
        if (typeof i !== 'number' || i<0 || i>=ks.length) return json(res, 400, {ok:false, message:'序号不对'});
        if (ks.length === 1) return json(res, 400, {ok:false, message:'至少保留 1 个 key'});
        ks.splice(i,1); saveKeys(ks);
        return json(res, 200, {ok:true, message:'已移除'});
      });
    }

    if (p === '/auth/admin/invite' && req.method === 'POST'){
      return readBody(req, function(body){
        const email = normEmail(body && body.email);
        if (!validEmail(email)) return json(res, 400, {ok:false, message:'邮箱格式不对'});
        if (isInvited(email)) return json(res, 200, {ok:true, message:'已在名单里'});
        wl.users.push(email); saveJSON('whitelist.json', wl);
        return json(res, 200, {ok:true, message:'已邀请 '+email});
      });
    }
    if (p === '/auth/admin/remove' && req.method === 'POST'){
      return readBody(req, function(body){
        const email = normEmail(body && body.email);
        if (wl.admins.includes(email)) return json(res, 400, {ok:false, message:'不能移除管理员'});
        const n = wl.users.length;
        wl.users = wl.users.filter(function(e){ return e !== email; });
        if (wl.users.length !== n){
          saveJSON('whitelist.json', wl);
          /* 顺手踢掉该邮箱的会话 */
          for (const t in sessions) if (sessions[t].email === email) delete sessions[t];
          saveJSON('sessions.json', sessions);
        }
        return json(res, 200, {ok:true, message:'已移除 '+email});
      });
    }
    return json(res, 404, {ok:false});
  }

  json(res, 404, {ok:false, message:'not found'});
});

server.listen(PORT, '127.0.0.1', function(){
  console.log('auth_server 监听 127.0.0.1:'+PORT
    +'  数据目录 '+DATA_DIR
    +(MOCK ? '  [SMTP_MOCK 模式,验证码打日志]' : '')
    +'  管理员: '+wl.admins.join(','));
});
