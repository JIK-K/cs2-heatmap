import os
import uuid
import polars as pl
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from demoparser2 import DemoParser

app = FastAPI(title="CS2 Tactical Analytics")
app.mount("/static", StaticFiles(directory="data/static"), name="static")
templates = Jinja2Templates(directory="templates")

MAP_DATA = {
    "de_mirage":  {"x": -3230, "y": 1713, "scale": 5.0},
    "de_inferno": {"x": -2087, "y": 3870, "scale": 4.9},
    "de_overpass":{"x": -4831, "y": 1781, "scale": 5.2},
    "de_nuke":    {"x": -3450, "y": 2887, "scale": 7.0},
    "de_vertigo": {"x": -3120, "y": 1720, "scale": 4.0},
    "de_ancient": {"x": -2950, "y": 2150, "scale": 5.0},
    "de_anubis":  {"x": -2796, "y": 3328, "scale": 5.22},
    "de_dust2":   {"x": -2476, "y": 3239, "scale": 4.4},
}

def game_to_pct(x, y, map_name):
    if map_name not in MAP_DATA: return None, None
    m = MAP_DATA[map_name]
    px = (x - m["x"]) / (m["scale"] * 10.24)
    py = (m["y"] - y) / (m["scale"] * 10.24)
    return round(px, 1), round(py, 1)

