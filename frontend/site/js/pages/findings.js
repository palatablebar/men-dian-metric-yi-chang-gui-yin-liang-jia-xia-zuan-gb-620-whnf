import { api } from '../api.js';
import { ENUMS, badgeTone, can, reviewTone } from '../config.js';
import { drawer, errorBox, errorMessage, esc, field, fmtTime, kv, table, toast } from '../ui.js';

const state = { runId: '', severity: '', status: '', q: '' };

function openFinding(view, ctx, item) {
  const canReview = can(ctx.user.role, 'finding:review');
  const { root, close } = drawer({
    title: item.title,
    subtitle: `${item.key} · 运行 ${item.run_no || item.run_id}`,
    body: `${kv([
      ['等级', `<span class="badge ${badgeTone(item.severity)}">${esc(ENUMS.severity[item.severity] || item.severity)}</span>`],
      ['分数', `<span class="mono">${item.score.toFixed(1)}</span>`],
      ['状态', `<span class="badge ${reviewTone(item.status)}">${esc(ENUMS.review[item.status] || item.status)}</span>`],
      ['数据源', esc(item.source_name || '—')],
      ['摘要', esc(item.summary || '—')],
      ['复核人', esc(item.reviewer || '—')],
      ['复核备注', esc(item.review_note || '—')],
      ['生成时间', fmtTime(item.created_at)],
    ])}
    <h3 style="margin:14px 0 8px;font-size:0.95rem">算法明细</h3>
    <pre class="code">${esc(JSON.stringify(item.payload || {}, null, 2))}</pre>`,
    footer: canReview
      ? `<form id="review-form" style="display:grid;gap:10px">
          ${field({ label: '复核结论', name: 'status', value: item.status, options: Object.entries(ENUMS.review).map(([value, label]) => ({ value, label })) })}
          ${field({ label: '备注', name: 'note', value: item.review_note || '', placeholder: '写一句判定依据' })}
          <button class="btn accent" type="submit">提交复核</button>
        </form>`
      : '<span class="mono muted">只读角色可以查看，但不能复核</span>',
  });
  root.querySelector('#review-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      await api.patch(`/api/findings/${item.id}/review`, {
        status: form.status.value,
        note: form.note.value.trim() || null,
      });
      toast('复核结果已保存');
      close();
      await findingsPage.render(view, ctx);
    } catch (err) {
      toast(errorMessage(err), 'err');
    }
  });
}

export const findingsPage = {
  async render(view, ctx) {
    state.runId = ctx.query.run_id || state.runId;
    let data;
    try {
      data = await api.get('/api/findings', {
        run_id: state.runId,
        severity: state.severity,
        status: state.status,
        q: state.q,
        limit: 50,
      });
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => findingsPage.render(view, ctx));
      return;
    }
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>结果复核 ${state.runId ? `<span class="mono muted">· 运行 #${esc(state.runId)}</span>` : ''}</h2>
          <div style="display:flex;gap:8px;align-items:center">
            <span class="meta">${data.total} 条</span>
            ${can(ctx.user.role, 'export:read') ? '<button class="btn sm ghost" id="export-findings">导出 CSV</button>' : ''}
          </div>
        </div>
        <div class="panel-body">
          <div class="filter-bar" id="finding-filters">
            ${field({ label: '搜索', name: 'q', value: state.q, placeholder: '标题 / 键' })}
            ${field({ label: '等级', name: 'severity', value: state.severity, options: [{ value: '', label: '全部' }, ...Object.entries(ENUMS.severity).map(([value, label]) => ({ value, label }))] })}
            ${field({ label: '复核状态', name: 'status', value: state.status, options: [{ value: '', label: '全部' }, ...Object.entries(ENUMS.review).map(([value, label]) => ({ value, label }))] })}
          </div>
        </div>
        ${table({
          rows: data.items,
          empty: { title: '这个筛选下没有结果', hint: '换个运行或等级再看。' },
          columns: [
            { key: 'title', label: '标题', render: (row) => `<b>${esc(row.title)}</b><div class="mono muted">${esc(row.key)}</div>` },
            { key: 'severity', label: '等级', render: (row) => `<span class="badge ${badgeTone(row.severity)}">${esc(ENUMS.severity[row.severity] || row.severity)}</span>` },
            { key: 'score', label: '分数', className: 'num', render: (row) => row.score.toFixed(1) },
            { key: 'status', label: '复核', render: (row) => `<span class="badge ${reviewTone(row.status)}">${esc(ENUMS.review[row.status] || row.status)}</span>` },
            { key: 'source_name', label: '数据源', render: (row) => esc(row.source_name || '—') },
            { key: 'run_no', label: '运行号', className: 'mono' },
            { key: 'created_at', label: '生成时间', render: (row) => fmtTime(row.created_at) },
          ],
        })}
      </section>`;
    const filters = view.querySelector('#finding-filters');
    filters?.addEventListener('change', () => {
      state.q = filters.querySelector('[name=q]').value.trim();
      state.severity = filters.querySelector('[name=severity]').value;
      state.status = filters.querySelector('[name=status]').value;
      findingsPage.render(view, ctx);
    });
    view.querySelectorAll('table.data tbody tr').forEach((row) => {
      row.addEventListener('click', () => {
        const item = data.items.find((entry) => String(entry.id) === row.dataset.id);
        if (item) openFinding(view, ctx, item);
      });
    });
    view.querySelector('#export-findings')?.addEventListener('click', async () => {
      try {
        await api.download(`/api/exports/findings.csv${state.runId ? `?run_id=${state.runId}` : ''}`, 'findings.csv');
        toast('已开始下载结果清单');
      } catch (err) {
        toast(errorMessage(err), 'err');
      }
    });
  },
};

export default findingsPage;
