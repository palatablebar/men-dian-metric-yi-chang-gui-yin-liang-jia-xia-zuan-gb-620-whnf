import { api } from '../api.js';
import { ENUMS, badgeTone, can, fmtMoney, fmtPct, reviewTone } from '../config.js';
import { bindFilters, drawer, errorBox, errorMessage, esc, field, filterBar, fmtTime, kv, table, toast } from '../ui.js';

const state = { severity: '', status: '', metric_key: '', region: '', q: '', data: [] };

function openDetail(view, ctx, item) {
  const canReview = can(ctx.user.role, 'anomaly:review');
  const payload = item.payload || {};
  const { root, close } = drawer({
    title: `${item.store_name} · ${item.metric_date}`,
    subtitle: `${item.store_code} · ${item.metric_label} · 稳健 z ${item.robust_z.toFixed(2)}`,
    body: `${kv([
      ['严重度', `<span class="badge ${badgeTone(item.severity)}">${esc(item.severity_label)}</span>`],
      ['观测值', `<b>${fmtMoney(item.observed)}</b>`],
      ['稳健基线', fmtMoney(item.baseline)],
      ['MAD', item.mad.toFixed(2)],
      ['影响金额', `<span class="${item.impact_amount < 0 ? 'neg' : 'pos'}">${fmtMoney(item.impact_amount)}</span>`],
      ['方向', esc(item.direction_label)],
      ['处理状态', `<span class="badge ${reviewTone(item.status)}">${esc(item.status_label)}</span>`],
      ['复核人', esc(item.reviewer || '—')],
      ['复核备注', esc(item.review_note || '—')],
      ['基线窗口', `${esc(payload.window_start || '—')} → ${esc(payload.window_end || '—')}（${esc(payload.window_samples || 0)} 个同期样本）`],
    ])}
    <h3 class="sub-head">基线三元组 vs 当期三元组</h3>
    ${table({
      rows: [
        { id: 'base', k: '基线（窗口 median）', ...(payload.baseline_triple || {}) },
        { id: 'cur', k: '当期', ...(payload.current_triple || {}) },
      ],
      columns: [
        { key: 'k', label: '口径' },
        { key: 'adr', label: 'ADR', className: 'num', render: (row) => (row.adr ? Number(row.adr).toFixed(0) : '—') },
        { key: 'occ', label: 'OCC', className: 'num', render: (row) => (row.occ === undefined ? '—' : fmtPct(row.occ)) },
        { key: 'rooms', label: '可售房量', className: 'num', render: (row) => row.rooms ?? '—' },
        { key: 'revenue', label: '营收', className: 'num', render: (row) => (row.revenue ? fmtMoney(row.revenue) : '—') },
      ],
    })}`,
    footer: canReview
      ? `<form id="review-form" class="stack">
          ${field({ label: '处理结论', name: 'status', value: item.status, options: Object.entries(ENUMS.review).map(([value, label]) => ({ value, label })) })}
          ${field({ label: '结论备注', name: 'note', value: item.review_note || '', placeholder: '一句话写清原因与动作' })}
          <button class="btn accent" type="submit">保存结论</button>
        </form>`
      : '<span class="mono muted">只读角色可以查看，但不能写结论</span>',
  });
  root.querySelector('[data-go-attribution]')?.addEventListener('click', () => {
    location.hash = `#/attribution?anomaly_id=${item.id}`;
  });
  root.querySelector('#review-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      await api.anomalies.review(item.id, { status: form.status.value, note: form.note.value.trim() || null });
      toast('处理结论已保存');
      close();
      await anomaliesPage.render(view, ctx);
    } catch (err) {
      toast(errorMessage(err), 'err');
    }
  });
}

function openRun(view, ctx) {
  const { root, close } = drawer({
    title: '发起异常检测',
    subtitle: '算法 A：滚动 28 天 median + MAD，周末分层，同向 2 天',
    body: `<form id="run-form" class="stack">
      ${field({ label: '窗口天数', name: 'window', type: 'number', value: '28' })}
      ${field({ label: '触发阈值 |z|', name: 'threshold', type: 'number', value: '3.5' })}
      ${field({ label: '方向延续 |z_prev|', name: 'persist_z', type: 'number', value: '1.5' })}
      <p class="muted small">本次检测会对全部门店 × rev 指标重算，异常按（门店, 日期, 指标）幂等落库，已有结论不会被覆盖。</p>
      <div class="form-error" id="run-error"></div>
      <button class="btn accent" type="submit">开始检测</button>
    </form>`,
  });
  root.querySelector('#run-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    button.textContent = '检测中…';
    try {
      const run = await api.runs.create({
        window: Number(form.window.value),
        threshold: Number(form.threshold.value),
        persist_z: Number(form.persist_z.value),
        metrics: ['rev'],
        trigger: 'manual',
      });
      toast(`检测 ${run.run_no} 完成：命中 ${run.anomaly_count} 起`);
      close();
      await anomaliesPage.render(view, ctx);
    } catch (err) {
      root.querySelector('#run-error').textContent = errorMessage(err);
      button.disabled = false;
      button.textContent = '开始检测';
    }
  });
}

