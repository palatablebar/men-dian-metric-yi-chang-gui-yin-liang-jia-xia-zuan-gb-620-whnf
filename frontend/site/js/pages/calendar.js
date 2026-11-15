import { api } from '../api.js';
import { ENUMS, can } from '../config.js';
import { drawer, errorBox, errorMessage, esc, field, kv, table, toast } from '../ui.js';

const state = { q: '', dayType: '', storeId: '' };

function ruleForm(values = {}) {
  return `<form id="rule-form" class="stack">
    ${field({ label: '门店', name: 'store_id', value: values.store_id || '', placeholder: '门店 ID（可在门店页查看）', attrs: 'required' })}
    ${field({ label: '特殊日类型', name: 'day_type', value: values.day_type || 'promo', options: Object.entries(ENUMS.calendarDayType).map(([value, label]) => ({ value, label })) })}
    ${field({ label: '生效开始（含）', name: 'start_date', value: values.start_date || '2026-11-11', placeholder: 'YYYY-MM-DD' })}
    ${field({ label: '生效结束（含）', name: 'end_date', value: values.end_date || '2026-11-11', placeholder: 'YYYY-MM-DD' })}
    ${field({ label: '标签', name: 'label', value: values.label || '', placeholder: '例如：双十一大促 / 客房层改造' })}
    ${field({ label: '备注', name: 'note', value: values.note || '', placeholder: '为什么不计入常态基线' })}
    <p class="muted small">保存后会产生新的日历版本：受影响门店的待处理异常与草稿报告失效重算，<b>已发布报告保留原引用</b>。</p>
    <div class="form-error" id="rule-error"></div>
    <button class="btn accent" type="submit">保存规则</button>
  </form>`;
}

function openCreate(view, ctx) {
  const { root, close } = drawer({
    title: '新增门店运营日历',
    subtitle: '特殊日不进入常态基线，当期结果仍按真实经营结果说明',
    body: ruleForm({ store_id: state.storeId }),
  });
  root.querySelector('#rule-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      const result = await api.calendar.create({
        store_id: Number(form.store_id.value),
        day_type: form.day_type.value,
        start_date: form.start_date.value,
        end_date: form.end_date.value || form.start_date.value,
        label: form.label.value.trim() || null,
        note: form.note.value.trim() || null,
      });
      toast(`规则已保存 · 日历 v${result.calendar_version} · 失效重算 ${result.job ? result.job.status : '未执行'}`);
      close();
      await calendarPage.render(view, ctx);
    } catch (err) {
      root.querySelector('#rule-error').textContent = errorMessage(err);
    }
  });
}

function openRule(view, ctx, rule) {
  const { root, close } = drawer({
    title: `${rule.store_name || '门店#' + rule.store_id} · ${rule.day_type_label}`,
    subtitle: `${rule.start_date} → ${rule.end_date}（${rule.days} 天）· 日历 v${rule.calendar_version}`,
    body: `${kv([
      ['门店编码', esc(rule.store_code || '—')],
      ['特殊日类型', esc(rule.day_type_label)],
      ['生效区间', `${esc(rule.start_date)} → ${esc(rule.end_date)}（含端点）`],
      ['标签', esc(rule.label || '—')],
      ['备注', esc(rule.note || '—')],
      ['状态', rule.active ? '生效中' : '已停用'],
      ['创建人', esc(rule.created_by || '—')],
    ])}`,
    footer: can(ctx.user.role, 'calendar:write') && rule.active
      ? `<div class="footer-actions">
          <button class="btn ghost" data-deactivate>停用该规则（触发失效重算）</button>
        </div>`
      : '<span class="mono muted">只读角色仅可查看</span>',
  });
  root.querySelector('[data-deactivate]')?.addEventListener('click', async () => {
    try {
      const result = await api.calendar.deactivate(rule.id);
      toast(`已停用 · 日历 v${result.calendar_version}`);
      close();
      await calendarPage.render(view, ctx);
    } catch (err) {
      toast(errorMessage(err), 'err');
    }
  });
}

