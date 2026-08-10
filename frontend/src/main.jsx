import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  getGraphMaps,
  getGraphStats,
  getSubgraph,
  getTask,
  searchGraph,
  uploadDemo,
} from "./api";
import "./styles.css";

const FLOW = ["Supervisor", "Tools", "Router", "RAG + Graph", "Critique", "Analyst", "Coach", "Verifier"];

function formatNumber(value) {
  return new Intl.NumberFormat("en-US").format(value || 0);
}

function statusLabel(status) {
  return { PENDING: "排队中", STARTED: "解析中", SUCCESS: "已完成", FAILURE: "失败" }[status] || status || "待提交";
}

function App() {
  const [file, setFile] = useState(null);
  const [mode, setMode] = useState("demo_forensic");
  const [taskId, setTaskId] = useState("");
  const [task, setTask] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [maps, setMaps] = useState([]);
  const [map, setMap] = useState("Mirage");
  const [graphStats, setGraphStats] = useState({});
  const [graph, setGraph] = useState({ nodes: [], edges: [] });
  const [query, setQuery] = useState("职业比赛中 Mirage 的首杀和道具模式");
  const [searchResults, setSearchResults] = useState([]);

  const analysis = task?.status === "SUCCESS" ? task.result?.analysis || task.result : null;
  const metrics = analysis?.metrics || {};

  useEffect(() => {
    Promise.all([getGraphMaps(), getGraphStats()])
      .then(([mapData, stats]) => {
        setMaps(mapData.maps || []);
        setGraphStats(stats);
        if (mapData.maps?.length && !mapData.maps.includes(map)) setMap(mapData.maps[0]);
      })
      .catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    getSubgraph(map).then(setGraph).catch((reason) => setError(reason.message));
  }, [map]);

  useEffect(() => {
    if (!taskId || task?.status === "SUCCESS" || task?.status === "FAILURE") return undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await getTask(taskId);
        if (!cancelled) setTask(next);
      } catch (reason) {
        if (!cancelled) setError(reason.message);
      }
    };
    poll();
    const timer = window.setInterval(poll, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [taskId, task?.status]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!file) return setError("请选择一个 .dem 文件");
    setBusy(true);
    setError("");
    setTask(null);
    try {
      const response = await uploadDemo(file, mode);
      setTaskId(response.task_id);
      setTask({ status: "PENDING", task_id: response.task_id });
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleSearch(event) {
    event.preventDefault();
    if (!query.trim()) return;
    try {
      const response = await searchGraph(query.trim(), map);
      setSearchResults(response.results || []);
    } catch (reason) {
      setError(reason.message);
    }
  }

  const graphNodes = useMemo(() => graph.nodes || [], [graph.nodes]);
  const positions = useMemo(() => {
    const width = 760;
    const columns = 4;
    return Object.fromEntries(graphNodes.map((node, index) => [
      node.id,
      { x: 54 + (index % columns) * 218, y: 38 + Math.floor(index / columns) * 52, node },
    ]));
  }, [graphNodes]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark">◈</span><span>CS2 COACH</span><small>TACTICAL INTELLIGENCE CONSOLE</small></div>
        <div className="top-status"><span className="pulse" /> API 8001 <span className="divider" /> GraphRAG online</div>
      </header>

      <main className="page-grid">
        <section className="hero">
          <div><p className="eyebrow">MATCH REVIEW / GRAPH-ENHANCED</p><h1>把 Demo 变成<br /><em>可执行的战术判断。</em></h1><p className="hero-copy">上传一场比赛，观察 Supervisor、Milvus RAG 与 GraphRAG 如何共同生成带证据的职业级复盘。</p></div>
          <div className="hero-orbit"><span>DEMO</span><span>RAG</span><span>GRAPH</span><b>CS2</b></div>
        </section>

        <section className="control-card card">
          <div className="section-heading"><div><p className="eyebrow">01 / ANALYZE</p><h2>提交比赛 Demo</h2></div><span className="chip">ASYNC PIPELINE</span></div>
          <form onSubmit={handleSubmit} className="upload-form">
            <label className={`dropzone ${file ? "has-file" : ""}`}>
              <input type="file" accept=".dem" onChange={(event) => setFile(event.target.files?.[0] || null)} />
              <span className="drop-icon">↑</span><strong>{file ? file.name : "拖入 .dem 文件，或点击选择"}</strong><small>{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB · ready` : "单文件上传 · 后端 Celery 异步解析"}</small>
            </label>
            <div className="form-row"><label>分析模式<select value={mode} onChange={(event) => setMode(event.target.value)}><option value="demo_forensic">Demo Forensic · 完整复盘</option><option value="tactical_comparison">Tactical Comparison · 战术对照</option><option value="player_coaching">Player Coaching · 个人训练</option></select></label><button className="primary-button" disabled={busy || !file}>{busy ? "提交中…" : "开始分析  ↗"}</button></div>
          </form>
          {task && <div className="task-line"><span className={`status-dot ${task.status === "SUCCESS" ? "success" : task.status === "FAILURE" ? "danger" : ""}`} />任务 {task.task_id} · {statusLabel(task.status)}</div>}
        </section>

        <section className="flow-card card"><div className="section-heading"><div><p className="eyebrow">02 / ORCHESTRATION</p><h2>Agent 执行链</h2></div><span className="mono">{task?.status || "IDLE"}</span></div><div className="flow-track">{FLOW.map((item, index) => <div className={`flow-step ${task?.status === "SUCCESS" || (task && index < 4) ? "active" : ""}`} key={item}><span>{String(index + 1).padStart(2, "0")}</span><b>{item}</b>{index < FLOW.length - 1 && <i />}</div>)}</div></section>

        <section className="metrics-grid"><Metric label="TOTAL ROUNDS" value={metrics.rounds_total} suffix=" rounds" /><Metric label="KILLS" value={metrics.kills_total} /><Metric label="FIRST KILLS" value={metrics.first_kills_total} accent /><Metric label="VERIFIER" value={analysis ? analysis.verification_report?.status || "review" : "—"} text /></section>

        <section className="report-card card"><div className="section-heading"><div><p className="eyebrow">03 / COACHING REPORT</p><h2>Analyst × Coach</h2></div><span className="chip">EVIDENCE-BOUND</span></div><div className="report-columns"><ReportBlock title="ANALYST / 发生了什么" text={analysis?.analyst_report} empty="提交 Demo 后，这里显示确定性指标与数据报告。" /><ReportBlock title="COACH / 应该怎么做" text={analysis?.coach_advice} empty="Coach 会基于指标和 [E#] 证据生成训练建议。" /></div></section>

        <section className="graph-card card"><div className="section-heading"><div><p className="eyebrow">04 / GRAPH RAG</p><h2>战术关系图谱</h2></div><div className="stats-inline"><span>{formatNumber(graphStats.nodes)} nodes</span><span>{formatNumber(graphStats.edges)} edges</span><span>{formatNumber(graphStats.communities)} communities</span></div></div><div className="graph-toolbar"><select value={map} onChange={(event) => setMap(event.target.value)}>{maps.map((item) => <option key={item}>{item}</option>)}</select><form onSubmit={handleSearch}><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索社区摘要与职业模式…" /><button>Global Search</button></form></div><div className="graph-layout"><GraphCanvas positions={positions} edges={graph.edges || []} /><div className="search-results">{searchResults.length ? searchResults.map((item) => <article key={item.source_id}><div className="result-meta">{item.metadata?.community_id} · {Number(item.score || 0).toFixed(2)}</div><p>{item.content}</p></article>) : <div className="empty-search">输入问题，检索 {map} 的社区摘要。<br /><small>结果保留回合来源 ID，可继续追溯到 Local Search。</small></div>}</div></div></section>

        <section className="evidence-card card"><div className="section-heading"><div><p className="eyebrow">05 / SOURCES</p><h2>证据引用</h2></div><span className="mono">{analysis?.retrieval_evidence?.length || 0} HITS</span></div><div className="evidence-list">{(analysis?.retrieval_evidence || []).slice(0, 8).map((item, index) => <article key={item.source_id || index}><span className="evidence-id">E{index + 1}</span><div><div className="result-meta">{item.metadata?.tactic_type} · {item.metadata?.map} · R{item.metadata?.round_number || "—"}</div><p>{item.content}</p></div></article>)}{!analysis?.retrieval_evidence?.length && <div className="empty-search">完成一次分析后，这里会列出 Milvus 与 GraphRAG 的可追溯证据。</div>}</div></section>
      </main>
      {error && <button className="error-toast" onClick={() => setError("")}>{error} ×</button>}
    </div>
  );
}

function Metric({ label, value, suffix = "", accent = false, text = false }) { return <article className={`metric ${accent ? "accent" : ""}`}><span>{label}</span><strong className={text ? "metric-text" : ""}>{text ? value : formatNumber(value)}<small>{text ? "" : suffix}</small></strong></article>; }

function ReportBlock({ title, text, empty }) { return <article className="report-block"><div className="block-label">{title}</div><div className="report-text">{text || <span className="placeholder">{empty}</span>}</div></article>; }

function GraphCanvas({ positions, edges }) { return <div className="graph-canvas"><svg viewBox="0 0 900 320" role="img" aria-label="CS2 tactical graph"><g className="edges">{edges.map((edge, index) => { const from = positions[edge.source]; const to = positions[edge.target]; return from && to ? <line key={index} x1={from.x} y1={from.y} x2={to.x} y2={to.y} /> : null; })}</g><g>{Object.values(positions).map(({ x, y, node }) => <g className={`graph-node node-${node.type}`} key={node.id} transform={`translate(${x}, ${y})`}><circle r="17" /><text x="25" y="4">{node.label?.slice(0, 24)}</text><title>{node.id}</title></g>)}</g></svg><div className="legend"><span><i className="legend-match" />match/map</span><span><i className="legend-round" />round</span><span><i className="legend-event" />event</span></div></div>; }

createRoot(document.getElementById("root")).render(<App />);
