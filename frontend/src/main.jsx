import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  compareGraphTeams,
  getGraphMaps,
  getGraphPlayers,
  getGraphStats,
  getPlayerProfile,
  getSubgraph,
  getTeamTactics,
  getTask,
  searchGraph,
  uploadDemo,
} from "./api";
import "./styles.css";

const FLOW = ["Supervisor", "Tools", "Router", "RAG + Graph", "Critique", "Analyst", "Coach", "Verifier"];
const FEATURED_TEAMS = ["Falcons", "Spirit", "Vitality", "FURIA", "MOUZ"];
const TACTIC_COLUMNS = [
  ["OPENING_DUEL", "首杀回合"],
  ["TRADE_KILL", "补枪"],
  ["UTILITY_BURST", "道具协同"],
  ["EXECUTE_CANDIDATE", "爆弹候选"],
  ["POST_PLANT", "下包后"],
  ["RETAKE_CONTACT", "回防接触"],
];

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
  const [map, setMap] = useState("");
  const [graphStats, setGraphStats] = useState({});
  const [graph, setGraph] = useState({ nodes: [], edges: [] });
  const [query, setQuery] = useState("猎鹰 Dust2 T侧首杀后胜率");
  const [searchResults, setSearchResults] = useState([]);
  const [coachBrief, setCoachBrief] = useState(null);
  const [teamComparison, setTeamComparison] = useState([]);
  const [playerTeam, setPlayerTeam] = useState(FEATURED_TEAMS[0]);
  const [players, setPlayers] = useState([]);
  const [selectedPlayerId, setSelectedPlayerId] = useState("");
  const [playerProfile, setPlayerProfile] = useState(null);
  const [tacticMap, setTacticMap] = useState("");
  const [tacticSide, setTacticSide] = useState("");
  const [tacticOpponent, setTacticOpponent] = useState("");
  const [tacticProfile, setTacticProfile] = useState(null);

  const analysis = task?.status === "SUCCESS" ? task.result?.analysis || task.result : null;
  const metrics = analysis?.metrics || {};

  useEffect(() => {
    Promise.all([getGraphMaps(), getGraphStats(), compareGraphTeams(FEATURED_TEAMS)])
      .then(([mapData, stats, comparison]) => {
        setMaps(mapData.maps || []);
        setGraphStats(stats);
        setTeamComparison(comparison.teams || []);
      })
      .catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    getGraphPlayers(playerTeam)
      .then((data) => {
        const nextPlayers = data.players || [];
        setPlayers(nextPlayers);
        setSelectedPlayerId(nextPlayers[0]?.player_id || "");
      })
      .catch((reason) => setError(reason.message));
  }, [playerTeam]);

  useEffect(() => {
    if (!selectedPlayerId) {
      setPlayerProfile(null);
      return;
    }
    getPlayerProfile(selectedPlayerId)
      .then((data) => setPlayerProfile(data.profile || null))
      .catch((reason) => setError(reason.message));
  }, [selectedPlayerId]);

  useEffect(() => {
    getTeamTactics(playerTeam, {
      mapName: tacticMap, side: tacticSide, opponent: tacticOpponent,
    })
      .then((data) => setTacticProfile(data.profile || null))
      .catch((reason) => setError(reason.message));
  }, [playerTeam, tacticMap, tacticSide, tacticOpponent]);

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
      setCoachBrief(response.answer || null);
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

        <section className="graph-card card"><div className="section-heading"><div><p className="eyebrow">04 / GRAPH RAG</p><h2>战术关系图谱</h2></div><div className="stats-inline"><span>{formatNumber(graphStats.nodes)} nodes</span><span>{formatNumber(graphStats.edges)} edges</span><span>{formatNumber(graphStats.tactical_sequences)} sequences</span><span>{formatNumber(graphStats.communities)} communities</span></div></div><div className="graph-toolbar"><select value={map} onChange={(event) => setMap(event.target.value)}><option value="">All maps</option>{maps.map((item) => <option key={item}>{item}</option>)}</select><form onSubmit={handleSearch}><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：猎鹰 Dust2 T侧首杀后胜率" /><button>Ask Graph</button></form></div><div className="graph-layout"><GraphCanvas positions={positions} edges={graph.edges || []} /><div className="search-results">{coachBrief && <CoachBrief brief={coachBrief} />}{searchResults.length ? searchResults.map((item) => <article key={item.source_id} className="raw-evidence"><div className="result-meta">{item.metadata?.community_id || item.metadata?.tactic_type} · {Number(item.score || 0).toFixed(2)}</div><p>{item.content}</p></article>) : !coachBrief && <div className="empty-search">输入战队、地图、阵营或对手，检索结构化战术画像与社区摘要。<br /><small>结果保留回合来源 ID，可继续追溯到 Local Search。</small></div>}</div></div></section>

        <section className="analytics-card card">
          <div className="section-heading"><div><p className="eyebrow">05 / CROSS-MATCH INTELLIGENCE</p><h2>选手画像 × 五队战术对比</h2></div><span className="chip">PER 100 ROUNDS</span></div>
          <div className="analytics-layout">
            <div className="player-pane">
              <div className="analytics-controls">
                <label>战队<select value={playerTeam} onChange={(event) => { setPlayerTeam(event.target.value); setTacticMap(""); setTacticSide(""); setTacticOpponent(""); }}>{FEATURED_TEAMS.map((item) => <option key={item}>{item}</option>)}</select></label>
                <label>选手<select value={selectedPlayerId} onChange={(event) => setSelectedPlayerId(event.target.value)}>{players.map((item) => <option key={item.player_id} value={item.player_id}>{item.name}</option>)}</select></label>
              </div>
              {playerProfile ? <PlayerProfile profile={playerProfile} /> : <div className="empty-search">等待本地图谱返回选手画像。</div>}
            </div>
            <div className="team-pane">
              <div className="result-meta table-title">战术序列频率 / 每 100 回合</div>
              <div className="comparison-scroll"><table className="comparison-table"><thead><tr><th>TEAM</th><th>SAMPLE</th>{TACTIC_COLUMNS.map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead><tbody>{teamComparison.map((team) => <tr key={team.team}><td><strong>{team.team}</strong></td><td>{team.sample_size.matches}M · {team.sample_size.maps} maps<br /><small>{team.sample_size.rounds} rounds</small></td>{TACTIC_COLUMNS.map(([key]) => <td key={key}>{Number(team.labels[key]?.per_100_rounds || 0).toFixed(1)}</td>)}</tr>)}</tbody></table></div>
              <p className="method-note">基于事件事实和确定性 silver labels；爆弹候选为弱监督标签。用于描述样本，不直接推断战术因果。</p>
            </div>
            <TacticalDrilldown profile={tacticProfile} map={tacticMap} side={tacticSide} opponent={tacticOpponent} onMap={setTacticMap} onSide={setTacticSide} onOpponent={setTacticOpponent} />
          </div>
        </section>

        <section className="evidence-card card"><div className="section-heading"><div><p className="eyebrow">06 / SOURCES</p><h2>证据引用</h2></div><span className="mono">{analysis?.retrieval_evidence?.length || 0} HITS</span></div><div className="evidence-list">{(analysis?.retrieval_evidence || []).slice(0, 8).map((item, index) => <article key={item.source_id || index}><span className="evidence-id">E{index + 1}</span><div><div className="result-meta">{item.metadata?.tactic_type} · {item.metadata?.map} · R{item.metadata?.round_number || "—"}</div><p>{item.content}</p></div></article>)}{!analysis?.retrieval_evidence?.length && <div className="empty-search">完成一次分析后，这里会列出 Milvus 与 GraphRAG 的可追溯证据。</div>}</div></section>
      </main>
      {error && <button className="error-toast" onClick={() => setError("")}>{error} ×</button>}
    </div>
  );
}

