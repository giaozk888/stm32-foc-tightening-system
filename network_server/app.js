"use strict";
const $ = id => document.getElementById(id);
let token = "", after = 0, last = 0, timer;
const outcomes = ["NONE", "OK", "STOPPED", "RUNDOWN_TIMEOUT", "STOP_TIMEOUT", "ABORT", "FAULT"];
async function fetchData(path) {
  const r = await fetch(path, {headers: {Authorization: `Bearer ${token}`}});
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r;
}
function query() { return `after=${after}&limit=100${$("kind").value ? `&kind=${$("kind").value}` : ""}`; }
async function refresh() {
  try {
    const s = await (await fetchData("/api/v1/summary")).json();
    $("samples").textContent = s.samples; $("results").textContent = s.results;
    $("devices").replaceChildren();
    for (const d of s.devices) {
      const p = document.createElement("p");
      p.textContent = `${d.device} · 接收 ${d.received_at} · 设备运行 ${d.sample.uptime_ms} ms · 故障 ${d.sample.fault} · 质量 0x${d.sample.vbus_quality.toString(16)}`;
      $("devices").append(p);
    }
    const data = await (await fetchData(`/api/v1/observations?${query()}`)).json();
    $("rows").replaceChildren(); last = after;
    for (const r of data.records) {
      last = r.id;
      const tr = document.createElement("tr"), v = r.sample;
      const motion = v.flags & 1 ? `${v.position_cdeg/100} / ${v.speed_drpm/10}` : "不可用";
      const iq = v.flags & 2 ? v.iq_ma : "不可用";
      const bus = v.vbus_quality & 18 ? "不可用" : `${v.vbus_mv/1000}（估值）`;
      for (const text of [r.id, r.received_at, r.device, `${r.session} / ${v.seq}`, `${v.run} / ${v.cycle}`, `${v.stage} / ${outcomes[v.outcome]}${v.kind ? " [结果]" : ""}`, motion, iq, `${bus} / 0x${v.vbus_quality.toString(16)}`]) {
        const td = document.createElement("td"); td.textContent = text; tr.append(td);
      }
      $("rows").append(tr);
    }
    $("message").textContent = "已读取服务器落库记录；网络控制始终锁定。";
  } catch (e) { $("message").textContent = `读取失败：${e.message}`; }
}
$("connect").onclick = () => { token = $("token").value; clearInterval(timer); refresh(); timer = setInterval(refresh, 5000); };
$("next").onclick = () => { after = last; refresh(); };
$("reset").onclick = $("kind").onchange = () => { after = 0; refresh(); };
$("export").onclick = async () => {
  try {
    const r = await fetchData(`/api/v1/export.csv?${query()}`), u = URL.createObjectURL(await r.blob());
    const a = document.createElement("a"); a.href = u; a.download = "network-observations.csv"; a.click(); setTimeout(() => URL.revokeObjectURL(u), 1000);
  } catch (e) { $("message").textContent = `导出失败：${e.message}`; }
};
