import { session } from './store.js';

export class ApiError extends Error {
  constructor(message, code, status, detail) {
    super(message);
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

function buildQuery(query) {
  if (!query) return '';
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    params.set(key, value);
  });
  const text = params.toString();
  return text ? `?${text}` : '';
}

async function request(path, { method = 'GET', body, query } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const token = session.token();
  if (token) headers.Authorization = `Bearer ${token}`;
  let response;
  try {
    response = await fetch(`${path}${buildQuery(query)}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    throw new ApiError('网络不可达，请确认服务已启动', 'NETWORK', 0, null);
  }
  if (response.status === 401) {
    session.clear();
    if (location.hash !== '#/login') location.hash = '#/login';
    throw new ApiError('登录已过期，请重新登录', 'AUTH_MISSING', 401, null);
  }
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const message = payload?.message || `请求失败（${response.status}）`;
    throw new ApiError(message, payload?.code || 'INTERNAL', response.status, payload?.detail);
  }
  return payload;
}

async function download(path, filename) {
  const token = session.token();
  const response = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!response.ok) throw new ApiError('导出失败（可能没有导出权限）', 'EXPORT_FAILED', response.status, null);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  get: (path, query) => request(path, { query }),
  post: (path, body) => request(path, { method: 'POST', body }),
  patch: (path, body) => request(path, { method: 'PATCH', body }),
  download,
  // 领域实体入口（每个实体一个方法组，页面只通过这些方法访问后端）
  stores: {
    list: (query) => request('/api/stores', { query }),
    regions: () => request('/api/stores/regions'),
    get: (id) => request(`/api/stores/${id}`),
    series: (id, query) => request(`/api/stores/${id}/series`, { query }),
    create: (body) => request('/api/stores', { method: 'POST', body }),
    patch: (id, body) => request(`/api/stores/${id}`, { method: 'PATCH', body }),
  },
  metrics: {
    list: (query) => request('/api/metrics', { query }),
    channelSplit: (query) => request('/api/metrics/channel-split', { query }),
  },
  anomalies: {
    list: (query) => request('/api/anomalies', { query }),
    get: (id) => request(`/api/anomalies/${id}`),
    review: (id, body) => request(`/api/anomalies/${id}/review`, { method: 'PATCH', body }),
  },
  calendar: {
    list: (query) => request('/api/calendar', { query }),
    version: () => request('/api/calendar/version'),
    revisions: (query) => request('/api/calendar/revisions', { query }),
    forStore: (storeId) => request(`/api/calendar/store/${storeId}`),
    create: (body, query) => request('/api/calendar', { method: 'POST', body, query }),
    update: (id, body, query) => request(`/api/calendar/${id}`, { method: 'PATCH', body, query }),
    deactivate: (id) => request(`/api/calendar/${id}`, { method: 'DELETE' }),
    jobs: (query) => request('/api/calendar/jobs', { query }),
    resumeJob: (id) => request(`/api/calendar/jobs/${id}/resume`, { method: 'POST' }),
  },
  attributions: {
    forAnomaly: (id) => request(`/api/attributions/anomaly/${id}`),
    list: (query) => request('/api/attributions', { query }),
  },
  runs: {
    list: (query) => request('/api/runs', { query }),
    get: (id) => request(`/api/runs/${id}`),
    create: (body) => request('/api/runs', { method: 'POST', body }),
    resume: (id) => request(`/api/runs/${id}/resume`, { method: 'POST' }),
  },
  reports: {
    list: (query) => request('/api/reports', { query }),
    get: (id) => request(`/api/reports/${id}`),
    create: (body) => request('/api/reports', { method: 'POST', body }),
    publish: (id, body) => request(`/api/reports/${id}`, { method: 'PATCH', body }),
    reassess: (id) => request(`/api/reports/${id}/reassess`, { method: 'POST' }),
    impact: (query) => request('/api/reports/impact/invalidation', { query }),
  },
  audit: {
    list: (query) => request('/api/audit', { query }),
  },
  overview: {
    get: () => request('/api/overview'),
  },
};
