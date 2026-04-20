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

TEMP_DIR = "data/temp"
os.makedirs(TEMP_DIR, exist_ok=True)

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
    unique_id = uuid.uuid4()
    tmp = os.path.join(TEMP_DIR, f"temp_{unique_id}.dem")
    try:
        import gc
        import time
        from awpy import Demo
        with open(tmp, "wb") as f:
            f.write(await file.read())
        
        # Initialize and Parse using awpy 2.0
        dem = Demo(tmp)
        dem.parse() # CRITICAL: Must call parse() to populate data

        # --- RAW DEMOPARSER2 DEBUG LOG ---
        print("DEBUG: === RAW DEMOPARSER2 DATA CHECK (RE-FIXED) ===")
        try:
            from demoparser2 import DemoParser
            raw_parser = DemoParser(tmp)
            
            print(f"DEBUG: Raw Header: {raw_parser.parse_header()}")
            
            # 1. Check Game State fields in ticks
            # team_name = m_szTeamname, team_clan_name = m_szClanTeamname
            game_state_fields = ["team_name", "team_clan_name", "team_rounds_total", "total_rounds_played", "round_win_reason"]
            try:
                # We check more ticks and use len() to avoid is_empty error
                team_ticks = raw_parser.parse_ticks(game_state_fields, ticks=[500, 5000, 15000, 25000])
                if team_ticks is not None and len(team_ticks) > 0:
                    print(f"DEBUG: Raw Team/Game State Ticks Content:\n{team_ticks}")
                else:
                    print("DEBUG: Game state fields returned no data.")
            except Exception as e:
                print(f"DEBUG: Failed to parse game state ticks: {e}")

            # 2. Check Event with 'other' fields
            try:
                # Query round_end which is most likely to have team/score info
                round_ends = raw_parser.parse_event("round_end", other=["team_name", "team_clan_name", "total_rounds_played", "round_win_reason"])
                if round_ends is not None and len(round_ends) > 0:
                    print(f"DEBUG: Round End Raw Events (Team Info):\n{round_ends}")
                else:
                    print("DEBUG: round_end event returned no data.")
            except Exception as e:
                print(f"DEBUG: Failed to parse round_end with other fields: {e}")

        except Exception as re:
            print(f"DEBUG: Raw demoparser2 check failed: {re}")
        print("DEBUG: ====================================")
        
        # 1. Header & Map Info
        header = dem.header
        map_name = header.get("map_name", "unknown")
        map_name_clean = map_name.lower().strip()
        print(f"DEBUG: Map identified as: {map_name} (Clean: {map_name_clean})")
        
        # 2. Extract DataFrames
        rounds_df = dem.rounds
        kills_df = dem.kills
        damage_df = dem.damages
        
        # 1. Team & Score Extraction using demoparser2
        try:
            from demoparser2 import DemoParser
            raw_parser = DemoParser(tmp)
            # Map rounds to teams
            round_data = raw_parser.parse_event("round_end", other=["team_name", "team_clan_name", "total_rounds_played"])
            
            # Build a map of round_num -> { "T": clan, "CT": clan, "winner_side": T/CT }
            round_team_map = {}
            team_a_name, team_b_name = "Team A", "Team B"
            
            if round_data is not None and len(round_data) > 0:
                # Convert to list of dicts compatibly for both Polars and Pandas
                if hasattr(round_data, "iter_rows"): # Polars
                    rows = [dict(zip(round_data.columns, row)) for row in round_data.iter_rows()]
                elif hasattr(round_data, "to_dict"): # Pandas
                    rows = round_data.to_dict('records')
                else:
                    rows = []

                for row in rows:
                    # total_rounds_played is usually the most reliable match for round_num
                    rn = row.get("total_rounds_played")
                    if rn is None:
                        rn = row.get("round", 0)
                    
                    winner = str(row.get("winner", "")).upper()
                    t_clan = row.get("t_team_clan_name") or row.get("t_team_name") or "T"
                    ct_clan = row.get("ct_team_clan_name") or row.get("ct_team_name") or "CT"
                    
                    round_team_map[rn] = {"T": t_clan, "CT": ct_clan, "winner_side": winner}
                    
                    if not team_a_name or team_a_name == "Team A":
                        team_a_name, team_b_name = t_clan, ct_clan

                print(f"DEBUG: Round Team Map (First 3): {dict(list(round_team_map.items())[:3])}...")
                print(f"DEBUG: Round Team Map (Total): {len(round_team_map)} rounds")

            # Calculate actual scores
            team_scores = {team_a_name: 0, team_b_name: 0}
            for rn, data in round_team_map.items():
                w_side = data["winner_side"]
                w_team = data.get(w_side)
                if w_team:
                    team_scores[w_team] = team_scores.get(w_team, 0) + 1
            
            print(f"DEBUG: Final Calculated Team Scores: {team_scores}")

        except Exception as e:
            print(f"DEBUG: Advanced Score calculation failed: {e}")
            team_scores = {"CT": 0, "T": 0}
            team_a_name, team_b_name = "CT", "T"

        total_rounds = len(rounds_df)

        # 4. Player Statistics
        player_stats = {}
        # Pre-build player-to-team map
        player_team_map = {}
        if not kills_df.is_empty():
            for k in kills_df.iter_rows(named=True):
                sid = str(k.get("attacker_steamid"))
                rn = k.get("round_num")
                side = str(k.get("attacker_side", "")).upper()
                if sid and sid not in player_team_map:
                    # Try current round, or fallback to any round this player was in
                    team_name = "Unknown"
                    if rn in round_team_map:
                        team_name = round_team_map[rn].get(side, side)
                    elif (rn - 1) in round_team_map: # Try offset
                        team_name = round_team_map[rn-1].get(side, side)
                    
                    if team_name != "Unknown":
                        player_team_map[sid] = team_name
            
            print(f"DEBUG: Player Team Mapping complete. Players mapped: {len(player_team_map)}")

        def get_p(sid, name):
            sid = str(sid)
            return player_stats.setdefault(sid, {
                "name": name or "Unknown", 
                "steamid": sid, 
                "kills": 0, "deaths": 0, "assists": 0, "damage": 0, 
                "team": player_team_map.get(sid, "Unknown")
            })

        if not kills_df.is_empty():
            for k in kills_df.iter_rows(named=True):
                a_sid, v_sid, as_sid = k.get("attacker_steamid"), k.get("victim_steamid"), k.get("assister_steamid")
                if a_sid:
                    p = get_p(a_sid, k.get("attacker_name"))
                    p["kills"] += 1
                if v_sid:
                    p = get_p(v_sid, k.get("victim_name"))
                    p["deaths"] += 1
                if as_sid:
                    p = get_p(as_sid, k.get("assister_name"))
                    p["assists"] += 1

        if not damage_df.is_empty():
            for d in damage_df.iter_rows(named=True):
                a_sid = d.get("attacker_steamid")
                if a_sid:
                    p = get_p(a_sid, d.get("attacker_name"))
                    p["damage"] += d.get("dmg_health", 0)

        players_list = []
        for sid, s in player_stats.items():
            if sid == "0" or not sid or s["name"] == "Unknown": continue
            players_list.append({
                "name": s["name"], "steamid": sid, "team_name": s["team"],
                "kills": s["kills"], "deaths": s["deaths"], "assists": s["assists"],
                "adr": round(s["damage"] / max(1, total_rounds), 1),
                "rating": round(1.0 + (s["kills"] - s["deaths"]) * 0.02 + (s["damage"] / max(1, total_rounds) / 100) * 0.1, 2),
                "impact": round((s["kills"] * 0.8 + s["assists"] * 0.2) / max(1, total_rounds), 2)
            })
        
        # 5. Heatmap Points
        def get_pts(df, x_col, y_col, filter_col=None, filter_val=None):
            if df is None or df.is_empty(): return []
            
            # Robust column detection
            actual_x, actual_y = None, None
            for col in df.columns:
                if col.lower() in [x_col.lower(), "x", "player_x", "attacker_x", "thrower_x"]: actual_x = col
                if col.lower() in [y_col.lower(), "y", "player_y", "attacker_y", "thrower_y"]: actual_y = col
            
            if not actual_x or not actual_y: return []
            
            target_df = df
            if filter_col and filter_val:
                # Use to_lowercase() for case-insensitive filtering to be compatible with all polars versions
                target_df = df.filter(pl.col(filter_col).cast(pl.Utf8).str.to_lowercase().str.contains(filter_val.lower()))
            
            # For grenades, we take only the last tick per entity to get detonation point
            if "entity_id" in target_df.columns:
                target_df = target_df.group_by("entity_id").last()

            pts = []
            for row in target_df.select([actual_x, actual_y]).drop_nulls().iter_rows(named=True):
                norm = game_to_pct(row[actual_x], row[actual_y], map_name_clean)
                if norm and norm[0] is not None: pts.append(norm)
            return pts

        heatmap_data = {
            "kills": get_pts(kills_df, "attacker_x", "attacker_y"),
            "deaths": get_pts(kills_df, "victim_x", "victim_y"),
            "shots": get_pts(getattr(dem, "shots", None), "player_x", "player_y"),
            "smokes": get_pts(getattr(dem, "smokes", None), "x", "y"),
            "flashes": get_pts(getattr(dem, "grenades", None), "x", "y", "grenade_type", "flash"),
            "he": get_pts(getattr(dem, "grenades", None), "x", "y", "grenade_type", "(hegrenade|frag)"),
        }
        
        print("DEBUG: Heatmap Data Counts:")
        for k, v in heatmap_data.items():
            print(f"DEBUG:   - {k}: {len(v)} points")

        # 6. Weapon stats
        weapon_kills = {}
        if not kills_df.is_empty():
            for k in kills_df.iter_rows(named=True):
                w = k.get("weapon")
                if w: weapon_kills[w] = weapon_kills.get(w, 0) + 1
        weapons = [{"weapon": str(w), "kills": k} for w, k in sorted(weapon_kills.items(), key=lambda x: x[1], reverse=True)]

        # 7. Team Summary
        # Filter Unknowns and prioritize sides
        all_teams = sorted(list(set([p["team_name"] for p in players_list if p["team_name"] != "Unknown"])))
        if not all_teams:
            all_teams = sorted(list(team_scores.keys()))
        
        team_a_name = all_teams[0] if len(all_teams) > 0 else "CT"
        team_b_name = all_teams[1] if len(all_teams) > 1 else "TERRORIST"
        
        print(f"DEBUG: Teams Identified: {all_teams}")

        # Final Player Log
        print("DEBUG: --- PLAYER SUMMARY ---")
        for p in sorted(players_list, key=lambda x: x["kills"], reverse=True)[:5]:
            print(f"DEBUG: {p['name']} ({p['team_name']}) - {p['kills']} kills")

        # Explicit cleanup for Windows
        if 'dem' in locals(): del dem
        gc.collect()

        return JSONResponse({
            "map_name": map_name,
            "total_kills": len(kills_df),
            "total_rounds": total_rounds,
            "hs_rate": round((kills_df["headshot"].sum() / len(kills_df) * 100), 1) if not kills_df.is_empty() and "headshot" in kills_df.columns else 0,
            "total_damage": sum([s["damage"] for s in player_stats.values()]),
            "players": sorted(players_list, key=lambda x: x["kills"], reverse=True),
            "round_stats": {
                "team_a": team_a_name, 
                "score_a": team_scores.get(team_a_name, 0), 
                "team_b": team_b_name, 
                "score_b": team_scores.get(team_b_name, 0)
            },
            "points": heatmap_data,
            "weapons": weapons,
            "has_map_data": map_name_clean in MAP_DATA
        })

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        # Final cleanup for Windows: delete objects and then files
        if 'dem' in locals(): del dem
        if 'raw_parser' in locals(): del raw_parser
        gc.collect()
        
        if os.path.exists(tmp):
            for i in range(5):
                try:
                    os.remove(tmp)
                    print(f"DEBUG: Successfully removed temp file {tmp}")
                    break
                except Exception as e:
                    print(f"DEBUG: Retry {i+1} - Failed to remove {tmp}: {e}")
                    time.sleep(1.0) # Longer sleep for Windows file handles

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