function openStoreCalendar(view, ctx, storeId) {
  if (!storeId) {
    toast('先选择一家门店', 'err');
    return;
  }
  api.calendar.forStore(storeId).then((data) => {
    const days = (data.days || []).slice().reverse();
    const { root } = drawer({
      title: `${data.store_name} · 运营日历`,
      subtitle: `${data.store_code} · 日历 v${data.calendar_version}`,
      body: `${kv([
        ['数据窗口', `${esc(data.data_window.start || '—')} → ${esc(data.data_window.end || '—')}`],
        ['纳入常态基线', `${data.included_day_count} 天`],
        ['排除（特殊日）', `${data.excluded_day_count} 天`],
        ['规则条数', `${data.rules.length} 条`],
      ])}
      <h3 class="sub-head">逐日纳入 / 排除（最近 90 天，倒序）</h3>
      ${table({
        rows: days.map((item) => ({ id: item.date, ...item })),
        columns: [
          { key: 'date', label: '日期', className: 'mono' },
          { key: 'day_type_label', label: '类型', render: (row) => (row.included ? '<span class="badge ok">常态日</span>' : `<span class="badge warn">${esc(row.day_type_label)}</span>`) },
          { key: 'included', label: '是否纳入基线', render: (row) => (row.included ? '<span class="pos">纳入</span>' : '<span class="neg">排除</span>') },
        ],
        empty: { title: '这家店还没有指标点', hint: '接入指标后再看日历。' },
      })}
      <h3 class="sub-head">规则明细</h3>
      ${table({
        rows: data.rules.map((item) => ({ id: item.id, ...item })),
        columns: [
          { key: 'day_type_label', label: '类型' },
          { key: 'start_date', label: '开始', className: 'mono' },
          { key: 'end_date', label: '结束', className: 'mono' },
          { key: 'days', label: '天数', className: 'num' },
          { key: 'active', label: '状态', render: (row) => (row.active ? '生效中' : '已停用') },
        ],
      })}`,
    });
    root.querySelectorAll('table.data').forEach((tableNode) => {
      tableNode.querySelectorAll('tbody tr').forEach((row) => {
        const rule = data.rules.find((item) => String(item.id) === row.dataset.id);
        if (!rule) return;
        row.addEventListener('click', () => toast(`${rule.day_type_label} · ${rule.start_date} → ${rule.end_date}`));
      });
    });
  }).catch((err) => toast(errorMessage(err), 'err'));
}

