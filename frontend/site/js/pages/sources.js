import { api } from '../api.js';
import { ENUMS, can } from '../config.js';
import { drawer, emptyState, errorBox, errorMessage, esc, field, fmtTime, kv, table, toast } from '../ui.js';

const state = { q: '', kind: '', enabled: '' };

function sourceRows(config) {
  const rows = (config || {}).rows || [];
  if (!rows.length) return '<p class="muted">该接入源还没有明细行。</p>';
  return `<div class="table-wrap"><table class="data" style="min-width:0">
    <thead><tr><th>KEY</th><th>标题</th><th>值</th><th>阈值</th></tr></thead>
    <tbody>${rows
      .slice(0, 12)
      .map(
        (row) =>
          `<tr><td class="mono">${esc(row.key)}</td><td>${esc(row.title)}</td><td class="num">${esc(row.value)}</td><td class="num">${esc(row.threshold)}</td></tr>`,
      )
      .join('')}</tbody></table></div>`;
}

function openSource(view, ctx, source) {
  const editable = can(ctx.user.role, 'source:write');
  const { root, close } = drawer({
    title: source.name,
    subtitle: `${source.code} · ${source.kind_label}`,
    body: `${kv([
      ['名称', esc(source.name)],
      ['接入方式', esc(source.kind_label)],
      ['入口', source.endpoint ? `<span class="mono">${esc(source.endpoint)}</span>` : '—'],
      ['负责人', esc(source.owner)],
      ['状态', source.enabled ? '启用' : '停用'],
      ['最近同步', fmtTime(source.last_synced_at)],
      ['备注', esc(source.note || '—')],
    ])}
    <h3 style="margin:14px 0 8px;font-size:0.95rem">明细行（前 12 条）</h3>
    ${sourceRows(source.config)}`,
    footer: editable
      ? `<button class="btn ghost" data-toggle>${source.enabled ? '停用该源' : '重新启用'}</button>`
      : '<span class="mono muted">只读角色仅可查看</span>',
  });
  root.querySelector('[data-toggle]')?.addEventListener('click', async () => {
    try {
      await api.patch(`/api/sources/${source.id}`, { enabled: !source.enabled });
      toast('接入源状态已更新');
      close();
      await sourcesPage.render(view, ctx);
    } catch (err) {
      toast(errorMessage(err), 'err');
    }
  });
}

function openCreate(view, ctx) {
  const { root, close } = drawer({
    title: '登记接入源',
    subtitle: '配置一次，后续运行都按这份口径',
    body: `<form id="source-form" class="form-grid" style="display:grid;gap:12px">
      ${field({ label: '编码（小写字母/数字）', name: 'code', placeholder: 'src-c' })}
      ${field({ label: '名称', name: 'name', placeholder: '例如：华东区门店价目表' })}
      ${field({
        label: '接入方式',
        name: 'kind',
        value: 'manual',
        options: Object.entries(ENUMS.sourceKind).map(([value, label]) => ({ value, label })),
      })}
      ${field({ label: '入口 / 文件路径', name: 'endpoint', placeholder: 'https://… 或 s3://…' })}
      ${field({ label: '备注', name: 'note' })}
      <div class="form-error" id="source-error"></div>
      <button class="btn accent" type="submit">保存</button>
    </form>`,
  });
  root.querySelector('#source-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      await api.post('/api/sources', {
        code: form.code.value.trim(),
        name: form.name.value.trim(),
        kind: form.kind.value,
        endpoint: form.endpoint.value.trim() || null,
        note: form.note.value.trim() || null,
        config: { rows: [] },
      });
      toast('接入源已登记');
      close();
      await sourcesPage.render(view, ctx);
    } catch (err) {
      root.querySelector('#source-error').textContent = err.code === 'CONFLICT' ? '编码已存在，请换一个' : errorMessage(err);
    }
  });
}

export const sourcesPage = {
  async render(view, ctx) {
    const query = { limit: 50, q: state.q, kind: state.kind, enabled: state.enabled };
    let data;
    try {
      data = await api.get('/api/sources', query);
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => sourcesPage.render(view, ctx));
      return;
    }
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>接入源</h2>
          <div style="display:flex;gap:8px;align-items:center">
            <span class="meta">${data.total} 个</span>
            ${can(ctx.user.role, 'source:write') ? '<button class="btn sm accent" id="new-source">登记接入源</button>' : ''}
          </div>
        </div>
        <div class="panel-body">
          <div class="filter-bar" id="source-filters">
            ${field({ label: '搜索', name: 'q', value: state.q, placeholder: '名称 / 编码' })}
            ${field({ label: '接入方式', name: 'kind', value: state.kind, options: [{ value: '', label: '全部' }, ...Object.entries(ENUMS.sourceKind).map(([value, label]) => ({ value, label }))] })}
            ${field({ label: '状态', name: 'enabled', value: state.enabled, options: [{ value: '', label: '全部' }, { value: 'true', label: '启用' }, { value: 'false', label: '停用' }] })}
            <div class="spacer"></div>
          </div>
        </div>
        ${table({
          rows: data.items,
          columns: [
            { key: 'code', label: '编码', className: 'mono' },
            { key: 'name', label: '名称', render: (row) => `<b>${esc(row.name)}</b>` },
            { key: 'kind_label', label: '接入方式' },
            { key: 'owner', label: '负责人' },
            { key: 'last_synced_at', label: '最近同步', render: (row) => fmtTime(row.last_synced_at) },
            { key: 'enabled', label: '状态', render: (row) => (row.enabled ? '<span class="badge ok">启用</span>' : '<span class="badge">停用</span>') },
          ],
          empty: { title: '还没有接入源', hint: '管理员可以登记第一个接入源。' },
        })}
      </section>`;

    const filters = view.querySelector('#source-filters');
    filters?.addEventListener('click', (event) => {
      if (event.target.closest('.spacer')) return;
    });
    filters?.addEventListener('change', () => {
      state.q = filters.querySelector('[name=q]').value.trim();
      state.kind = filters.querySelector('[name=kind]').value;
      state.enabled = filters.querySelector('[name=enabled]').value;
      sourcesPage.render(view, ctx);
    });
    filters?.querySelector('[name=q]')?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        state.q = event.target.value.trim();
        sourcesPage.render(view, ctx);
      }
    });
    view.querySelectorAll('table.data tbody tr').forEach((row) => {
      row.addEventListener('click', () => {
        const item = data.items.find((entry) => String(entry.id) === row.dataset.id);
        if (item) openSource(view, ctx, item);
      });
    });
    view.querySelector('#new-source')?.addEventListener('click', () => openCreate(view, ctx));
  },
};

export default sourcesPage;
