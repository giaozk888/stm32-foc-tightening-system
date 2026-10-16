"use strict";

const token = document.querySelector('meta[name="panel-token"]').content;
const elements = Object.fromEntries(
  ["conn-dot", "connection", "last-rx", "port", "scan", "connect", "refresh",
   "ping", "notice", "mode", "fault", "foc", "position", "iq", "vbus",
   "slots", "pending", "esp", "ping-status", "position-now", "position-chart",
   "iq-now", "iq-chart", "discovery", "parse-errors", "log"]
    .map(id => [id, document.getElementById(id)])
);
let lastSeq = 0;
let connected = false;
let samples = [];

function showNotice(message) {
  elements.notice.textContent = message || "";
}

async function getJson(path) {
  const response = await fetch(path, {cache: "no-store"});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

async function postJson(path, payload = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Panel-Token": token},
    body: JSON.stringify(payload)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

async function scanPorts() {
  const ports = await getJson("/api/ports");
  const selected = elements.port.value || "COM5";
  elements.port.replaceChildren();
  for (const port of ports) {
    const option = document.createElement("option");
    option.value = port.device;
    option.textContent = `${port.device} · ${port.description}`;
    elements.port.append(option);
  }
  if (!ports.some(port => port.device === selected)) {
    const option = document.createElement("option");
    option.value = selected;
    option.textContent = selected;
    elements.port.append(option);
  }
  elements.port.value = selected;
}

function format(value, digits = 1) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function setText(id, value) {
  elements[id].textContent = value === null || value === undefined ? "—" : String(value);
}

function appendLogs(lines) {
  if (!lines.length) return;
  const atBottom = elements.log.scrollTop + elements.log.clientHeight >= elements.log.scrollHeight - 25;
  elements.log.querySelector(".log-empty")?.remove();
  const fragment = document.createDocumentFragment();
  for (const entry of lines) {
    const row = document.createElement("p");
    row.textContent = `${String(entry.timestamp).slice(11, 23)}  ${entry.line}`;
    if (/^\d+ ERR\b/.test(entry.line) || entry.line.startsWith("[上位机]")) {
      row.classList.add("error");
    }
    fragment.append(row);
  }
  elements.log.append(fragment);
  while (elements.log.children.length > 400) elements.log.firstElementChild.remove();
  if (atBottom) elements.log.scrollTop = elements.log.scrollHeight;
}

function drawChart(canvas, key, color, unit) {
  const scale = window.devicePixelRatio || 1;
  const width = Math.max(1, canvas.clientWidth);
  const height = Math.max(1, canvas.clientHeight);
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const ctx = canvas.getContext("2d");
  ctx.scale(scale, scale);
  ctx.clearRect(0, 0, width, height);
  const left = 48, right = 10, top = 15, bottom = 24;
  const plotWidth = Math.max(1, width - left - right);
  const plotHeight = Math.max(1, height - top - bottom);
  const values = samples.map(point => point[key]).filter(Number.isFinite);
  const rawMin = values.length ? Math.min(...values) : 0;
  const rawMax = values.length ? Math.max(...values) : 1;
  const padding = Math.max((rawMax - rawMin) * 0.12, key === "position" ? 0.1 : 2);
  const minimum = rawMin - padding, maximum = rawMax + padding;
  ctx.strokeStyle = "#28405a";
  ctx.lineWidth = 1;
  ctx.fillStyle = "#8097b1";
  ctx.font = "11px Segoe UI, sans-serif";
  for (let i = 0; i <= 3; i++) {
    const y = top + i * plotHeight / 3;
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(width - right, y); ctx.stroke();
    ctx.fillText(`${(maximum - i * (maximum - minimum) / 3).toFixed(1)}`, 2, y + 4);
  }
  ctx.fillText(unit, 2, height - 4);
  if (!values.length) {
    ctx.fillText("等待遥测数据…", left + 10, top + plotHeight / 2);
    return;
  }
  ctx.beginPath();
  samples.forEach((point, index) => {
    const x = left + index * plotWidth / Math.max(samples.length - 1, 1);
    const y = top + (maximum - point[key]) * plotHeight / (maximum - minimum);
    if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.fillStyle = "#8097b1";
  ctx.textAlign = "right";
  ctx.fillText(samples.at(-1).time || "", width - right, height - 4);
  ctx.textAlign = "left";
}

function redraw() {
  drawChart(elements["position-chart"], "position", "#65c8ee", "deg");
  drawChart(elements["iq-chart"], "iq", "#6fdda8", "mA");
}

function render(state) {
  connected = Boolean(state.connected);
  elements["conn-dot"].classList.toggle("online", connected);
  setText("connection", connected ? `${state.port} 已连接` : "未连接");
  setText("last-rx", connected ? `最近接收 ${state.fields.last_rx}` : "等待设备数据");
  elements.connect.textContent = connected ? "断开" : "连接";
  elements.refresh.disabled = !connected;
  elements.ping.disabled = !connected;
  elements.port.disabled = connected;
  if (state.error) showNotice(`串口错误：${state.error}`);
  const f = state.fields;
  setText("mode", f.mode);
  setText("fault", f.fault);
  elements.fault.classList.toggle("good", f.fault === "0");
  elements.fault.classList.toggle("bad", f.fault !== "0" && f.fault !== "—");
  setText("foc", format(f.foc_hz, 0));
  setText("position", `${format(f.position_deg, 2)}°`);
  setText("iq", `${format(f.iq_ma, 0)} mA`);
  setText("vbus", `${format(f.vbus_v, 2)} V`);
  setText("slots", `${f.slot} / ${f.confirmed}`);
  setText("pending", `待试槽 ${f.pending}`);
  setText("esp", f.esp);
  setText("ping-status", f.ping);
  setText("position-now", `${format(f.position_deg, 2)} deg`);
  setText("iq-now", `${format(f.iq_ma, 0)} mA`);
  setText("discovery", `${f.discovery_rx} / ${f.discovery_tx}`);
  setText("parse-errors", f.parse_errors);
  samples = Array.isArray(state.samples) ? state.samples : [];
  appendLogs(state.logs || []);
  lastSeq = Math.max(lastSeq, Number(state.latest_seq) || 0);
  redraw();
}

async function poll() {
  try {
    render(await getJson(`/api/state?after=${lastSeq}`));
  } catch (error) {
    showNotice(`本地服务不可用：${error.message}`);
  } finally {
    window.setTimeout(poll, 1000);
  }
}

async function action(callback) {
  try {
    await callback();
    showNotice("");
    render(await getJson(`/api/state?after=${lastSeq}`));
  } catch (error) {
    showNotice(error.message);
  }
}

elements.scan.addEventListener("click", () => action(scanPorts));
elements.connect.addEventListener("click", () => action(async () => {
  if (connected) await postJson("/api/disconnect");
  else await postJson("/api/connect", {port: elements.port.value});
}));
elements.refresh.addEventListener("click", () => action(() => postJson("/api/refresh")));
elements.ping.addEventListener("click", () => action(() => postJson("/api/esp-ping")));
window.addEventListener("resize", redraw);
scanPorts().catch(error => showNotice(error.message));
redraw();
poll();
