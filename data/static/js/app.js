/**
 * CS2 Tactical Analytics - Frontend Engine
 * Optimized for performance and high-fidelity visualization.
 */

// ── UI Elements ──
const elements = {
  fileInput: document.getElementById("fileInput"),
  dropZone: document.getElementById("dropZone"),
  btnAnalyze: document.getElementById("btnAnalyze"),
  loading: document.getElementById("loading"),
  results: document.getElementById("results"),
  uploadSection: document.getElementById("uploadSection"),
  uploadInner: document.getElementById("uploadInner"),
  fileName: document.getElementById("fname"),
  loadingText: document.getElementById("ltxt"),
  mapBadge: document.getElementById("mapBadge"),
  statsGrid: document.getElementById("sgrid"),
  weaponStats: document.getElementById("wep"),
  playerTable: document.getElementById("ptable"),
  canvasBox: document.getElementById("canvasBox"),
  noMap: document.getElementById("noMap"),
  scoreA: document.getElementById("s-a"),
  scoreB: document.getElementById("s-b"),
  teamAName: document.getElementById("t-a-name"),
  teamBName: document.getElementById("t-b-name"),
};

// ── State Management ──
let state = {
  data: null,
  mapImage: null,
  activeFilters: new Set(["kills"]),
  loadingInterval: null,
};

const LAYER_COLORS = {
  kills:   { h: [255, 68, 68],   d: "rgba(255,68,68,0.8)" },
  deaths:  { h: [68, 136, 255],  d: "rgba(68,136,255,0.8)" },
  shots:   { h: [255, 204, 0],   d: "rgba(255,204,0,0.6)" },
  smokes:  { h: [68, 221, 170],  d: "rgba(68,221,170,0.8)" },
  flashes: { h: [255, 170, 51],  d: "rgba(255,170,51,0.8)" },
  he:      { h: [255, 102, 51],  d: "rgba(255,102,51,0.8)" },
};

// ── Initialization ──
function init() {
  elements.fileInput.addEventListener("change", handleFileSelect);
  elements.dropZone.addEventListener("dragover", e => { e.preventDefault(); elements.dropZone.classList.add("over"); });
  elements.dropZone.addEventListener("dragleave", () => elements.dropZone.classList.remove("over"));
  elements.dropZone.addEventListener("drop", handleFileDrop);
  elements.btnAnalyze.addEventListener("click", startAnalysis);
}

function handleFileSelect() {
  const file = elements.fileInput.files[0];
  if (file) {
    elements.fileName.textContent = file.name;
    elements.btnAnalyze.disabled = false;
  }
}

function handleFileDrop(e) {
  e.preventDefault();
  elements.dropZone.classList.remove("over");
  const file = e.dataTransfer.files[0];
  if (file && file.name.endsWith(".dem")) {
    elements.fileInput.files = e.dataTransfer.files;
    handleFileSelect();
  }
}

// ── Core Analysis Flow ──
async function startAnalyze() {
  elements.uploadInner.style.display = "none";
  elements.loading.classList.add("on");
  elements.btnAnalyze.disabled = true;

  const msgs = ["Decoding demo data...", "Extracting match events...", "Calculating player ratings...", "Building heatmaps..."];
  let i = 0;
  state.loadingInterval = setInterval(() => {
    elements.loadingText.textContent = msgs[i++ % msgs.length];
  }, 2000);

  const formData = new FormData();
  formData.append("file", elements.fileInput.files[0]);

  try {
    const response = await fetch("/analyze", { method: "POST", body: formData });
    const result = await response.json();
    clearInterval(state.loadingInterval);
    
    if (result.error) throw new Error(result.error);
    renderDashboard(result);
  } catch (err) {
    clearInterval(state.loadingInterval);
    showError(err.message);
  }
}

function showError(msg) {
  elements.loading.classList.remove("on");
  elements.results.classList.add("on");
  elements.statsGrid.innerHTML = `<div class="glass error-box">${msg}</div>`;
}

