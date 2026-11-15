import { api } from '../api.js';
import { BRAND, fmtMoney } from '../config.js';
import { barList, emptyState, errorBox, errorMessage, esc, fmtTime, handNote, statStrip, table } from '../ui.js';

function trendStems(points) {
  if (!points.length) return emptyState({ title: '还没有异常', hint: '去「异常清单」发起一次检测。' });
  const max = Math.max(1, ...points.map((point) => point.count));
  return `<div class="trend">${points
    .map(
      (point) => `<div class="col" title="${esc(point.date)} · ${esc(point.count)} 起 · ${fmtMoney(point.impact)}">
        <div class="stem" style="height:${Math.max(3, Math.round((point.count / max) * 76))}px"></div>
        <span class="lbl">${esc(point.date.slice(5))}</span>
      </div>`,
    )
    .join('')}</div>`;
}

export const overviewPage = {
  async render(view, ctx) {
    view.innerHTML = '<div class="empty"><div class="mark">读取交接本…</div></div>';
    let data;
    let recent;
    try {
      [data, recent] = await Promise.all([api.overview.get(), api.anomalies.list({ limit: 6 })]);
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => overviewPage.render(view, ctx));
      return;
    }
    const latest = data.latest_run;
    view.innerHTML = `
      <section class="hero">
        <div class="hero-main">
          <div class="eyebrow">数据窗口 ${esc(data.data_window.start || '—')} → ${esc(data.data_window.end || '—')} · ${esc(data.days)} 天</div>
          <h2>${data.anomalies_total} 起异常，影响 <em>${fmtMoney(data.impact_total)}</em></h2>
          <p>其中 ${data.pending_total} 起待处理，${data.reviewed_total} 起已有结论；门店 ${data.stores_total} 家、指标点 ${data.points_total.toLocaleString('zh-CN')} 条。${data.invalidated_total ? `另有 ${data.invalidated_total} 起因日历规则变更待重算。` : ''}</p>
          <div class="hero-actions">
            ${latest ? `<span class="chip">最近检测 ${esc(latest.run_no)} · ${esc(latest.status_label)} · ${latest.anomaly_count} 起</span>` : ''}
            ${data.latest_report ? `<span class="chip">最近报告 ${esc(data.latest_report.report_no)} · ${esc(data.latest_report.status_label)}</span>` : ''}
          </div>
        </div>
        ${handNote(BRAND.handNote)}
      </section>

      ${statStrip([
        { label: '异常起数', value: data.anomalies_total, hint: `覆盖 ${data.stores_total} 家门店` },
        { label: '影响金额', value: fmtMoney(data.impact_total), hint: `待处理 ${fmtMoney(data.impact_pending)}` },
        { label: '待处理', value: data.pending_total, hint: data.worker_alive ? '夜班任务在岗' : '夜班任务心跳超时' },
        { label: '指标点', value: data.points_total.toLocaleString('zh-CN'), hint: `${data.days} 天 × 3 渠道` },
        { label: '日历待重算', value: data.invalidated_total || 0, hint: '规则变更后失效重算' },
      ])}

      <div class="grid-2">
        <section class="panel">
          <div class="panel-head"><h2>严重度分布</h2><span class="meta">severity</span></div>
          <div class="panel-body">${data.severity.length ? barList(data.severity) : emptyState({ title: '还没有异常', hint: '去异常清单跑一次检测。' })}</div>
        </section>
        <section class="panel">
          <div class="panel-head"><h2>处理进度</h2><span class="meta">review</span></div>
          <div class="panel-body">${data.review.length ? barList(data.review, 'ok') : emptyState({ title: '还没有处理记录', hint: '异常生成后由分析师写结论。' })}</div>
        </section>
      </div>

      <div class="grid-2">
        <section class="panel">
          <div class="panel-head"><h2>拖累门店 Top</h2><span class="meta">impact / store</span></div>
          ${table({
            rows: data.top_drag,
            columns: [
              { key: 'store_name', label: '门店', render: (row) => `<b>${esc(row.store_name)}</b><div class="mono muted">${esc(row.store_code)} · ${esc(row.region)}</div>` },
              { key: 'impact', label: '影响金额', className: 'num', render: (row) => `<span class="neg">${fmtMoney(row.impact)}</span>` },
              { key: 'count', label: '异常', className: 'num' },
            ],
            empty: { title: '还没有异常', hint: '检测后这里会出现拖累门店。' },
          })}
        </section>
        <section class="panel">
          <div class="panel-head"><h2>异常日期分布</h2><span class="meta">anomalies / day</span></div>
          <div class="panel-body">${trendStems(data.trend)}</div>
        </section>
      </div>

      <div class="grid-2">
        <section class="panel">
          <div class="panel-head"><h2>最近异常</h2><span class="meta">top 6 by z</span></div>
          ${table({
            rows: recent.items,
            columns: [
              { key: 'store_name', label: '门店 / 日期', render: (row) => `<b>${esc(row.store_name)}</b><div class="mono muted">${esc(row.metric_date)}</div>` },
              { key: 'robust_z', label: '稳健 z', className: 'num', render: (row) => `<span class="neg">${row.robust_z.toFixed(2)}</span>` },
              { key: 'impact_amount', label: '影响', className: 'num', render: (row) => fmtMoney(row.impact_amount) },
              { key: 'severity', label: '等级', render: (row) => `<span class="badge ${row.severity}">${esc(row.severity_label)}</span>` },
            ],
          })}
        </section>
        <section class="panel">
          <div class="panel-head"><h2>门店与区域</h2><span class="meta">stores</span></div>
          <div class="panel-body">
            ${barList(data.regions.map((item) => ({ label: item.region, count: item.count })))}
            <div class="legend">${data.store_status.map((item) => `<span class="chip">${esc(item.label)} ${item.count}</span>`).join('')}</div>
          </div>
        </section>
      </div>

      <section class="panel">
        <div class="panel-head"><h2>最近一次检测</h2><span class="meta">latest run</span></div>
        <div class="panel-body">
          ${
            latest
              ? `<div class="kv">
                  <dt>批次号</dt><dd class="mono">${esc(latest.run_no)}</dd>
                  <dt>状态</dt><dd>${esc(latest.status_label)}</dd>
                  <dt>门店</dt><dd>${latest.store_count} 家</dd>
                  <dt>命中</dt><dd>${latest.anomaly_count} 起</dd>
                  <dt>影响</dt><dd>${fmtMoney(latest.impact_total)}</dd>
                  <dt>开始</dt><dd>${fmtTime(latest.started_at)}</dd>
                </div>`
              : emptyState({ title: '还没有检测批次', hint: '在「异常清单」发起一次检测。' })
          }
        </div>
      </section>`;
  },
};

export default overviewPage;
