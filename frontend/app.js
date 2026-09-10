const COLORS = {
  original: "#2a78d6",
  normal_ratio: "#eb6834",
  idw: "#1baf7a",
  random_forest: "#eda100",
  best_result: "#7a4fd6",
};

const SERIES_LABELS = {
  original: "Data Asli",
  normal_ratio: "Normal Ratio",
  idw: "IDW",
  random_forest: "Random Forest",
  best_result: "Hasil Terbaik",
};

let state = {
  scope: "dashboard", // "dashboard" | sessionId string
  map: null,
  markerLayer: null,
  topMissingChart: null,
  timeseriesChart: null,
};

function apiPath(path) {
  if (state.scope === "dashboard") return `/api/dashboard${path}`;
  return `/api/sessions/${state.scope}${path}`;
}

function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.className = isError ? "toast error" : "toast";
  toast.hidden = false;
  setTimeout(() => { toast.hidden = true; }, 5000);
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

function setBadge(text, cls) {
  const badge = document.getElementById("statusBadge");
  badge.textContent = text;
  badge.className = `badge ${cls || ""}`.trim();
}

function completenessColor(pct) {
  if (pct === null || pct === undefined || isNaN(pct)) return "#c3c2b7";
  const steps = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#0d366b"];
  const idx = Math.min(steps.length - 1, Math.floor((pct / 100) * steps.length));
  return steps[idx];
}

function renderStatCards(summaryRows) {
  const total = summaryRows.length;
  const totalMissing = summaryRows.reduce((a, r) => a + (r.DATA_ASLI_KOSONG || 0), 0);
  const totalValid = summaryRows.reduce((a, r) => a + (r.DATA_ASLI_VALID || 0), 0);
  const rfEligible = summaryRows.filter((r) => r.RF_MEMENUHI_SYARAT_LATIH).length;

  const cards = [
    { label: "Jumlah PCH", value: total },
    { label: "Data asli valid", value: totalValid.toLocaleString("id-ID") },
    { label: "Data asli kosong", value: totalMissing.toLocaleString("id-ID") },
    { label: "PCH memenuhi syarat latih RF", value: `${rfEligible}/${total}` },
  ];

  document.getElementById("statCards").innerHTML = cards
    .map((c) => `<div class="card"><div class="label">${c.label}</div><div class="value">${c.value}</div></div>`)
    .join("");
}

function renderMap(rows) {
  if (!state.map) {
    state.map = L.map("map");
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 18,
    }).addTo(state.map);
    state.markerLayer = L.layerGroup().addTo(state.map);
  }

  state.markerLayer.clearLayers();

  const points = [];
  rows.forEach((row) => {
    if (row.Latitude == null || row.Longitude == null) return;
    const pct = row.completeness_pct;
    const marker = L.circleMarker([row.Latitude, row.Longitude], {
      radius: 6,
      color: "#fcfcfb",
      weight: 1,
      fillColor: completenessColor(pct),
      fillOpacity: 0.9,
    }).bindPopup(
      `<b>${row.NAMAPOS}</b><br/>Kelengkapan: ${pct != null ? pct.toFixed(1) : "-"}%<br/>` +
      `Valid: ${row.DATA_ASLI_VALID ?? "-"} | Kosong: ${row.DATA_ASLI_KOSONG ?? "-"}`
    );
    marker.addTo(state.markerLayer);
    points.push([row.Latitude, row.Longitude]);
  });

  if (points.length) {
    state.map.fitBounds(points, { padding: [20, 20] });
  } else {
    state.map.setView([-2.5, 118], 5);
  }
}

function renderTopMissing(rows) {
  const sorted = [...rows].reverse();
  const labels = sorted.map((r) => r.NAMAPOS);

  const ctx = document.getElementById("topMissingChart");
  if (state.topMissingChart) state.topMissingChart.destroy();

  state.topMissingChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Normal Ratio", data: sorted.map((r) => r.ISI_NORMAL_RATIO), backgroundColor: COLORS.normal_ratio },
        { label: "IDW", data: sorted.map((r) => r.ISI_IDW), backgroundColor: COLORS.idw },
        { label: "Random Forest", data: sorted.map((r) => r.ISI_RANDOM_FOREST), backgroundColor: COLORS.random_forest },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: { title: { display: true, text: "Jumlah hari berhasil diisi" } } },
      plugins: { legend: { position: "bottom" } },
    },
  });
}