// ── Rendering Engine ──
function renderDashboard(data) {
  state.data = data;
  elements.loading.classList.remove("on");
  elements.uploadSection.style.display = "none";
  elements.results.classList.add("on");

  // 1. Overview Statistics
  elements.statsGrid.innerHTML = `
    <div class="glass sc c"><div class="sl">KILLS</div><div class="sv">${data.total_kills}</div><div class="su">전체 킬 수</div></div>
    <div class="glass sc o"><div class="sl">ROUNDS</div><div class="sv">${data.total_rounds}</div><div class="su">전체 라운드</div></div>
    <div class="glass sc g"><div class="sl">HS RATE</div><div class="sv">${data.hs_rate}%</div><div class="su">헤드샷 비율</div></div>
    <div class="glass sc y"><div class="sl">DAMAGE</div><div class="sv">${(data.total_damage / 1000).toFixed(1)}k</div><div class="su">전체 가한 데미지</div></div>
  `;

  // 2. Scoreboard
  const rs = data.round_stats;
  elements.scoreA.innerText = rs.score_a;
  elements.scoreB.innerText = rs.score_b;
  elements.teamAName.innerText = rs.team_a;
  elements.teamBName.innerText = rs.team_b;
  elements.mapBadge.innerText = data.map_name.toUpperCase();

  // 3. Players Table
  renderPlayers(data.players);

  // 4. Weapon Stats
  if (data.weapons) renderWeaponStats(data.weapons);

  // 5. Heatmap Initialization
  loadMapImage(data.map_name);
  
  elements.results.scrollIntoView({ behavior: "smooth" });
}

