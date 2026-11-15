/** 无框架 UI 组件：表格 / 抽屉 / 过滤条 / 水位条 / 序列图 / 交接批注 / toast。 */
import { ENUMS, fmtMoney, fmtPct } from './config.js';

export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

export function fmtTime(iso) {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return esc(iso);
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

export function badge(tone, text) {
  return `<span class="badge ${esc(tone)}">${esc(text)}</span>`;
}

export function statStrip(items) {
  return `<div class="stat-strip">${items
    .map(
      (item) => `<div class="stat ${item.tone || ''}">
        <span class="k">${esc(item.label)}</span>
        <span class="v">${item.raw ? item.value : esc(item.value)}</span>
        <span class="hint">${esc(item.hint || '')}</span>
      </div>`,
    )
    .join('')}</div>`;
}

export function emptyState({ title, hint, actionText, actionId }) {
  return `<div class="empty" data-testid="empty-state">
    <div class="mark">${esc(title)}</div>
    <p>${esc(hint || '')}</p>
    ${actionText ? `<button class="btn ghost" id="${esc(actionId || 'empty-action')}">${esc(actionText)}</button>` : ''}
  </div>`;
}

export function errorBox(message, retryId = 'retry-btn') {
  return `<div class="error-box"><span>${esc(message)}</span><button class="btn sm ghost" id="${esc(retryId)}">重试</button></div>`;
}

/** 业务表格组件：门店 / 异常 / 报告三页共用。 */
export function table({ columns, rows, rowId, empty }) {
  if (!rows || rows.length === 0) return emptyState(empty || { title: '暂无记录', hint: '调整筛选条件或先发起一次检测。' });
  const head = columns.map((col) => `<th class="${esc(col.align || '')}">${esc(col.label)}</th>`).join('');
  const body = rows
    .map(
      (row) => `<tr data-id="${esc(row.id)}" ${rowId ? `id="${esc(rowId(row))}"` : ''}>
        ${columns.map((col) => `<td class="${esc(col.className || '')}">${col.render ? col.render(row) : esc(row[col.key])}</td>`).join('')}
      </tr>`,
    )
    .join('');
  return `<div class="table-wrap"><table class="data"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

/** 共用过滤条组件：字段 + 变更回调。 */
export function filterBar({ id = 'filter-bar', fields, action }) {
  return `<div class="filter-bar" id="${esc(id)}" data-testid="${esc(id)}">
    ${fields
      .map((item) =>
        field({
          label: item.label,
          name: item.name,
          value: item.value,
          placeholder: item.placeholder,
          options: item.options,
        }),
      )
      .join('')}
    <div class="spacer"></div>
    ${action || ''}
  </div>`;
}

export function bindFilters(root, id, onChange) {
  const bar = root.querySelector(`#${id}`);
  if (!bar) return;
  bar.addEventListener('change', () => {
    const data = {};
    bar.querySelectorAll('[name]').forEach((node) => {
      data[node.name] = node.value;
    });
    onChange(data);
  });
  bar.querySelectorAll('input[type=text],input[type=search]').forEach((node) => {
    node.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      const data = {};
      bar.querySelectorAll('[name]').forEach((item) => {
        data[item.name] = item.value;
      });
      onChange(data);
    });
  });
}

export function drawer({ title, subtitle, body, footer }) {
  const backdrop = document.createElement('div');
  backdrop.className = 'drawer-backdrop';
  backdrop.innerHTML = `<aside class="drawer" role="dialog" aria-modal="true">
    <div class="drawer-head">
      <div>
        <h2>${esc(title)}</h2>
        <div class="mono muted">${esc(subtitle || '')}</div>
      </div>
      <button class="btn sm ghost" data-close>关闭</button>
    </div>
    <div class="drawer-body">${body}</div>
    ${footer ? `<div class="drawer-foot">${footer}</div>` : ''}
  </aside>`;
  const close = () => {
    backdrop.remove();
    document.removeEventListener('keydown', onKey);
  };
  const onKey = (event) => {
    if (event.key === 'Escape') close();
  };
  backdrop.addEventListener('click', (event) => {
    if (event.target === backdrop || event.target.closest('[data-close]')) close();
  });
  document.addEventListener('keydown', onKey);
  document.body.appendChild(backdrop);
  return { root: backdrop, close };
}

export function kv(items) {
  return `<dl class="kv">${items
    .map(([key, value]) => `<dt>${esc(key)}</dt><dd>${value === undefined || value === null ? '—' : value}</dd>`)
    .join('')}</dl>`;
}

export function barList(items, tone = '') {
  const max = Math.max(1, ...items.map((item) => item.count));
  return `<div class="bars">${items
    .map(
      (item) => `<div class="bar-row">
        <span>${esc(item.label)}</span>
        <div class="bar-track"><div class="bar-fill ${esc(tone)}" style="width:${Math.round((item.count / max) * 100)}%"></div></div>
        <span class="mono">${esc(item.count)}</span>
      </div>`,
    )
    .join('')}</div>`;
}

