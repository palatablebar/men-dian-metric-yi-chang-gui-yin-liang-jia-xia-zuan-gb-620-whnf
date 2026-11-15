import { api } from '../api.js';
import { errorBox, errorMessage, esc, fmtTime, statStrip, table } from '../ui.js';

export const auditPage = {
  async render(view, ctx) {
    let data;
    try {
      data = await api.audit.list({ limit: 120 });
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => auditPage.render(view, ctx));
      return;
    }
    const layers = data.items.reduce((acc, item) => {
      acc[item.layer] = (acc[item.layer] || 0) + 1;
      return acc;
    }, {});
    view.innerHTML = `
      ${statStrip([
        { label: '审计条数', value: data.total, hint: '最近 120 条' },
        ...Object.entries(layers).map(([layer, count]) => ({ label: `层 ${layer}`, value: count, hint: '分层留痕' })),
      ])}
      <section class="panel">
        <div class="panel-head"><h2>审计日志</h2><span class="meta">仅管理员可见 · 领域动作 + HTTP 写请求双层</span></div>
        ${table({
          rows: data.items,
          columns: [
            { key: 'created_at', label: '时间', render: (row) => fmtTime(row.created_at) },
            { key: 'actor_email', label: '操作人', className: 'mono' },
            { key: 'actor_role', label: '角色' },
            { key: 'action_label', label: '动作' },
            { key: 'entity', label: '对象' },
            { key: 'layer', label: '层', render: (row) => `<span class="badge">${esc(row.layer)}</span>` },
            { key: 'detail', label: '详情', render: (row) => `<span class="mono muted">${esc(JSON.stringify(row.detail || {}))}</span>` },
          ],
          empty: { title: '还没有审计记录', hint: '登录、检测、处理、导出都会留痕。' },
        })}
      </section>`;
  },
};

export default auditPage;
