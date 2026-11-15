/**
 * 品牌、导航、角色权限与枚举文案（前端唯一定义处）。
 * 后端对应：backend/src/constants/{roles,enums}.py；README §11 列出全部出现位置。
 */
export const BRAND = {
  short: 'anomalyattr',
  title: '门店指标异常归因与量价下钻',
  org: '蓝湾酒店集团 · 经营分析组',
  edition: 'NIGHT AUDIT · 交接本 2026',
  subtitle: '120 家门店 · 日报异常 → 贡献分解 → 维度归因 → 周会结论',
  loginLead: '夜审交接的不只是数字，而是「跌在哪家店、跌在哪个渠道、是量还是价」。',
  loginPoints: [
    ['01', '滚动 28 天稳健基线（median + MAD），周末单独分层，避免单日抖动误报。'],
    ['02', 'Δ营收按 LMDI 拆成房价 / 出租率 / 可售房量三段，残差照样写清。'],
    ['03', '门店 / 渠道 / 房型三维贡献下钻，结论一句话，可导出给区域经理。'],
  ],
  shift: '夜班 22:30 — 次日 07:30',
  handNote: '交接提醒：OTA 侧昨日 23:00 起限流 40 分钟，11-03 外滩店营收已确认偏低，明早周会要讲。',
};

export const NAV = [
  { to: '#/overview', no: '01', label: '总览', permission: 'overview:read' },
  { to: '#/stores', no: '02', label: '门店与指标', permission: 'store:read' },
  { to: '#/anomalies', no: '03', label: '异常清单', permission: 'anomaly:read' },
  { to: '#/attribution', no: '04', label: '归因下钻', permission: 'anomaly:read' },
  { to: '#/reports', no: '05', label: '报告与导出', permission: 'report:read' },
  { to: '#/audit', no: '06', label: '审计日志', permission: 'audit:read' },
];

export const ROLE_LABELS = {
  admin: '经营管理员',
  analyst: '经营分析师',
  viewer: '区域只读',
};

export const PERMISSIONS = {
  admin: [
    'overview:read', 'store:read', 'store:write', 'metric:read', 'anomaly:read', 'anomaly:review',
    'run:read', 'run:create', 'report:read', 'report:generate', 'export:read', 'audit:read',
  ],
  analyst: [
    'overview:read', 'store:read', 'metric:read', 'anomaly:read', 'anomaly:review',
    'run:read', 'run:create', 'report:read', 'export:read',
  ],
  viewer: ['overview:read', 'store:read', 'metric:read', 'anomaly:read', 'run:read', 'report:read'],
};

export const ENUMS = {
  severity: { high: '高', medium: '中', low: '低' },
  review: { pending: '待处理', confirmed: '已确认', dismissed: '已排除' },
  metric: { rev: '营收', adr: '平均房价 ADR', occ: '出租率 OCC' },
  direction: { up: '上行', down: '下行' },
  channel: { ota: 'OTA 渠道', direct: '直连/官网', corp: '协议/团队' },
  storeStatus: { open: '营业中', renovating: '局部改造', closed: '暂停营业' },
  runStatus: { queued: '排队中', running: '执行中', success: '成功', partial: '部分成功', failed: '失败' },
  trigger: { manual: '手动', schedule: '定时', seed: '初始化' },
  reportKind: { daily: '日报', weekly: '周报' },
  reportStatus: { draft: '草稿', published: '已发布' },
  factor: { adr: '房价 ADR', occ: '出租率 OCC', rooms: '可售房量' },
};

export function can(role, permission) {
  return (PERMISSIONS[role] || []).includes(permission);
}

export function badgeTone(severity) {
  return { high: 'high', medium: 'medium', low: 'low' }[severity] || 'info';
}

export function reviewTone(status) {
  return { pending: 'pending warn', confirmed: 'ok', dismissed: 'danger' }[status] || 'info';
}

export function fmtMoney(value) {
  const number = Number(value || 0);
  const sign = number < 0 ? '-' : '';
  const abs = Math.abs(number);
  if (abs >= 10000) return `${sign}${(abs / 10000).toFixed(2)} 万`;
  return `${sign}${abs.toFixed(0)} 元`;
}

export function fmtPct(value, digits = 1) {
  if (value === null || value === undefined) return '—';
  return `${(Number(value) * 100).toFixed(digits)}%`;
}
