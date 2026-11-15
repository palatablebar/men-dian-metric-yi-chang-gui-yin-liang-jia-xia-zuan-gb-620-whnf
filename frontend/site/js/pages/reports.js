import { api } from '../api.js';
import { ENUMS, can, fmtMoney } from '../config.js';
import { drawer, errorBox, errorMessage, esc, field, kv, table, toast } from '../ui.js';

function openDetail(view, ctx, report) {
  const snapshot = report.snapshot || {};
  const { root } = drawer({
    title: report.title,
    subtitle: `${report.report_no} · ${report.kind_label} · ${report.status_label}`,
    body: `${kv([
      ['统计区间', `${esc(report.period_start)} → ${esc(report.period_end)}`],
      ['异常起数', report.anomaly_count],
      ['影响合计', fmtMoney(report.impact_total)],
      ['生成人', esc(report.generated_by)],
      ['口径', esc(snapshot.method || '—')],
      ['数据窗口', `${esc(snapshot.data_window?.start || '—')} → ${esc(snapshot.data_window?.end || '—')}`],
    ])}
    <h3 class="sub-head">严重度分布</h3>
    ${table({
      rows: (snapshot.severity || []).map((item, index) => ({ id: index, ...item })),
      columns: [
        { key: 'label', label: '等级' },
        { key: 'count', label: '起数', className: 'num' },
      ],
    })}
    <h3 class="sub-head">拖累门店</h3>
    ${table({
      rows: (snapshot.top_drag_stores || []).map((item, index) => ({ id: index, ...item })),
      columns: [
        { key: 'store', label: '门店' },
        { key: 'impact', label: '影响金额', className: 'num', render: (row) => `<span class="neg">${fmtMoney(row.impact)}</span>` },
        { key: 'count', label: '异常', className: 'num' },
      ],
    })}`,
    footer: can(ctx.user.role, 'export:read')
      ? `<div class="footer-actions">
          <button class="btn accent" data-export>导出报告 CSV</button>
          ${can(ctx.user.role, 'report:generate') ? `<button class="btn ghost" data-publish="${report.status === 'published' ? 'draft' : 'published'}">${report.status === 'published' ? '撤回到草稿' : '发布报告'}</button>` : ''}
        </div>`
      : '<span class="mono muted">只读角色不能导出或发布</span>',
  });
  root.querySelector('[data-export]')?.addEventListener('click', async () => {
    try {
      await api.download(`/api/exports/reports/${report.id}.csv`, `${report.report_no}.csv`);
      toast('已开始下载报告');
    } catch (err) {
      toast(errorMessage(err), 'err');
    }
  });
  root.querySelector('[data-publish]')?.addEventListener('click', async (event) => {
    try {
      await api.reports.publish(report.id, { status: event.target.dataset.publish });
      toast('报告状态已更新');
      await reportsPage.render(view, ctx);
    } catch (err) {
      toast(errorMessage(err), 'err');
    }
  });
}

function openGenerate(view, ctx) {
  const { root, close } = drawer({
    title: '生成经营报告',
    subtitle: '按统计区间汇总异常、影响金额与拖累门店',
    body: `<form id="report-form" class="stack">
      ${field({ label: '报告类型', name: 'kind', value: 'weekly', options: Object.entries(ENUMS.reportKind).map(([value, label]) => ({ value, label })) })}
      ${field({ label: '开始日期', name: 'period_start', value: '2026-10-26', placeholder: 'YYYY-MM-DD' })}
      ${field({ label: '结束日期', name: 'period_end', value: '2026-11-13', placeholder: 'YYYY-MM-DD' })}
      ${field({ label: '备注', name: 'note', placeholder: '例如：11 月第 2 周周会用' })}
      <div class="form-error" id="report-error"></div>
      <button class="btn accent" type="submit">生成报告</button>
    </form>`,
  });
  root.querySelector('#report-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      const report = await api.reports.create({
        kind: form.kind.value,
        period_start: form.period_start.value,
        period_end: form.period_end.value,
        note: form.note.value.trim() || null,
      });
      toast(`报告 ${report.report_no} 已生成：${report.anomaly_count} 起异常`);
      close();
      await reportsPage.render(view, ctx);
    } catch (err) {
      root.querySelector('#report-error').textContent = errorMessage(err);
    }
  });
}