function renderFailureTable(rows) {
  const container = document.getElementById("failureTable");
  if (!rows.length) {
    container.innerHTML = '<p class="hint">Tidak ada data kegagalan (semua data asli lengkap, atau belum dihitung).</p>';
    return;
  }
  const header = Object.keys(rows[0]);
  container.innerHTML = `
    <table class="data-table">
      <thead><tr>${header.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${header.map((h) => `<td>${r[h] ?? "-"}</td>`).join("")}</tr>`).join("")}</tbody>
    </table>`;
}

async function loadStationOptions() {
  const stations = await fetchJson(apiPath("/stations"));
  const select = document.getElementById("stationSelect");
  select.innerHTML = stations.map((s) => `<option value="${s}">${s}</option>`).join("");
  return stations;
}

async function loadTimeseries(station) {
  const start = document.getElementById("startDate").value;
  const end = document.getElementById("endDate").value;
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);

  const data = await fetchJson(`${apiPath(`/timeseries/${encodeURIComponent(station)}`)}?${params}`);

  const datasets = Object.entries(data.series).map(([key, values]) => ({
    label: SERIES_LABELS[key] || key,
    data: values,
    borderColor: COLORS[key] || "#999",
    backgroundColor: COLORS[key] || "#999",
    borderWidth: key === "original" ? 2.2 : 1.4,
    pointRadius: 0,
    spanGaps: false,
    tension: 0.1,
  }));

  const ctx = document.getElementById("timeseriesChart");
  if (state.timeseriesChart) state.timeseriesChart.destroy();
  state.timeseriesChart = new Chart(ctx, {
    type: "line",
    data: { labels: data.dates, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { maxTicksLimit: 12 } },
        y: { title: { display: true, text: "Curah hujan (mm/hari)" } },
      },
      plugins: { legend: { position: "bottom" } },
    },
  });
}

async function renderModelInfo() {
  const el = document.getElementById("modelInfo");
  try {
    const info = await fetchJson("/api/models");
    const sample = info.stations.slice(0, 10);
    el.innerHTML = `
      <p>Format: HDF5 (.h5) berisi model scikit-learn (Random Forest) yang di-pickle per stasiun, dibuat ${new Date(info.created_at).toLocaleString("id-ID")}.</p>
      <p>Jumlah stasiun dengan model: <b>${info.station_count}</b> | n_estimators: ${info.rf_n_estimators} | random_state: ${info.rf_random_state}</p>
      <table class="data-table">
        <thead><tr><th>NAMAPOS</th><th>Sampel latih</th><th>Jumlah donor</th></tr></thead>
        <tbody>${sample.map((s) => `<tr><td>${s.NAMAPOS}</td><td>${s.n_train_samples}</td><td>${s.n_donors}</td></tr>`).join("")}</tbody>
      </table>
      ${info.stations.length > 10 ? `<p class="hint">... dan ${info.stations.length - 10} stasiun lainnya.</p>` : ""}
    `;
  } catch (err) {
    el.innerHTML = `<p class="hint">Info model belum tersedia: ${err.message}</p>`;
  }
}

async function refreshAll() {
  try {
    const summary = await fetchJson(apiPath("/summary"));
    renderStatCards(summary.stations);
    renderFailureTable(summary.failure_percentage);

    const mapRows = await fetchJson(apiPath("/map"));
    renderMap(mapRows);

    const topMissing = await fetchJson(apiPath("/top-missing?n=20"));
    renderTopMissing(topMissing);

    const stations = await loadStationOptions();
    if (stations.length) {
      await loadTimeseries(stations[0]);
    }

    setBadge(state.scope === "dashboard" ? "dashboard referensi" : `sesi upload: ${state.scope}`, "ok");
  } catch (err) {
    setBadge("gagal memuat", "error");
    showToast(err.message, true);
  }
}

document.getElementById("stationSelect").addEventListener("change", (e) => {
  loadTimeseries(e.target.value).catch((err) => showToast(err.message, true));
});
document.getElementById("startDate").addEventListener("change", () => {
  const station = document.getElementById("stationSelect").value;
  if (station) loadTimeseries(station).catch((err) => showToast(err.message, true));
});
document.getElementById("endDate").addEventListener("change", () => {
  const station = document.getElementById("stationSelect").value;
  if (station) loadTimeseries(station).catch((err) => showToast(err.message, true));
});

document.getElementById("uploadInput").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  setBadge("mengunggah & memproses...", "");
  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetchJson("/api/upload", { method: "POST", body: formData });
    state.scope = res.session_id;
    document.getElementById("downloadBtn").disabled = false;
    showToast(res.message);
    await refreshAll();
  } catch (err) {
    setBadge("upload gagal", "error");
    showToast(err.message, true);
  } finally {
    e.target.value = "";
  }
});

document.getElementById("downloadBtn").addEventListener("click", () => {
  if (state.scope === "dashboard") return;
  window.location.href = `/api/sessions/${state.scope}/download`;
});

renderModelInfo();
refreshAll();