export const calendarPage = {
  async render(view, ctx) {
    state.q = ctx.query.q ?? state.q;
    if (ctx.query.store_id) state.storeId = ctx.query.store_id;
    let data;
    let revisions;
    let jobs;
    try {
      [data, revisions, jobs] = await Promise.all([
        api.calendar.list({ store_id: state.storeId || undefined, day_type: state.dayType || undefined, limit: 100 }),
        api.calendar.revisions({ limit: 8 }),
        api.calendar.jobs({ limit: 6 }),
      ]);
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => calendarPage.render(view, ctx));
      return;
    }
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>运营日历 <span class="mono muted">· 日历 v${data.calendar_version}</span></h2>
          <div class="head-actions">
            <span class="meta">${data.total} 条规则</span>
            ${can(ctx.user.role, 'calendar:write') ? '<button class="btn sm accent" id="new-rule">新增特殊日</button>' : ''}
          </div>
        </div>
        <div class="panel-body">
          <div class="filter-bar" id="calendar-filters">
            ${field({ label: '门店 ID', name: 'store_id', value: state.storeId, placeholder: '例如 1' })}
            ${field({ label: '类型', name: 'day_type', value: state.dayType, options: [{ value: '', label: '全部' }, ...data.day_types.map((item) => ({ value: item.key, label: item.label }))] })}
            <div class="spacer"></div>
            <button class="btn sm ghost" id="view-store-calendar">查看门店纳入/排除日期</button>
          </div>
          <p class="muted small">停业改造、临时闭店、大促日都按特殊日处理：<b>不计入常态基线</b>，避免可比样本被特殊日污染；当期异常仍按真实经营结果说明。</p>
        </div>
        ${table({
          rows: data.items,
          columns: [
            { key: 'store_name', label: '门店', render: (row) => `<b>${esc(row.store_name || '门店#' + row.store_id)}</b><div class="mono muted">${esc(row.store_code || '')}</div>` },
            { key: 'day_type_label', label: '类型', render: (row) => `<span class="badge warn">${esc(row.day_type_label)}</span>` },
            { key: 'start_date', label: '生效开始', className: 'mono' },
            { key: 'end_date', label: '生效结束', className: 'mono' },
            { key: 'days', label: '天数', className: 'num' },
            { key: 'active', label: '状态', render: (row) => (row.active ? '<span class="badge ok">生效中</span>' : '<span class="badge">已停用</span>') },
            { key: 'calendar_version', label: '版本', className: 'num', render: (row) => `v${row.calendar_version}` },
          ],
          empty: { title: '还没有运营日历', hint: '管理员可以按门店登记特殊日（改造 / 闭店 / 大促）。' },
        })}
      </section>

      <div class="grid-2">
        <section class="panel">
          <div class="panel-head"><h2>日历版本</h2><span class="meta">每次规则变更递增</span></div>
          ${table({
            rows: revisions.items,
            columns: [
              { key: 'version', label: '版本', className: 'mono', render: (row) => `v${row.version}` },
              { key: 'summary', label: '变更内容' },
              { key: 'action', label: '动作' },
              { key: 'created_at', label: '时间', className: 'mono', render: (row) => esc((row.created_at || '').slice(0, 19).replace('T', ' ')) },
            ],
          })}
        </section>
        <section class="panel">
          <div class="panel-head"><h2>失效重算任务</h2><span class="meta">中断可续跑 · 同版本幂等</span></div>
          ${table({
            rows: jobs.items,
            columns: [
              { key: 'job_no', label: '任务', className: 'mono' },
              { key: 'calendar_version', label: '版本', className: 'num', render: (row) => `v${row.calendar_version}` },
              { key: 'status', label: '状态', render: (row) => `<span class="badge ${row.status === 'success' ? 'ok' : row.status === 'failed' ? 'warn' : 'pending'}">${esc(ENUMS.jobStatus[row.status] || row.status)}</span>` },
              { key: 'stage', label: '阶段', className: 'mono' },
              { key: 'idempotent_hit', label: '幂等命中', render: (row) => (row.idempotent_hit ? '是' : '—') },
            ],
          })}
        </section>
      </div>`;
    const filters = view.querySelector('#calendar-filters');
    filters?.querySelector('[name=store_id]')?.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      state.storeId = event.target.value.trim();
      calendarPage.render(view, ctx);
    });
    filters?.querySelector('[name=day_type]')?.addEventListener('change', (event) => {
      state.dayType = event.target.value;
      calendarPage.render(view, ctx);
    });
    view.querySelector('#view-store-calendar')?.addEventListener('click', () => openStoreCalendar(view, ctx, state.storeId || filters.querySelector('[name=store_id]').value.trim()));
    const ruleTable = view.querySelector('section.panel table.data');
    ruleTable?.querySelectorAll('tbody tr').forEach((row) => {
      row.addEventListener('click', () => {
        const rule = data.items.find((item) => String(item.id) === row.dataset.id);
        if (rule) openRule(view, ctx, rule);
      });
    });
    view.querySelector('#new-rule')?.addEventListener('click', () => openCreate(view, ctx));
  },
};

export default calendarPage;