function Metric({ label, value, suffix = "", accent = false, text = false }) { return <article className={`metric ${accent ? "accent" : ""}`}><span>{label}</span><strong className={text ? "metric-text" : ""}>{text ? value : formatNumber(value)}<small>{text ? "" : suffix}</small></strong></article>; }

function ReportBlock({ title, text, empty }) { return <article className="report-block"><div className="block-label">{title}</div><div className="report-text">{text || <span className="placeholder">{empty}</span>}</div></article>; }

function CoachBrief({ brief }) { return <article className="coach-brief"><div className="brief-head"><div><div className="result-meta">DETERMINISTIC COACH BRIEF</div><h3>{brief.title}</h3></div><span className="chip">样本可信度 · {brief.sample_confidence}</span></div><p className="brief-summary">{brief.summary}</p><div className="brief-section"><b>数据判读</b>{brief.findings.map((item) => <p key={item}>{item}</p>)}</div><div className="brief-section action"><b>训练重点</b>{brief.actions.map((item) => <p key={item}>{item}</p>)}</div><p className="brief-caveat">{brief.caveat}</p>{brief.sources.length > 0 && <div className="brief-sources">{brief.sources.map((item) => <span key={item.id}>[{item.id}] {item.round_id}</span>)}</div>}</article>; }