export const reportsPage = {
  async render(view, ctx) {
    let data;
    let runs;
    try {
      [data, runs] = await Promise.all([api.reports.list({ limit: 50 }), api.runs.list({ limit: 5 })]);
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => reportsPage.render(view, ctx));
      return;
    }
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>报告与导出</h2>
          <div class="head-actions">
            <span class="meta">${data.total} 份</span>
            ${can(ctx.user.role, 'export:read') ? '<button class="btn sm ghost" id="export-attr">归因明细 CSV</button>' : ''}
            ${can(ctx.user.role, 'report:generate') ? '<button class="btn sm accent" id="new-report">生成报告</button>' : ''}
          </div>
        </div>
        ${table({
          rows: data.items,
          columns: [
            { key: 'report_no', label: '编号', className: 'mono' },
            { key: 'title', label: '标题', render: (row) => `<b>${esc(row.title)}</b><div class="mono muted">${esc(row.period_start)} → ${esc(row.period_end)}</div>` },
            { key: 'kind_label', label: '类型' },
            { key: 'anomaly_count', label: '异常', className: 'num' },
            { key: 'impact_total', label: '影响', className: 'num', render: (row) => `<span class="neg">${fmtMoney(row.impact_total)}</span>` },
            { key: 'status', label: '状态', render: (row) => `<span class="badge ${row.status === 'published' ? 'ok' : 'pending'}">${esc(row.status_label)}</span>` },
            { key: 'generated_by', label: '生成人', className: 'mono' },
          ],
          empty: { title: '还没有报告', hint: '管理员可以按区间生成第一份周报。' },
        })}
      </section>

      <div class="grid-2">
        <section class="panel">
          <div class="panel-head"><h2>导出清单</h2><span class="meta">CSV · UTF-8 BOM</span></div>
          <div class="panel-body stack">
            <p class="muted small">导出接口按角色鉴权：viewer 调用会返回 403；导出动作写入审计日志（可回查谁在什么时候导了什么）。</p>
            ${can(ctx.user.role, 'export:read')
              ? `<div class="footer-actions">
                  <button class="btn ghost" id="export-anomalies">异常清单 anomalies.csv</button>
                  <button class="btn ghost" id="export-attributions">归因明细 attributions.csv</button>
                  <button class="btn ghost" id="export-channels">渠道下钻 channels.csv</button>
                </div>`
              : '<span class="mono muted">当前角色没有导出权限（导出按钮不出现，接口也会 403）</span>'}
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><h2>最近检测批次</h2><span class="meta">runs</span></div>
          ${table({
            rows: runs.items,
            columns: [
              { key: 'run_no', label: '批次', className: 'mono' },
              { key: 'status', label: '状态', render: (row) => `<span class="badge ${row.status === 'success' ? 'ok' : 'warn'}">${esc(ENUMS.runStatus[row.status] || row.status)}</span>` },
              { key: 'anomaly_count', label: '命中', className: 'num' },
              { key: 'store_count', label: '门店', className: 'num' },
              { key: 'impact_total', label: '影响', className: 'num', render: (row) => fmtMoney((row.metrics || {}).impact_total || 0) },
            ],
          })}
        </section>
      </div>`;
    view.querySelectorAll('table.data tbody tr').forEach((row) => {
      row.addEventListener('click', () => {
        const report = data.items.find((item) => String(item.id) === row.dataset.id);
        if (report) openDetail(view, ctx, report);
      });
    });
    view.querySelector('#new-report')?.addEventListener('click', () => openGenerate(view, ctx));
    const download = async (path, filename) => {
      try {
        await api.download(path, filename);
        toast('已开始下载');
      } catch (err) {
        toast(errorMessage(err), 'err');
      }
    };
    view.querySelector('#export-anomalies')?.addEventListener('click', () => download('/api/exports/anomalies.csv', 'anomalies.csv'));
    view.querySelector('#export-attributions')?.addEventListener('click', () => download('/api/exports/attributions.csv', 'attributions.csv'));
    view.querySelector('#export-channels')?.addEventListener('click', () => download('/api/exports/channels.csv', 'channels.csv'));
    view.querySelector('#export-attr')?.addEventListener('click', () => download('/api/exports/attributions.csv', 'attributions.csv'));
  },
};

export default reportsPage;
