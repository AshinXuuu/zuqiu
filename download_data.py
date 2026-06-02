"""
download_data.py — 在你自己的电脑上运行(联网),批量拉取 football-data.co.uk 历史数据。
Cowork 沙盒只放行 PyPI、无法直连该站,所以下载这一步交给本机。

用法:
    python download_data.py                # 默认拉 5 大联赛近 6 季
    python download_data.py --leagues E0 D1 --seasons 2223 2324 2425
    python download_data.py --out data     # 指定输出目录

拉完后,把 data/ 目录(整份)交给 Cowork,模型与回测脚本会自动读取。

输出:每个 联赛-赛季 一个 CSV(原始全列),外加一个合并清洗后的 matches_clean.csv,
     只保留建模需要的列 + 统一字段名(开盘/收盘 Pinnacle 的 1X2、大小球2.5、亚盘)。
"""
import argparse, os, sys, csv, io, urllib.request

BASE = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"

# 常用联赛代码(football-data.co.uk)
LEAGUES_DEFAULT = ["E0", "D1", "I1", "SP1", "F1"]   # 英超 德甲 意甲 西甲 法甲
# 近 6 季;赛季写法:2425 = 2024-25
SEASONS_DEFAULT = ["1920", "2021", "2122", "2223", "2324", "2425"]

# 我们建模/回测需要的列(开盘 Pinnacle = PSH..; 收盘 = PSCH..; 亚盘主盘口 AHh / AHCh)
WANT = {
    "Date": "Date", "HomeTeam": "HomeTeam", "AwayTeam": "AwayTeam",
    "FTHG": "FTHG", "FTAG": "FTAG",
    # 开盘 Pinnacle 1X2 + 大小球2.5
    "PSH": "PSH", "PSD": "PSD", "PSA": "PSA",
    "P>2.5": "PO", "P<2.5": "PU",
    # 收盘 Pinnacle 1X2 + 大小球2.5
    "PSCH": "PSCH", "PSCD": "PSCD", "PSCA": "PSCA",
    "PC>2.5": "PCO", "PC<2.5": "PCU",
    # 亚盘(主盘口让球线 + 开盘/收盘 Pinnacle 亚盘赔率)
    "AHh": "AHh", "PAHH": "PAHH", "PAHA": "PAHA",
    "AHCh": "AHCh", "PCAHH": "PCAHH", "PCAHA": "PCAHA",
}
OUT_COLS = ["League", "Season", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG",
            "PSH", "PSD", "PSA", "PO", "PU", "PSCH", "PSCD", "PSCA", "PCO", "PCU",
            "AHh", "PAHH", "PAHA", "AHCh", "PCAHH", "PCAHA"]


def _ssl_ctx():
    """优先用 certifi 的根证书;没有就退回不校验(只为下公开 CSV,无安全风险)。"""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
        raw = r.read()
    # 该站常用 latin-1/cp1252
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", nargs="+", default=LEAGUES_DEFAULT)
    ap.add_argument("--seasons", nargs="+", default=SEASONS_DEFAULT)
    ap.add_argument("--out", default="data")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    merged = []
    for season in args.seasons:
        for league in args.leagues:
            url = BASE.format(season=season, league=league)
            try:
                txt = fetch(url)
            except Exception as e:
                print(f"[skip] {league} {season}: {e}")
                continue
            rows = list(csv.DictReader(io.StringIO(txt)))
            if not rows:
                print(f"[empty] {league} {season}")
                continue
            # 原始全列存档
            with open(os.path.join(args.out, f"{league}_{season}.csv"), "w",
                      newline="", encoding="utf-8") as f:
                f.write(txt)
            kept = 0
            for row in rows:
                if not row.get("FTHG") or not row.get("PSCH"):
                    continue  # 缺赛果或缺收盘赔率的跳过
                rec = {"League": league, "Season": season}
                ok = True
                for src, dst in WANT.items():
                    if src in ("Date", "HomeTeam", "AwayTeam"):
                        rec[dst] = (row.get(src) or "").strip()
                    else:
                        v = (row.get(src) or "").strip()
                        rec[dst] = v
                merged.append(rec)
                kept += 1
            print(f"[ok]   {league} {season}: {kept} matches")

    if merged:
        path = os.path.join(args.out, "matches_clean.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=OUT_COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(merged)
        print(f"\n合并清洗完成: {len(merged)} 场 -> {path}")
        print("把整个 data/ 目录交给 Cowork,运行 backtest_value.py 即可。")
    else:
        print("没拉到任何数据,检查联赛/赛季代码或网络。")


if __name__ == "__main__":
    main()
