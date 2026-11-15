import { api } from '../api.js';
import { ENUMS, can } from '../config.js';
import { drawer, errorBox, errorMessage, esc, field, fmtTime, kv, table, toast } from '../ui.js';

const state = { status: '', sourceId: '' };

function runDuration(run) {
  if (!run.started_at || !run.finished_at) return '—';
  const ms = new Date(run.finished_at) - new Date(run.started_at);
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function openRun(view, ctx, run) {
  const { root } = drawer({
    title: `运行 ${run.run_no}`,
    subtitle: `${run.source_name || '未绑定数据源'} · ${ENUMS.trigger[run.trigger] || run.trigger}`,
    body: `${kv([
      ['状态', esc(ENUMS.runStatus[run.status] || run.status)],
      ['操作人', esc(run.operator_email)],
      ['输入行数', esc(run.input_count)],
      ['产出条数', esc(run.output_count)],
      ['开始', fmtTime(run.started_at)],
      ['结束', fmtTime(run.finished_at)],
      ['耗时', runDuration(run)],
    ])}
    <h3 style="margin:14px 0 8px;font-size:0.95rem">指标</h3>
    <pre class="code">${esc(JSON.stringify(run.metrics || {}, null, 2))}</pre>
    <h3 style="margin:14px 0 8px;font-size:0.95rem">运行日志</h3>
    <pre class="code">${esc(run.log_text || '（无日志）')}</pre>`,
    footer: `<button class="btn accent" data-findings>查看本次结果</button>`,
  });
  root.querySelector('[data-findings]')?.addEventListener('click', () => {
    location.hash = `#/findings?run_id=${run.id}`;
  });
}

function openRunForm(view, ctx, sources) {
  const { root, close } = drawer({
    title: '发起运行',
    subtitle: '选择接入源后立即执行一次，并把结果写入结果池',
    body: `<form id="run-form" style="display:grid;gap:12px">
      ${field({
        label: '接入源',
        name: 'source_id',
        options: sources.map((source) => ({ value: source.id, label: `${source.name}（${source.code}）` })),
      })}
      ${field({ label: '触发方式说明', name: 'trigger', value: 'manual', options: [{ value: 'manual', label: '手动' }, { value: 'schedule', label: '定时补偿' }] })}
      <div class="form-error" id="run-error"></div>
      <button class="btn accent" type="submit">开始运行</button>
    </form>`,
  });
  root.querySelector('#run-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    button.textContent = '运行中…';
    try {
      const run = await api.post('/api/runs', {
        source_id: Number(form.source_id.value),
        trigger: form.trigger.value,
      });
      toast(`运行 ${run.run_no} 完成：${run.status}，产出 ${run.output_count} 条`);
      close();
      await runsPage.render(view, ctx);
    } catch (err) {
      root.querySelector('#run-error').textContent = errorMessage(err);
      button.disabled = false;
      button.textContent = '开始运行';
    }
  });
}

export const runsPage = {
  async render(view, ctx) {
    let runs;
    let sources;
    try {
      [runs, sources] = await Promise.all([
        api.get('/api/runs', { status: state.status, source_id: state.sourceId, limit: 50 }),
        api.get('/api/sources', { limit: 100 }),
      ]);
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => runsPage.render(view, ctx));
      return;
    }
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>运行记录</h2>
          <div style="display:flex;gap:8px;align-items:center">
            <span class="meta">${runs.total} 次</span>
            ${can(ctx.user.role, 'run:create') ? '<button class="btn sm accent" id="new-run">发起运行</button>' : ''}
          </div>
        </div>
        <div class="panel-body">
          <div class="filter-bar" id="run-filters">
            ${field({ label: '接入源', name: 'source_id', value: state.sourceId, options: [{ value: '', label: '全部' }, ...sources.items.map((source) => ({ value: source.id, label: source.name }))] })}
            ${field({ label: '状态', name: 'status', value: state.status, options: [{ value: '', label: '全部' }, ...Object.entries(ENUMS.runStatus).map(([value, label]) => ({ value, label }))] })}
          </div>
        </div>
        ${table({
          rows: runs.items,
          columns: [
            { key: 'run_no', label: '运行号', className: 'mono' },
            { key: 'source_name', label: '数据源' },
            { key: 'status', label: '状态', render: (row) => `<span class="badge ${row.status === 'success' ? 'ok' : row.status === 'failed' ? 'danger' : 'warn'}">${esc(ENUMS.runStatus[row.status] || row.status)}</span>` },
            { key: 'trigger', label: '触发', render: (row) => esc(ENUMS.trigger[row.trigger] || row.trigger) },
            { key: 'input_count', label: '输入', className: 'num' },
            { key: 'output_count', label: '产出', className: 'num' },
            { key: 'started_at', label: '开始时间', render: (row) => fmtTime(row.started_at) },
          ],
        })}
      </section>`;
    const filters = view.querySelector('#run-filters');
    filters?.addEventListener('change', () => {
      state.sourceId = filters.querySelector('[name=source_id]').value;
      state.status = filters.querySelector('[name=status]').value;
      runsPage.render(view, ctx);
    });
    view.querySelectorAll('table.data tbody tr').forEach((row) => {
      row.addEventListener('click', () => {
        const run = runs.items.find((item) => String(item.id) === row.dataset.id);
        if (run) openRun(view, ctx, run);
      });
    });
    view.querySelector('#new-run')?.addEventListener('click', () => openRunForm(view, ctx, sources.items));
  },
};

export default runsPage;
