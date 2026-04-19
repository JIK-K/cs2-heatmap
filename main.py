import os
import uuid
import gc
import polars as pl
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from awpy import Demo

app = FastAPI(title="CS2 Tactical Analytics")
app.mount("/static", StaticFiles(directory="data/static"), name="static")
templates = Jinja2Templates(directory="templates")

MAP_DATA = {
    "de_mirage":  {"x": -3230, "y": 1713, "scale": 5.0},
    "de_inferno": {"x": -2087, "y": 3870, "scale": 4.9},
    "de_overpass":{"x": -4831, "y": 1781, "scale": 5.2},
    "de_nuke":    {"x": -3453, "y": 2887, "scale": 7.0},
    "de_vertigo": {"x": -3168, "y": 1762, "scale": 4.0},
    "de_ancient": {"x": -2953, "y": 2164, "scale": 5.0},
    "de_anubis":  {"x": -2796, "y": 3328, "scale": 5.22},
    "de_dust2":   {"x": -2476, "y": 3239, "scale": 4.4},
}

def game_to_pct(x, y, map_name):
    if map_name not in MAP_DATA: return None, None
    m = MAP_DATA[map_name]
    # JS KDE 계산식(px * GRID)과 맞추기 위해 0~1 범위로 반환
    px = (x - m["x"]) / (m["scale"] * 1024)
    py = (m["y"] - y) / (m["scale"] * 1024)
    return round(px, 4), round(py, 4)

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/map-image/{map_name}")
async def get_map_image(map_name: str):
    path1 = f"data/maps/{map_name}.png"
    path2 = os.path.expanduser(f"~/.awpy/maps/{map_name}.png")
    
    if os.path.exists(path1): return FileResponse(path1)
    if os.path.exists(path2): return FileResponse(path2)
    
    return JSONResponse({"error": "Map not found"}, status_code=404)

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    tmp = f"temp_{uuid.uuid4()}.dem"
    try:
        with open(tmp, "wb") as f:
            f.write(await file.read())
        
        dem = Demo(tmp)
        dem.parse()
        header = dem.header if hasattr(dem, "header") else {}
        map_name = header.get("map_name", "unknown")
        
        # awpy 속성을 통해 데이터 추출
        kills_df = dem.kills if hasattr(dem, "kills") and dem.kills is not None else pl.DataFrame()
        damage_df = dem.damages if hasattr(dem, "damages") and dem.damages is not None else pl.DataFrame()
        rounds_df = dem.rounds if hasattr(dem, "rounds") and dem.rounds is not None else pl.DataFrame()
        
        # 1. 기본 통계 (컬럼명 headshot으로 수정)
        total_kills = len(kills_df) if not kills_df.is_empty() else 0
        total_rounds = int(rounds_df["round_num"].max()) if not rounds_df.is_empty() and "round_num" in rounds_df.columns else 1
        
        hs_col = "headshot" if "headshot" in kills_df.columns else ("is_headshot" if "is_headshot" in kills_df.columns else None)
        hs_count = kills_df[hs_col].sum() if hs_col else 0
        hs_rate = round((hs_count / total_kills * 100), 1) if total_kills > 0 else 0
        
        damage_col = "dmg_health" if "dmg_health" in damage_df.columns else ("damage" if "damage" in damage_df.columns else None)
        total_damage = int(damage_df[damage_col].sum()) if not damage_df.is_empty() and damage_col else 0
        
        # 2. 팀 식별 (파일명 기반 기본값)
        fname = file.filename.lower().replace(".dem", "")
        for g in ["-m1", "-m2", "-m3", "-mirage", "-dust2", "-inferno"]: fname = fname.replace(g, "")
        parts = [p.strip().upper() for p in fname.split("-vs-")] if "vs" in fname else ["TEAM A", "TEAM B"]
        team_a_name, team_b_name = (parts[0], parts[1]) if len(parts) >= 2 else ("TEAM A", "TEAM B")
        
        # 팀 소속 선수 보완 (awpy 내장 파서 또는 kills 활용)
        team_members = {"ct": set(), "t": set()}
        try:
            # 안전한 시간대의 틱 여러 개를 추출하여 팀 번호 확보 (CT: 3, T: 2)
            ticks = dem.parser.parse_ticks(["m_iTeamNum"], ticks=[5000, 10000, 15000, 20000])
            for row in ticks.iter_rows(named=True):
                sid, tid = str(row.get("steamid", "")), row.get("m_iTeamNum")
                if sid and sid != "0":
                    if tid == 3: team_members["ct"].add(sid)
                    elif tid == 2: team_members["t"].add(sid)
        except Exception:
            pass

        # 3. 스코어 계산 (팀 진영 매칭 정교화)
        score_a, score_b = 0, 0
        team_a_start_side = "ct"
        
        try:
            # 1라운드 선수 명단 추출
            r1_players = dem.ticks.filter(pl.col("round_num") == 1).select(["name", "side"]).unique()
            r1_names_upper = [str(n).upper() for n in r1_players["name"].to_list()]
            
            # 파일명에서 추출한 팀 이름(team_a_name)이 1라운드 선수 이름이나 클랜에 포함되는지 확인
            # (보통 프로팀명은 파일명에 있고, 선수 이름에는 없더라도 검색 가능성 있음)
            # 여기서는 파일명의 첫 번째 팀(Team A)이 1라운드 CT 선수들과 연관있는지 확인
            ct_players = r1_players.filter(pl.col("side").str.to_lowercase() == "ct")["name"].to_list()
            ct_names_combined = " ".join([str(n) for n in ct_players]).upper()
            
            # 단순 매칭: 파일명 첫 팀 이름이 CT 선수 명단 문자열에 포함되거나 그 반대인 경우
            if team_a_name.upper() in ct_names_combined:
                team_a_start_side = "ct"
            else:
                team_a_start_side = "t"
                
            print(f"DEBUG: Team A ({team_a_name}) identified as starting on {team_a_start_side}")
        except Exception as e:
            print(f"DEBUG: Team identification failed: {e}")

        if not rounds_df.is_empty():
            halftime = 12 if total_rounds <= 24 else 15
            for r in rounds_df.sort("round_num").iter_rows(named=True):
                r_num = r.get("round_num", 0)
                winner_side = str(r.get("winner", "")).lower()
                
                # 라운드별 Team A의 사이드 계산
                if r_num <= halftime:
                    current_a_side = team_a_start_side
                else:
                    # 13라운드부터 진영 교체 (CS2 MR12 기준)
                    current_a_side = "t" if team_a_start_side == "ct" else "ct"
                
                if winner_side in current_a_side:
                    score_a += 1
                else:
                    score_b += 1

        # 4. 플레이어 통계
        players = []
        if not kills_df.is_empty():
            k_agg = kills_df.group_by("attacker_steamid").agg(pl.len().alias("kills"))
            d_agg = kills_df.group_by("victim_steamid").agg(pl.len().alias("deaths"))
            a_agg = kills_df.group_by("assister_steamid").agg(pl.len().alias("assists")) if "assister_steamid" in kills_df.columns else pl.DataFrame({"assister_steamid": [], "assists": []})
            dmg_agg = damage_df.group_by("attacker_steamid").agg(pl.sum("dmg_health").alias("dmg")) if not damage_df.is_empty() else pl.DataFrame({"attacker_steamid": [], "dmg": []})
            
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
            
            if "attacker_team_name" in kills_df.columns:
                team_names_df = kills_df.select(["attacker_steamid", "attacker_team_name"]).drop_nulls().unique("attacker_steamid")
                combined = combined.join(team_names_df, left_on="sid", right_on="attacker_steamid", how="left")
            
            for p in combined.iter_rows(named=True):
                sid = str(p["sid"])
                tname = p.get("attacker_team_name")
                if not tname:
                    if sid in team_members["ct"]: tname = "CT Team"
                    elif sid in team_members["t"]: tname = "T Team"
                    else: tname = "Unknown Team"
                    
                players.append({
                    "name": p.get("attacker_name") or "Unknown",
                    "steamid": sid,
                    "team_name": str(tname),
                    "kills": int(p.get("kills", 0)),
                    "deaths": int(p.get("deaths", 0)),
                    "assists": int(p.get("assists", 0)),
                    "adr": round(p.get("dmg", 0) / total_rounds, 1),
                    "rating": round(1.0 + (int(p.get("kills", 0)) - int(p.get("deaths", 0))) * 0.02, 2),
                    "impact": 0
                })

        # 5. 히트맵 포인트 추출 (awpy 공식 프로퍼티 사용)
        map_name_clean = map_name.lower().strip()
        def get_points(df, x_cols, y_cols):
            if df is None or df.is_empty(): return []
            xc = next((c for c in x_cols if c in df.columns), None)
            yc = next((c for c in y_cols if c in df.columns), None)
            if not xc or not yc: return []
            
            # 유효한 좌표만 추출하여 percentage로 변환
            results = []
            for row in df.select([xc, yc]).drop_nulls().iter_rows(named=True):
                px, py = game_to_pct(row[xc], row[yc], map_name_clean)
                if px is not None:
                    results.append((px, py))
            return results

        # 공식 프로퍼티에서 직접 데이터 참조
        kills_df_coords = dem.kills
        shots_df = dem.shots
        smokes_df = dem.smokes
        
        # flashes와 he는 dem.events 딕셔너리에서 직접 추출
        flashes_df = dem.events.get("flashbang_detonate", pl.DataFrame())
        he_df = dem.events.get("hegrenade_detonate", pl.DataFrame())

        points = {
            "kills":  get_points(kills_df_coords, ["attacker_X", "attacker_x", "x", "X"], ["attacker_Y", "attacker_y", "y", "Y"]),
            "deaths": get_points(kills_df_coords, ["victim_X", "victim_x", "x", "X"], ["victim_Y", "victim_y", "y", "Y"]),
            "shots":  get_points(shots_df, ["player_X", "player_x", "user_X", "user_x", "x", "X"], ["player_Y", "player_y", "user_Y", "user_y", "y", "Y"])[:1000],
            "smokes": get_points(smokes_df, ["X", "x", "user_x", "user_X"], ["Y", "y", "user_y", "user_Y"]),
            "flashes": get_points(flashes_df, ["X", "x", "user_x", "user_X"], ["Y", "y", "user_y", "user_Y"]),
            "he": get_points(he_df, ["X", "x", "user_x", "user_X"], ["Y", "y", "user_y", "user_Y"]),
        }

        # 6. 무기 통계 집계
        weapons = []
        weapon_col = "weapon" if "weapon" in kills_df.columns else ("weapon_name" if "weapon_name" in kills_df.columns else None)
        if not kills_df.is_empty() and weapon_col:
            w_agg = kills_df.group_by(weapon_col).agg(pl.len().alias("kills")).sort("kills", descending=True)
            for row in w_agg.iter_rows(named=True):
                weapons.append({"weapon": str(row[weapon_col]), "kills": row["kills"]})

        return JSONResponse({
            "map_name": map_name,
            "total_kills": total_kills,
            "total_rounds": total_rounds,
            "hs_rate": hs_rate,
            "total_damage": total_damage,
            "players": sorted(players, key=lambda x: x["kills"], reverse=True),
            "round_stats": {"team_a": team_a_name, "score_a": score_a, "team_b": team_b_name, "score_b": score_b},
            "points": points,
            "weapons": weapons,
            "has_map_data": map_name in MAP_DATA
        })

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        try:
            if 'dem' in locals():
                del dem
            import gc
            gc.collect()
            if os.path.exists(tmp): os.remove(tmp)
        except Exception as e:
            print(f"Failed to delete {tmp}: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
