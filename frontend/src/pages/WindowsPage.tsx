import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";

type P = { id: number; name: string };
type W = {
  oven_id: number;
  oven_label: string;
  start_min: number;
  end_min: number;
  duration_min: number;
  ferment_end: number;
  bake_end: number;
};
type BatchOut = { id: number; code: string };
type ConflictDetail = {
  message?: string;
  opponent_code?: string;
  opponent_batch_id?: number;
  phase?: string;
  phase_label?: string;
};
type Outcome =
  | { kind: "ok"; code: string; oven_label: string }
  | { kind: "conflict"; oven_label: string; opponent: string; phase: string }
  | { kind: "error"; oven_label: string; message: string };

const PHASE_LABEL: Record<string, string> = { ferment: "发酵", bake: "烘烤" };
function fmt(m: number) { const h = Math.floor(m/60), mm = m%60; return `${String(h).padStart(2,"0")}:${String(mm).padStart(2,"0")}`; }

export default function WindowsPage() {
  const [products, setProducts] = useState<P[]>([]);
  const [pid, setPid] = useState<number | "">("");
  const [rows, setRows] = useState<W[]>([]);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [pending, setPending] = useState<number | null>(null);

  useEffect(() => { api<P[]>("/products").then(p => { setProducts(p); if (p[0]) setPid(p[0].id); }); }, []);
  useEffect(() => {
    if (pid === "") return;
    setOutcome(null);
    api<W[]>(`/windows?product_id=${pid}`).then(setRows);
  }, [pid]);

  async function claim(w: W) {
    if (pid === "") return;
    setPending(w.oven_id);
    setOutcome(null);
    try {
      // 提交产品+炉位+建议开工分钟，由后端按当时库里的占炉重新计算裁决
      const b = await api<BatchOut>("/batches", {
        method: "POST",
        body: JSON.stringify({ product_id: pid, oven_id: w.oven_id, start_min: w.start_min }),
      });
      setOutcome({ kind: "ok", code: b.code, oven_label: w.oven_label });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail && typeof e.detail === "object") {
        const d = e.detail as ConflictDetail;
        const opponent = d.opponent_code ?? (d.opponent_batch_id != null ? `#${d.opponent_batch_id}` : "另一批次");
        const phase = d.phase_label ?? (d.phase ? PHASE_LABEL[d.phase] ?? d.phase : "未知");
        setOutcome({ kind: "conflict", oven_label: w.oven_label, opponent, phase });
      } else {
        setOutcome({ kind: "error", oven_label: w.oven_label, message: e instanceof Error ? e.message : String(e) });
      }
    } finally {
      setPending(null);
      // 无论成败都按最新占炉重取建议
      api<W[]>(`/windows?product_id=${pid}`).then(setRows);
    }
  }

  return (<>
    <h2>可开工窗口</h2>
    <div className="toolbar">
      <select value={pid} onChange={e => setPid(Number(e.target.value))}>{products.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      <span className="hint">建议为试算结果，不单独占炉；提交时按当时库里的占炉重新计算</span>
    </div>
    {outcome?.kind === "ok" && (
      <div className="ok">
        {outcome.oven_label} 已创建批次 <strong className="mono">{outcome.code}</strong>
        ，可到 <Link to="/batches">批次列表</Link> 或 <Link to="/gantt">甘特</Link> 核对两段端点。
      </div>
    )}
    {outcome?.kind === "conflict" && (
      <div className="err">
        {outcome.oven_label} 该空档已被批次 <strong className="mono">{outcome.opponent}</strong> 的
        {outcome.phase}阶段占上，本次未创建。
      </div>
    )}
    {outcome?.kind === "error" && (
      <div className="err">{outcome.oven_label} 提交失败:{outcome.message}</div>
    )}
    <table className="table"><thead><tr><th>炉位</th><th>开工</th><th>发酵止</th><th>烘烤止</th><th>所需时长</th><th>操作</th></tr></thead>
    <tbody>{rows.map(w => <tr key={w.oven_id}>
      <td>{w.oven_label}</td>
      <td className="mono">{fmt(w.start_min)}</td>
      <td className="mono">{fmt(w.ferment_end)}</td>
      <td className="mono">{fmt(w.bake_end)}</td>
      <td className="mono">{w.duration_min} min</td>
      <td><button disabled={pending === w.oven_id} onClick={() => claim(w)}>
        {pending === w.oven_id ? "提交中…" : "带入创建"}
      </button></td>
    </tr>)}
      {!rows.length && <tr><td colSpan={6}>无可用窗口</td></tr>}
    </tbody></table>
  </>);
}