function PlayerProfile({ profile }) {
  const combat = profile.combat || {};
  const rates = profile.rates_per_100_rounds || {};
  return <div className="player-profile"><div className="player-title"><div><strong>{profile.name}</strong><span>{profile.team}</span></div><small>{profile.sample_size.matches} matches · {profile.sample_size.maps} maps · {profile.sample_size.rounds} rounds</small></div><div className="profile-metrics"><ProfileMetric label="K/D" value={combat.kd_ratio ?? "—"} /><ProfileMetric label="OPENING WIN" value={combat.opening_duel_win_pct == null ? "—" : `${combat.opening_duel_win_pct}%`} /><ProfileMetric label="KILLS / 100R" value={rates.kills} /><ProfileMetric label="TRADES / 100R" value={rates.trade_kills} /></div><div className="tactic-chips">{TACTIC_COLUMNS.map(([key, label]) => <span key={key}>{label}<b>{profile.tactical_participation?.[key] || 0}</b></span>)}</div><div className="source-hint">SOURCE · {profile.source_round_ids?.[0] || "unavailable"}</div></div>;
}

function ProfileMetric({ label, value }) { return <div><span>{label}</span><strong>{value}</strong></div>; }

function TacticalDrilldown({ profile, map, side, opponent, onMap, onSide, onOpponent }) {
  if (!profile) return <div className="tactic-drilldown empty-search">等待战术切片数据。</div>;
  const conversions = profile.conversions || {};
  const leader = (key) => profile.role_leaders?.[key]?.[0];
  return <div className="tactic-drilldown"><div className="drilldown-head"><div><div className="result-meta">CONTEXTUAL TACTICAL SLICE</div><h3>{profile.team} · {map || "ALL MAPS"} · {side || "BOTH SIDES"}</h3></div><small>{profile.sample_size.matches} matches · {profile.sample_size.maps} maps · {profile.sample_size.rounds} rounds</small></div><div className="drilldown-filters"><select value={map} onChange={(event) => onMap(event.target.value)}><option value="">全部地图</option>{profile.available_filters.maps.map((item) => <option key={item}>{item}</option>)}</select><select value={side} onChange={(event) => onSide(event.target.value)}><option value="">T + CT</option><option value="T">T</option><option value="CT">CT</option></select><select value={opponent} onChange={(event) => onOpponent(event.target.value)}><option value="">全部对手</option>{profile.available_filters.opponents.map((item) => <option key={item}>{item}</option>)}</select></div><div className="conversion-grid"><ConversionMetric label="ROUND WIN" value={profile.outcomes.round_win_pct} count={profile.sample_size.decided_rounds} /><ConversionMetric label="OPENING → WIN" {...conversionProps(conversions.opening_won)} /><ConversionMetric label="OPENING LOSS → WIN" {...conversionProps(conversions.opening_lost_recovery)} /><ConversionMetric label="TRADE ROUND" {...conversionProps(conversions.trade_round)} /><ConversionMetric label="POST-PLANT" {...conversionProps(conversions.post_plant)} /><ConversionMetric label="RETAKE CONTACT" {...conversionProps(conversions.retake_contact)} /><ConversionMetric label="EXECUTE CANDIDATE" {...conversionProps(conversions.execute_candidate)} /></div><div className="role-strip"><RoleLeader label="OPENING" leader={leader("opening_kills")} /><RoleLeader label="TRADE" leader={leader("trade_kills")} /><RoleLeader label="UTILITY" leader={leader("utility_burst_participation")} />{profile.site_breakdown.map((item) => <div key={item.site}><span>SITE {item.site}</span><strong>{formatPercent(item.round_win_pct)}</strong><small>{item.rounds} tagged rounds</small></div>)}</div><div className="source-hint">SOURCE · {profile.source_round_ids?.[0] || "no rounds for this slice"}</div></div>;
}

function conversionProps(value = {}) { return { value: value.round_win_pct, count: value.opportunities }; }
function formatPercent(value) { return value == null ? "—" : `${Number(value).toFixed(1)}%`; }
function ConversionMetric({ label, value, count }) { return <div><span>{label}</span><strong>{formatPercent(value)}</strong><small>{count || 0} opportunities</small></div>; }
function RoleLeader({ label, leader }) { return <div><span>{label} LEADER</span><strong>{leader?.name || "—"}</strong><small>{leader ? `${leader.count} · ${formatPercent(leader.share_pct)}` : "no observation"}</small></div>; }

function GraphCanvas({ positions, edges }) { return <div className="graph-canvas"><svg viewBox="0 0 900 320" role="img" aria-label="CS2 tactical graph"><g className="edges">{edges.map((edge, index) => { const from = positions[edge.source]; const to = positions[edge.target]; return from && to ? <line key={index} x1={from.x} y1={from.y} x2={to.x} y2={to.y} /> : null; })}</g><g>{Object.values(positions).map(({ x, y, node }) => <g className={`graph-node node-${node.type}`} key={node.id} transform={`translate(${x}, ${y})`}><circle r="17" /><text x="25" y="4">{node.label?.slice(0, 24)}</text><title>{node.id}</title></g>)}</g></svg><div className="legend"><span><i className="legend-match" />match/map</span><span><i className="legend-round" />round</span><span><i className="legend-tactic" />tactical sequence</span><span><i className="legend-event" />event</span></div></div>; }

createRoot(document.getElementById("root")).render(<App />);