def safe_parse_events(parser, event_names):
    """사용자 환경에 따라 단일 문자열 또는 리스트 인자를 처리하고 DataFrame을 반환"""
    try:
        res = parser.parse_events(event_names)
        if isinstance(res, list) and len(res) > 0: return res[0]
        return res
    except TypeError:
        # 리스트 인자가 필요한 경우 처리
        res = parser.parse_events([event_names] if isinstance(event_names, str) else event_names)
        if isinstance(res, list) and len(res) > 0: return res[0]
        return res

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/map-image/{map_name}")
async def get_map_image(map_name: str):
    path = f"data/maps/{map_name}.png"
    if os.path.exists(path): return FileResponse(path)
    return JSONResponse({"error": "Map not found"}, status_code=404)

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    tmp = f"temp_{uuid.uuid4()}.dem"
    try:
        with open(tmp, "wb") as f:
            f.write(await file.read())
        
        parser = DemoParser(tmp)
        header = parser.parse_header()
        map_name = header.get("map_name", "unknown")
        
        # 데이터 추출
        kills_df = safe_parse_events(parser, "player_death")
        damage_df = safe_parse_events(parser, "player_hurt")
        rounds_df = safe_parse_events(parser, "round_end")
        
        # 1. 기본 통계
        total_kills = len(kills_df) if not kills_df.is_empty() else 0
        total_rounds = int(rounds_df["round_num"].max()) if not rounds_df.is_empty() else 1
        hs_rate = round((kills_df["is_headshot"].sum() / total_kills * 100), 1) if total_kills > 0 else 0
        total_damage = int(damage_df["dmg_health"].sum()) if not damage_df.is_empty() else 0
        
        # 2. 팀 식별 (파일명 기반)
        fname = file.filename.lower().replace(".dem", "")
        for g in ["-m1", "-m2", "-m3", "-mirage", "-dust2", "-inferno"]: fname = fname.replace(g, "")
        parts = [p.strip().upper() for p in fname.split("-vs-")] if "vs" in fname else ["TEAM A", "TEAM B"]
        team_a_name, team_b_name = (parts[0], parts[1]) if len(parts) >= 2 else ("TEAM A", "TEAM B")
        
        # 팀 소속 선수 (Round 1 틱 데이터로 식별)
        team_members = {"ct": set(), "t": set()}
        ticks = parser.parse_ticks(["m_iTeamNum"], ticks=[2000, 5000])
        for row in ticks.iter_rows(named=True):
            sid, tid = str(row.get("steamid", "")), row.get("m_iTeamNum")
            if sid and sid != "0":
                if tid == 3: team_members["ct"].add(sid)
                elif tid == 2: team_members["t"].add(sid)

        # 3. 스코어 계산 (하프타임 스왑 대응)
        score_a, score_b = 0, 0
        if not rounds_df.is_empty():
            halftime = 12 if total_rounds <= 24 else 15
            for r in rounds_df.sort("round_num").iter_rows(named=True):
                r_num = r.get("round_num", 0)
                winner = str(r.get("winner", "")).lower()
                is_ct_win = "ct" in winner or "3" in winner
                # 전반전: Team A(CT), Team B(T) / 후반전: Team A(T), Team B(CT)
                a_current_side = "ct" if r_num <= halftime else "t"
                if (a_current_side == "ct" and is_ct_win) or (a_current_side == "t" and not is_ct_win):
                    score_a += 1
                else:
                    score_b += 1

        # 4. 플레이어 통계 집계
        players = []
        if not kills_df.is_empty():
            k_agg = kills_df.group_by("attacker_steamid").agg(pl.count().alias("kills"))
            d_agg = kills_df.group_by("victim_steamid").agg(pl.count().alias("deaths"))
            a_agg = kills_df.group_by("assister_steamid").agg(pl.count().alias("assists"))
            dmg_agg = damage_df.group_by("attacker_steamid").agg(pl.sum("dmg_health").alias("dmg"))
            
            all_sids = pl.concat([
                k_agg.select(pl.col("attacker_steamid").alias("sid")),
                d_agg.select(pl.col("victim_steamid").alias("sid"))
            ]).unique().drop_nulls()
            
            combined = all_sids.join(k_agg, left_on="sid", right_on="attacker_steamid", how="left") \
                              .join(d_agg, left_on="sid", right_on="victim_steamid", how="left") \
                              .join(a_agg, left_on="sid", right_on="assister_steamid", how="left") \
                              .join(dmg_agg, left_on="sid", right_on="attacker_steamid", how="left") \
                              .fill_null(0)
            
            names = kills_df.select(["attacker_steamid", "attacker_name"]).unique("attacker_steamid")
            combined = combined.join(names, left_on="sid", right_on="attacker_steamid", how="left")
            
            for p in combined.iter_rows(named=True):
                sid = str(p["sid"])
                # 시작 시 진영 기준으로 팀 할당
                tname = team_a_name if sid in team_members["ct"] else team_b_name
                players.append({
                    "name": p.get("attacker_name") or "Unknown",
                    "steamid": sid,
                    "team_name": tname,
                    "kills": int(p.get("kills", 0)),
                    "deaths": int(p.get("deaths", 0)),
                    "assists": int(p.get("assists", 0)),
                    "adr": round(p.get("dmg", 0) / total_rounds, 1),
                    "rating": round(1.0 + (int(p.get("kills", 0)) - int(p.get("deaths", 0))) * 0.02, 2), # 단순화된 레이팅
                    "impact": 0
                })

        # 5. 히트맵 포인트
        def get_points(df, x_col, y_col):
            if df is None or df.is_empty() or x_col not in df.columns: return []
            return [game_to_pct(row[x_col], row[y_col], map_name) for row in df.select([x_col, y_col]).drop_nulls().iter_rows() if game_to_pct(row[x_col], row[y_col], map_name)[0] is not None]

        points = {
            "kills":  get_points(kills_df, "attacker_X", "attacker_Y"),
            "deaths": get_points(kills_df, "victim_X", "victim_Y"),
            "shots":  get_points(safe_parse_events(parser, "weapon_fire"), "attacker_X", "attacker_Y")[:1000],
            "smokes": get_points(safe_parse_events(parser, "smokegrenade_detonate"), "x", "y"),
            "flashes": get_points(safe_parse_events(parser, "flashbang_detonate"), "x", "y"),
            "he": get_points(safe_parse_events(parser, "hegrenade_detonate"), "x", "y"),
        }

        return JSONResponse({
            "map_name": map_name,
            "total_kills": total_kills,
            "total_rounds": total_rounds,
            "hs_rate": hs_rate,
            "total_damage": total_damage,
            "players": sorted(players, key=lambda x: x["kills"], reverse=True),
            "round_stats": {"team_a": team_a_name, "score_a": score_a, "team_b": team_b_name, "score_b": score_b},
            "points": points,
            "has_map_data": map_name in MAP_DATA
        })

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        if os.path.exists(tmp): os.remove(tmp)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
