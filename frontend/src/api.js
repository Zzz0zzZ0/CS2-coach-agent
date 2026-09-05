async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || data.error || `Request failed: ${response.status}`);
  }
  return data;
}

export function uploadDemo(file, analysisMode) {
  const body = new FormData();
  body.append("file", file);
  body.append("analysis_mode", analysisMode);
  return request("/api/upload-demo", { method: "POST", body });
}

export function getTask(taskId) {
  return request(`/api/tasks/${encodeURIComponent(taskId)}`);
}

export function getGraphMaps() {
  return request("/api/graph/maps");
}

export function getGraphStats() {
  return request("/api/graph/stats");
}

export function getGraphPlayers(team, limit = 10) {
  const params = new URLSearchParams({ team, limit: String(limit) });
  return request(`/api/graph/players?${params}`);
}

export function getPlayerProfile(playerId) {
  return request(`/api/graph/players/${encodeURIComponent(playerId)}`);
}

export function compareGraphTeams(teams) {
  const params = new URLSearchParams({ teams: teams.join(",") });
  return request(`/api/graph/teams/compare?${params}`);
}

export function getSubgraph(mapName) {
  const query = mapName ? `?map_name=${encodeURIComponent(mapName)}` : "";
  return request(`/api/graph/subgraph${query}`);
}

export function searchGraph(query, mapName) {
  const params = new URLSearchParams({ q: query, limit: "6" });
  if (mapName) params.set("map_name", mapName);
  return request(`/api/graph/search?${params}`);
}
