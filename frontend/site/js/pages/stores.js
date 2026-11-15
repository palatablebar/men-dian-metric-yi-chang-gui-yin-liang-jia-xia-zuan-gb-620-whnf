import { api } from '../api.js';
import { ENUMS, can, fmtMoney, fmtPct } from '../config.js';
import { bindFilters, drawer, errorBox, errorMessage, esc, field, filterBar, kv, seriesChart, table, toast } from '../ui.js';

const state = { q: '', region: '', status: '' };

async function openStore(view, ctx, store) {
  let series;
  try {
    series = await api.stores.series(store.id);
  } catch (err) {
    toast(errorMessage(err), 'err');
    return;
  }
  const points = series.points;
  const { root } = drawer({
    title: store.name,
    subtitle: `${store.code} · ${store.region} · ${store.city} · ${store.status_label}`,
    body: `${kv([
      ['房量', `${store.room_count} 间`],
      ['品牌', esc(store.brand)],
      ['店长', esc(store.manager)],
      ['90 天营收', fmtMoney(series.summary.revenue)],
      ['平均 ADR', `${series.summary.adr.toFixed(0)} 元`],
      ['平均 OCC', fmtPct(series.summary.occupancy)],
    ])}
    <h3 class="sub-head">营收日序列（特殊日已标注，不进入常态基线）</h3>
    ${seriesChart(points, { height: 140 })}
    <div class="chip-wrap">${points
      .filter((point) => point.is_special)
      .slice(-14)
      .map((point) => `<span class="chip warn mono">${esc(point.date)} · ${esc(ENUMS.calendarDayType[point.special_type] || '特殊日')}</span>`)
      .join('') || '<span class="muted small">窗口内没有特殊日</span>'}</div>
    <h3 class="sub-head">指标点（最近 10 条渠道明细）</h3>
    ${table({
      rows: points.slice(-10).reverse().map((point, index) => ({ id: `${point.date}-${index}`, ...point })),
      columns: [
        { key: 'date', label: '日期', className: 'mono' },
        { key: 'revenue', label: '营收', className: 'num', render: (row) => fmtMoney(row.revenue) },
        { key: 'adr', label: 'ADR', className: 'num', render: (row) => row.adr.toFixed(0) },
        { key: 'occupancy', label: 'OCC', className: 'num', render: (row) => fmtPct(row.occupancy) },
        { key: 'rooms_sold', label: '售出', className: 'num' },
        { key: 'is_weekend', label: '周末', render: (row) => (row.is_weekend ? '<span class="badge">周末</span>' : '—') },
        { key: 'is_special', label: '基线', render: (row) => (row.is_special ? `<span class="badge warn">${esc(ENUMS.calendarDayType[row.special_type] || '特殊日')}</span>` : '<span class="muted">纳入</span>') },
      ],
    })}`,
    footer: `<div class="footer-actions">
        <button class="btn accent" data-anomalies>看这家店的异常</button>
        <button class="btn ghost" data-calendar>运营日历（纳入/排除）</button>
      </div>`,
  });
  root.querySelector('[data-anomalies]')?.addEventListener('click', () => {
    location.hash = `#/anomalies?store_id=${store.id}`;
  });
  root.querySelector('[data-calendar]')?.addEventListener('click', () => {
    location.hash = `#/calendar?store_id=${store.id}`;
  });
}

function openCreate(view, ctx) {
  const { root, close } = drawer({
    title: '登记门店',
    subtitle: '仅管理员可维护门店档案',
    body: `<form id="store-form" style="display:grid;gap:12px">
      ${field({ label: '门店编码', name: 'code', placeholder: 'LB-HZ-999' })}
      ${field({ label: '门店名称', name: 'name', placeholder: '蓝湾·光谷中心店' })}
      ${field({ label: '区域', name: 'region', value: '华中', options: ['华东', '华南', '华北', '西南', '华中'].map((item) => ({ value: item, label: item })) })}
      ${field({ label: '城市', name: 'city', placeholder: '武汉' })}
      ${field({ label: '房量', name: 'room_count', type: 'number', value: '200' })}
      ${field({ label: '店长', name: 'manager', placeholder: '店长姓名' })}
      <div class="form-error" id="store-error"></div>
      <button class="btn accent" type="submit">保存门店</button>
    </form>`,
  });
  root.querySelector('#store-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      await api.stores.create({
        code: form.code.value.trim().toUpperCase(),
        name: form.name.value.trim(),
        region: form.region.value,
        city: form.city.value.trim(),
        room_count: Number(form.room_count.value || 200),
        manager: form.manager.value.trim(),
      });
      toast('门店已登记');
      close();
      await storesPage.render(view, ctx);
    } catch (err) {
      root.querySelector('#store-error').textContent = err.code === 'CONFLICT' ? '门店编码已存在' : errorMessage(err);
    }
  });
}

export const storesPage = {
  async render(view, ctx) {
    state.q = ctx.query.q ?? state.q;
    state.region = ctx.query.region ?? state.region;
    let data;
    let regions;
    try {
      [data, regions] = await Promise.all([
        api.stores.list({ q: state.q, region: state.region, status: state.status, limit: 200 }),
        api.stores.regions(),
      ]);
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => storesPage.render(view, ctx));
      return;
    }
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>门店与指标</h2>
          <div class="head-actions">
            <span class="meta">${data.total} 家门店</span>
            ${can(ctx.user.role, 'store:write') ? '<button class="btn sm accent" id="new-store">登记门店</button>' : ''}
          </div>
        </div>
        <div class="panel-body">
          ${filterBar({
            id: 'store-filters',
            fields: [
              { label: '搜索', name: 'q', value: state.q, placeholder: '名称 / 编码 / 城市' },
              { label: '区域', name: 'region', value: state.region, options: [{ value: '', label: '全部' }, ...regions.items.map((item) => ({ value: item.region, label: `${item.region}（${item.count}）` }))] },
              { label: '状态', name: 'status', value: state.status, options: [{ value: '', label: '全部' }, ...Object.entries(ENUMS.storeStatus).map(([value, label]) => ({ value, label }))] },
            ],
          })}
        </div>
        ${table({
          rows: data.items,
          columns: [
            { key: 'code', label: '编码', className: 'mono' },
            { key: 'name', label: '门店', render: (row) => `<b>${esc(row.name)}</b><div class="mono muted">${esc(row.city)} · ${esc(row.brand)}</div>` },
            { key: 'region', label: '区域' },
            { key: 'room_count', label: '房量', className: 'num' },
            { key: 'manager', label: '店长' },
            { key: 'status', label: '状态', render: (row) => `<span class="badge ${row.status === 'open' ? 'ok' : row.status === 'renovating' ? 'warn' : ''}">${esc(row.status_label)}</span>` },
          ],
          empty: { title: '没有符合条件的门店', hint: '换个区域或清空搜索词。' },
        })}
      </section>`;
    bindFilters(view, 'store-filters', (values) => {
      state.q = values.q.trim();
      state.region = values.region;
      state.status = values.status;
      storesPage.render(view, ctx);
    });
    view.querySelectorAll('table.data tbody tr').forEach((row) => {
      row.addEventListener('click', () => {
        const store = data.items.find((item) => String(item.id) === row.dataset.id);
        if (store) openStore(view, ctx, store);
      });
    });
    view.querySelector('#new-store')?.addEventListener('click', () => openCreate(view, ctx));
  },
};

export default storesPage;