/** 营收日序列折线（SVG，零依赖）：标注异常点。 */
export function seriesChart(points, { anomalyDate, height = 132 } = {}) {
  if (!points || points.length < 2) return emptyState({ title: '没有可画的序列', hint: '先确认该门店已有指标点。' });
  const width = 640;
  const values = points.map((point) => point.revenue);
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const stepX = width / (points.length - 1);
  const coords = points.map((point, index) => {
    const x = index * stepX;
    const y = height - 8 - ((point.revenue - min) / span) * (height - 26);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const hit = points.findIndex((point) => point.date === anomalyDate);
  return `<figure class="series">
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="营收日序列">
      <polyline points="${coords.join(' ')}" fill="none" stroke="var(--ink-soft)" stroke-width="1.6" />
      ${
        hit >= 0
          ? `<circle cx="${(hit * stepX).toFixed(1)}" cy="${coords[hit].split(',')[1]}" r="5" fill="var(--danger)" />
             <line x1="${(hit * stepX).toFixed(1)}" y1="0" x2="${(hit * stepX).toFixed(1)}" y2="${height}" stroke="var(--danger)" stroke-dasharray="3 3" stroke-width="1" />`
          : ''
      }
    </svg>
    <figcaption class="mono muted">${esc(points[0].date)} → ${esc(points[points.length - 1].date)} · 峰值 ${fmtMoney(max)} · 谷值 ${fmtMoney(min)}</figcaption>
  </figure>`;
}

/** 量价分解水位条：正负双向，标出占比。 */
export function factorBars({ parts, shares }) {
  const keys = ['adr', 'occ', 'rooms'];
  const max = Math.max(1, ...keys.map((key) => Math.abs(parts[key] || 0)));
  return `<div class="factors">${keys
    .map((key) => {
      const value = parts[key] || 0;
      const width = Math.round((Math.abs(value) / max) * 100);
      const share = shares[key];
      return `<div class="factor-row">
        <span class="factor-label">${esc(ENUMS.factor[key])}</span>
        <div class="factor-track">
          <div class="factor-fill ${value < 0 ? 'down' : 'up'}" style="width:${width}%"></div>
        </div>
        <span class="mono factor-value">${fmtMoney(value)}</span>
        <span class="mono factor-share" data-testid="share-${key}">${share === null || share === undefined ? '—' : fmtPct(share)}</span>
      </div>`;
    })
    .join('')}</div>`;
}

/** 维度贡献表：门店 / 渠道 / 房型共用。 */
export function contributionTable(block) {
  const rows = (block.rows || []).slice(0, 6);
  if (!rows.length) return emptyState({ title: '该维度没有可比数据', hint: '窗口内缺少同区域/渠道数据。' });
  return `<div class="table-wrap"><table class="data compact">
    <thead><tr><th>分组</th><th class="right">当期</th><th class="right">基线</th><th class="right">变动</th><th class="right">贡献占比</th></tr></thead>
    <tbody>${rows
      .map(
        (row) => `<tr><td>${esc(row.key)}</td>
          <td class="num">${fmtMoney(row.current)}</td>
          <td class="num">${fmtMoney(row.base)}</td>
          <td class="num ${row.delta < 0 ? 'neg' : 'pos'}">${fmtMoney(row.delta)}</td>
          <td class="num">${row.contribution === null || row.contribution === undefined ? '—' : fmtPct(row.contribution)}</td></tr>`,
      )
      .join('')}</tbody></table></div>`;
}

export function handNote(text, sign = '值班经理 · 顾青') {
  return `<aside class="hand-note" data-testid="hand-note">
    <p>${esc(text)}</p>
    <span class="sign">${esc(sign)}</span>
  </aside>`;
}

export function field({ label, name, type = 'text', value = '', placeholder = '', options = null, attrs = '' }) {
  const control = options
    ? `<select name="${esc(name)}" id="${esc(name)}" ${attrs}>${options
        .map((opt) => `<option value="${esc(opt.value)}" ${String(opt.value) === String(value) ? 'selected' : ''}>${esc(opt.label)}</option>`)
        .join('')}</select>`
    : `<input name="${esc(name)}" id="${esc(name)}" type="${esc(type)}" value="${esc(value)}" placeholder="${esc(placeholder)}" ${attrs} />`;
  return `<div class="field"><label for="${esc(name)}">${esc(label)}</label>${control}</div>`;
}

export function toast(message, tone = '') {
  const stack = document.getElementById('toast-stack');
  const node = document.createElement('div');
  node.className = `toast ${tone}`;
  node.textContent = message;
  stack.appendChild(node);
  setTimeout(() => node.remove(), 3600);
}

export function errorMessage(err) {
  if (!err) return '未知错误';
  if (err.code === 'FORBIDDEN') return '当前角色没有这个操作的权限';
  if (err.code === 'VALIDATION') return err.message || '参数不合法';
  return err.message || '请求失败';
}
