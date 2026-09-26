import { useEffect, useState } from "react";
import { api } from "../api/client";
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
type Created = { id: number; code: string };
function fmt(m: number) { const h = Math.floor(m/60), mm = m%60; return `${String(h).padStart(2,"0")}:${String(mm).padStart(2,"0")}`; }
export default function WindowsPage() {
  const [products, setProducts] = useState<P[]>([]);
  const [pid, setPid] = useState<number | "">("");
  const [rows, setRows] = useState<W[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  useEffect(() => { api<P[]>("/products").then(p => { setProducts(p); if (p[0]) setPid(p[0].id); }); }, []);
  const reload = (productId: number | "" = pid) =>
    productId === "" ? Promise.resolve() : api<W[]>(`/windows?product_id=${productId}`).then(setRows);
  useEffect(() => { setMsg(""); setErr(""); reload(); }, [pid]);
  async function adopt(w: W) {
    setMsg(""); setErr(""); setBusy(w.oven_id);
    try {
      // 产品、炉位、建议开工分钟一起提交；是否仍空由后端按当时库里的占炉重算
      const b = await api<Created>("/batches", {
        method: "POST",
        body: JSON.stringify({ product_id: pid, oven_id: w.oven_id, start_min: w.start_min }),
      });
      setMsg(`已创建 ${b.code}：${w.oven_label} 开工 ${fmt(w.start_min)}，发酵止 ${fmt(w.ferment_end)}、烘烤止 ${fmt(w.bake_end)}，可到批次/甘特台核对。`);
    } catch (e) {
      setErr(`未创建：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
      reload();
    }
  }
  return (<>
    <h2>可开工窗口</h2>
    <div className="toolbar">
      <select value={pid} onChange={e => setPid(Number(e.target.value))}>{products.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
    </div>
    {msg && <div className="ok">{msg}</div>}
    {err && <div className="err">{err}</div>}
    <table className="table"><thead><tr><th>炉位</th><th>开工</th><th>发酵止</th><th>烘烤止</th><th>所需时长</th><th></th></tr></thead>
    <tbody>{rows.map(w => <tr key={w.oven_id}>
      <td>{w.oven_label}</td>
      <td className="mono">{fmt(w.start_min)}</td>
      <td className="mono">{fmt(w.ferment_end)}</td>
      <td className="mono">{fmt(w.bake_end)}</td>
      <td className="mono">{w.duration_min} min</td>
      <td><button disabled={busy === w.oven_id} onClick={() => adopt(w)}>带入创建</button></td>
    </tr>)}
      {!rows.length && <tr><td colSpan={6}>无可用窗口</td></tr>}
    </tbody></table>
  </>);
}