export const anomaliesPage = {
  async render(view, ctx) {
    if (ctx.query.store_id) state.storeId = ctx.query.store_id;
    if (ctx.query.severity) state.severity = ctx.query.severity;
    let data;
    let regions;
    try {
      [data, regions] = await Promise.all([
        api.anomalies.list({
          severity: state.severity,
          status: state.status,
          metric_key: state.metric_key,
          region: state.region,
          q: state.q,
          store_id: state.storeId,
          limit: 100,
        }),
        api.stores.regions(),
      ]);
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => anomaliesPage.render(view, ctx));
      return;
    }
    state.data = data.items;
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>异常清单 ${state.storeId ? `<span class="mono muted">· 门店 #${esc(state.storeId)}</span>` : ''}</h2>
          <div class="head-actions">
            <span class="meta">${data.total} 起</span>
            ${can(ctx.user.role, 'export:read') ? '<button class="btn sm ghost" id="export-anomalies">导出异常 CSV</button>' : ''}
            ${can(ctx.user.role, 'run:create') ? '<button class="btn sm accent" id="new-run">发起检测</button>' : ''}
          </div>
        </div>
        <div class="panel-body">
          ${filterBar({
            id: 'anomaly-filters',
            fields: [
              { label: '搜索门店', name: 'q', value: state.q, placeholder: '门店名 / 编码' },
              { label: '区域', name: 'region', value: state.region, options: [{ value: '', label: '全部' }, ...regions.items.map((item) => ({ value: item.region, label: item.region }))] },
              { label: '指标', name: 'metric_key', value: state.metric_key, options: [{ value: '', label: '全部' }, ...Object.entries(ENUMS.metric).map(([value, label]) => ({ value, label }))] },
              { label: '严重度', name: 'severity', value: state.severity, options: [{ value: '', label: '全部' }, ...Object.entries(ENUMS.severity).map(([value, label]) => ({ value, label }))] },
              { label: '处理状态', name: 'status', value: state.status, options: [{ value: '', label: '全部' }, ...Object.entries(ENUMS.review).map(([value, label]) => ({ value, label }))] },
            ],
          })}
        </div>
        ${table({
          rows: data.items,
          columns: [
            { key: 'store_name', label: '门店 / 日期', render: (row) => `<b>${esc(row.store_name)}</b><div class="mono muted">${esc(row.metric_date)} · ${esc(row.store_code)}</div>` },
            { key: 'metric_label', label: '指标' },
            { key: 'observed', label: '观测', className: 'num', render: (row) => fmtMoney(row.observed) },
            { key: 'baseline', label: '稳健基线', className: 'num', render: (row) => fmtMoney(row.baseline) },
            { key: 'robust_z', label: '稳健 z', className: 'num', render: (row) => `<span class="${row.robust_z < 0 ? 'neg' : 'pos'}">${row.robust_z.toFixed(2)}</span>` },
            { key: 'impact_amount', label: '影响金额', className: 'num', render: (row) => `<span class="${row.impact_amount < 0 ? 'neg' : 'pos'}">${fmtMoney(row.impact_amount)}</span>` },
            { key: 'severity', label: '等级', render: (row) => `<span class="badge ${badgeTone(row.severity)}">${esc(row.severity_label)}</span>` },
            { key: 'status', label: '处理', render: (row) => `<span class="badge ${reviewTone(row.status)}">${esc(row.status_label)}</span>` },
          ],
          empty: { title: '这个筛选下没有异常', hint: '清空筛选或发起一次检测。' },
        })}
      </section>`;
    bindFilters(view, 'anomaly-filters', (values) => {
      state.q = values.q.trim();
      state.region = values.region;
      state.metric_key = values.metric_key;
      state.severity = values.severity;
      state.status = values.status;
      anomaliesPage.render(view, ctx);
    });
    view.querySelectorAll('table.data tbody tr').forEach((row) => {
      row.addEventListener('click', () => {
        const item = state.data.find((entry) => String(entry.id) === row.dataset.id);
        if (item) openDetail(view, ctx, item);
      });
    });
    view.querySelector('#export-anomalies')?.addEventListener('click', async () => {
      try {
        await api.download('/api/exports/anomalies.csv', 'anomalies.csv');
        toast('已开始下载异常清单');
      } catch (err) {
        toast(errorMessage(err), 'err');
      }
    });
    view.querySelector('#new-run')?.addEventListener('click', () => openRun(view, ctx));
  },
};

export default anomaliesPage;
