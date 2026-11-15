import { api } from '../api.js';
import { ENUMS, fmtMoney, fmtPct } from '../config.js';
import { contributionTable, errorBox, errorMessage, esc, factorBars, kv, table, toast } from '../ui.js';

export const attributionPage = {
  async render(view, ctx) {
    view.innerHTML = '<div class="empty"><div class="mark">调取归因…</div></div>';
    let list;
    let detail;
    try {
      list = await api.anomalies.list({ limit: 40 });
      const targetId = ctx.query.anomaly_id || (list.items[0] || {}).id;
      if (!targetId) {
        view.innerHTML = `<section class="panel">${errorBox('还没有可归因的异常，请先发起一次检测。')}</section>`;
        return;
      }
      detail = await api.attributions.forAnomaly(targetId);
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => attributionPage.render(view, ctx));
      return;
    }
    const shares = detail.shares;
    const dims = detail.dimensions || {};
    const sample = detail.sample || {};
    const sampleDays = sample.days || [];
    const excluded = sample.excluded_special_days || [];
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>归因下钻</h2>
          <div class="head-actions">
            <span class="meta">算法 B · ${esc(detail.method)}</span>
            ${ctx.user.role !== 'viewer' ? '<button class="btn sm ghost" id="export-attr">导出归因 CSV</button>' : ''}
          </div>
        </div>
        <div class="panel-body">
          <div class="pickers">
            ${list.items
              .slice(0, 12)
              .map(
                (item) => `<a class="pick ${String(item.id) === String(detail.anomaly_id) ? 'active' : ''}" href="#/attribution?anomaly_id=${item.id}" data-testid="pick-${item.id}">
                  <b>${esc(item.store_name)}</b>
                  <span class="mono">${esc(item.metric_date)} · z ${item.robust_z.toFixed(2)} · ${fmtMoney(item.impact_amount)}</span>
                </a>`,
              )
              .join('')}
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>${esc(detail.store_name)} · ${esc(detail.metric_date)}</h2>
          <span class="meta">Δ营收 ${fmtMoney(detail.total_delta)} · 残差 ${detail.residual.toFixed(2)} 元</span>
        </div>
        <div class="panel-body">
          <h3 class="sub-head">同一组样本（异常 / 量价三项 / 下钻共用）</h3>
          <p class="muted small">样本 ${esc(sample.start || '—')} → ${esc(sample.end || '—')}，共 ${sampleDays.length} 天，样本指纹 <span class="mono">${esc(sample.key || '—')}</span>；日历 v${esc(sample.attribution_calendar_version ?? 0)}。样本一致性：<span class="badge ${sample.consistent ? 'ok' : 'danger'}">${sample.consistent ? '一致' : '不一致，请重算'}</span></p>
          <div class="chip-wrap">${sampleDays.map((day) => `<span class="chip mono">${esc(day)}</span>`).join('')}</div>
          <p class="muted small">被运营日历排除的特殊日（${excluded.length} 天）：${excluded.map((item) => `<span class="chip warn mono">${esc(item.date)} · ${esc(ENUMS.calendarDayType[item.special_type] || item.special_type || '特殊日')}</span>`).join('') || '无'}</p>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>量价分解</h2>
          <span class="meta">LMDI 加法形式 · 与异常同一样本</span>
        </div>
        <div class="panel-body split">
          <div>
            <h3 class="sub-head">量价分解（LMDI 加法形式）</h3>
            ${factorBars({ parts: detail.parts, shares })}
            <p class="muted small">对数平均权重 ${detail.drivers.log_mean_weight ?? '—'}；基线 ${fmtMoney(detail.base_rev)} → 当期 ${fmtMoney(detail.cur_rev)}；三项之和与 Δ 的差额如实记为残差，不摊派。</p>
            ${kv([
              ['基线 ADR', `${Number(detail.drivers.base.adr).toFixed(0)} 元`],
              ['基线 OCC', fmtPct(detail.drivers.base.occ)],
              ['基线可售房量', detail.drivers.base.rooms],
              ['当期 ADR', `${Number(detail.drivers.current.adr).toFixed(0)} 元`],
              ['当期 OCC', fmtPct(detail.drivers.current.occ)],
              ['当期可售房量', detail.drivers.current.rooms],
            ])}
          </div>
          <div>
            <h3 class="sub-head">结论（写入报告与导出）</h3>
            <div class="narrative" data-testid="narrative">${esc(detail.narrative)}</div>
            <h3 class="sub-head">三维贡献</h3>
            <div class="tabs">
              ${['channel', 'store', 'room_type']
                .map(
                  (key, index) =>
                    `<button class="tab ${index === 0 ? 'active' : ''}" data-tab="${key}">${esc((dims[key] || {}).label || key)}</button>`,
                )
                .join('')}
            </div>
            <div id="dim-body">${contributionTable(dims.channel || {})}</div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><h2>同维度明细</h2><span class="meta">contribution = group Δ / total Δ · 同一组样本</span></div>
        <div class="panel-body grid-3">
          ${['channel', 'store', 'room_type']
            .map(
              (key) => `<div class="dim-block">
                <h3 class="sub-head">${esc((dims[key] || {}).label || key)}</h3>
                ${contributionTable(dims[key] || {})}
              </div>`,
            )
            .join('')}
        </div>
      </section>`;
    view.querySelectorAll('.tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        view.querySelectorAll('.tab').forEach((node) => node.classList.remove('active'));
        tab.classList.add('active');
        const block = dims[tab.dataset.tab];
        const body = view.querySelector('#dim-body');
        if (body) body.innerHTML = contributionTable(block || {});
      });
    });
    view.querySelector('#export-attr')?.addEventListener('click', async () => {
      try {
        await api.download('/api/exports/attributions.csv', 'attributions.csv');
        toast('已开始下载归因明细');
      } catch (err) {
        toast(errorMessage(err), 'err');
      }
    });
  },
};

export default attributionPage;
