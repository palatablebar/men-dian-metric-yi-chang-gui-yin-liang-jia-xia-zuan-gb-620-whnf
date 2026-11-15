import { api } from '../api.js';
import { session } from '../store.js';
import { BRAND } from '../config.js';
import { errorMessage, esc, toast } from '../ui.js';

/** 登录页版式：夜审交接单（左交接单 + 右签收）。 */
export const loginPage = {
  async render(root, ctx) {
    root.className = 'login-host';
    root.innerHTML = `
      <div class="login">
        <section class="login-brief">
          <div class="brief-head">
            <div class="eyebrow">${esc(BRAND.edition)}</div>
            <h1>夜审<br /><em>交接单</em></h1>
            <div class="stamp">蓝湾酒店集团<br />经营分析组</div>
          </div>
          <dl class="brief-meta">
            <div><dt>班次</dt><dd>${esc(BRAND.shift)}</dd></div>
            <div><dt>覆盖</dt><dd>120 家门店 · 3 个渠道</dd></div>
            <div><dt>值班经理</dt><dd>顾青</dd></div>
            <div><dt>交接对象</dt><dd>经营分析组 · 区域经理</dd></div>
          </dl>
          <div class="brief-points">
            ${BRAND.loginPoints
              .map(([no, text]) => `<div class="brief-point"><i>${esc(no)}</i><span>${esc(text)}</span></div>`)
              .join('')}
          </div>
          <p class="hand-note-inline">${esc(BRAND.handNote)}</p>
          <div class="eyebrow">${esc(BRAND.org)} · 内部工作台</div>
        </section>
        <section class="login-form-wrap">
          <form class="login-card" id="login-form" novalidate>
            <div class="sign-head">
              <div class="eyebrow">交接收货 · SIGN IN</div>
              <div class="brand">${esc(BRAND.title)}</div>
              <div class="sub">三个演示账号权限不同，页面、按钮与接口返回都会随角色变化。</div>
            </div>
            <div class="field">
              <label for="email">交接人邮箱</label>
              <input id="email" name="email" type="email" autocomplete="username" value="admin@${esc(BRAND.short)}.io" required />
            </div>
            <div class="field">
              <label for="password">口令</label>
              <input id="password" name="password" type="password" autocomplete="current-password" value="Demo@2026" required />
            </div>
            <div class="form-error" id="login-error" role="alert"></div>
            <button class="btn accent" id="login-submit" type="submit">签收并进入交接本</button>
            <div class="login-hint">
              演示账号（口令 <code>Demo@2026</code>）：<br />
              <code>admin@${esc(BRAND.short)}.io</code> 管理员 · <code>analyst@${esc(BRAND.short)}.io</code> 分析师 ·
              <code>viewer@${esc(BRAND.short)}.io</code> 只读
            </div>
          </form>
        </section>
      </div>`;

    const form = root.querySelector('#login-form');
    const errorNode = root.querySelector('#login-error');
    const submit = root.querySelector('#login-submit');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      errorNode.textContent = '';
      submit.disabled = true;
      submit.textContent = '正在核对…';
      try {
        const result = await api.post('/api/auth/login', {
          email: form.email.value.trim(),
          password: form.password.value,
        });
        session.set(result.access_token, result.user);
        toast(`交接完成，${result.user.display_name}`);
        location.hash = '#/overview';
        await ctx.reload();
      } catch (err) {
        errorNode.textContent = err.code === 'AUTH_INVALID' ? '账号或口令不正确' : errorMessage(err);
      } finally {
        submit.disabled = false;
        submit.textContent = '签收并进入交接本';
      }
    });
  },
};

export default loginPage;