function renderPlayers(players) {
  const teams = {};
  players.forEach(p => {
    if (!teams[p.team_name]) teams[p.team_name] = [];
    teams[p.team_name].push(p);
  });

  const teamNames = Object.keys(teams);
  elements.playerTable.innerHTML = `
    <div class="team-container">
      ${teamNames.map((t, idx) => `
        <div class="glass team-box">
          <div class="team-header ${idx === 0 ? 'ct' : 't'}">
            <div class="team-info">
              <span class="team-side-tag">${idx === 0 ? 'CT' : 'T'}</span>
              <span class="team-name-text">${t}</span>
            </div>
            <div class="team-meta">${teams[t].length} PLAYERS</div>
          </div>
          <div class="table-scroll">
            <table>
              <thead>
                <tr><th>PLAYER</th><th>K</th><th>D</th><th>A</th><th>ADR</th><th>IMP</th><th>RATING</th></tr>
              </thead>
              <tbody>
                ${teams[t].map(p => `
                  <tr>
                    <td class="p-name">${p.name}</td>
                    <td class="p-val">${p.kills}</td>
                    <td class="p-val">${p.deaths}</td>
                    <td class="p-val">${p.assists}</td>
                    <td class="p-val">${p.adr.toFixed(1)}</td>
                    <td class="p-val">${p.impact.toFixed(2)}</td>
                    <td><span class="rating-badge ${getRatingClass(p.rating)}">${p.rating.toFixed(2)}</span></td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function getRatingClass(r) {
  if (r >= 1.2) return "rating-high";
  if (r >= 0.9) return "rating-mid";
  return "rating-low";
}

function renderWeaponStats(weapons) {
  if (!elements.weaponStats) return;
  
  const maxKills = weapons.length > 0 ? weapons[0].kills : 1;
  elements.weaponStats.innerHTML = weapons.slice(0, 10).map(w => `
    <div class="weapon-row">
      <div class="weapon-name">${w.weapon.toUpperCase()}</div>
      <div class="weapon-bar-container">
        <div class="weapon-bar" style="width: ${(w.kills / maxKills) * 100}%"></div>
      </div>
      <div class="weapon-kills">${w.kills}</div>
    </div>
  `).join("");
}

// ── Heatmap Engine ──
function loadMapImage(mapName) {
  elements.noMap.style.display = "none";
  elements.canvasBox.style.display = "block";
  
  state.mapImage = new Image();
  state.mapImage.onload = handleMapResize;
  state.mapImage.onerror = () => {
    elements.noMap.style.display = "block";
    state.mapImage.hasError = true;
    state.mapImage.mockWidth = 1024;
    state.mapImage.mockHeight = 1024;
    handleMapResize();
  };
  state.mapImage.src = `/map-image/${mapName}`;
  
  window.addEventListener("resize", handleMapResize);
  setupHeatmapControls();
}

function handleMapResize() {
  const container = document.getElementById("heatmap-container");
  const imgW = state.mapImage.mockWidth || state.mapImage.width;
  const imgH = state.mapImage.mockHeight || state.mapImage.height;
  if (!imgW) return;

  const aspect = imgH / imgW;
  const w = container.clientWidth;
  const h = w * aspect;
  container.style.height = h + "px";

  const cvs = ["cvMap", "cvHeat"];
  cvs.forEach(id => {
    const c = document.getElementById(id);
    // 내부 해상도를 1024로 고정하여 좌표계(0~1)와 매칭
    c.width = 1024;
    c.height = 1024;
  });

  drawMap();
  drawHeat();
}

function drawMap() {
  const ctx = document.getElementById("cvMap").getContext("2d");
  const c = document.getElementById("cvMap");
  ctx.clearRect(0, 0, c.width, c.height);
  
  if (!state.mapImage.hasError && state.mapImage.complete) {
    ctx.drawImage(state.mapImage, 0, 0, c.width, c.height);
    ctx.fillStyle = "rgba(0,0,0,0.5)"; // Dim the map for better visibility
    ctx.fillRect(0, 0, c.width, c.height);
  } else {
    ctx.fillStyle = "#111"; // Fallback dark background
    ctx.fillRect(0, 0, c.width, c.height);
  }
}

function setupHeatmapControls() {
  document.querySelectorAll(".filter-btn").forEach(btn => {
    const layer = btn.dataset.layer;
    btn.onclick = () => {
      if (state.activeFilters.has(layer)) state.activeFilters.delete(layer);
      else state.activeFilters.add(layer);
      btn.classList.toggle("active");
      drawHeat();
    };
  });
}

function drawHeat() {
  const ctx = document.getElementById("cvHeat").getContext("2d");
  const c = document.getElementById("cvHeat");
  ctx.clearRect(0, 0, c.width, c.height);

  state.activeFilters.forEach(layer => {
    const pts = state.data.points[layer];
    if (pts && pts.length) {
      drawKDE(ctx, pts, c.width, c.height, LAYER_COLORS[layer].h);
    }
  });
}

function drawKDE(ctx, pts, W, H, rgb) {
  const GRID = 256;
  const density = new Float32Array(GRID * GRID);
  const bw = 0.02; // Bandwidth
  const bw2 = bw * bw;

  pts.forEach(([px, py]) => {
    const gx = px * GRID, gy = py * GRID;
    const r = Math.ceil(bw * GRID * 2.5);
    for (let dy = -r; dy <= r; dy++) {
      for (let dx = -r; dx <= r; dx++) {
        const nx = Math.floor(gx + dx), ny = Math.floor(gy + dy);
        if (nx < 0 || ny < 0 || nx >= GRID || ny >= GRID) continue;
        const dist2 = Math.pow(px - nx / GRID, 2) + Math.pow(py - ny / GRID, 2);
        if (dist2 < bw2 * 4) density[ny * GRID + nx] += Math.exp(-dist2 / (2 * bw2));
      }
    }
  });

  let maxD = 0;
  for (let d of density) if (d > maxD) maxD = d;
  if (maxD === 0) return;

  const off = document.createElement("canvas");
  off.width = off.height = GRID;
  const octx = off.getContext("2d");
  const idata = octx.createImageData(GRID, GRID);

  for (let i = 0; i < density.length; i++) {
    const t = density[i] / maxD;
    if (t < 0.05) continue;
    
    const alpha = Math.min(255, t * 200);
    idata.data[i * 4] = rgb[0];
    idata.data[i * 4 + 1] = rgb[1];
    idata.data[i * 4 + 2] = rgb[2];
    idata.data[i * 4 + 3] = alpha;
  }
  octx.putImageData(idata, 0, 0);

  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.drawImage(off, 0, 0, W, H);
  ctx.restore();
}

function resetUI() {
  clearInterval(state.loadingInterval);
  window.location.reload();
}

// Start
init();
