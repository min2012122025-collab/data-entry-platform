(() => {
  'use strict';
  let brand = { name: '通用录入平台', logo_url: '/assets/default-brand.svg' };
  let user = null;
  let checkingUser = false;
  let timer;

  async function request(url, options = {}) {
    const response = await fetch(url, { credentials: 'same-origin', ...options });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请检查输入内容');
    return data;
  }

  function setText(element, value) {
    if (element && element.textContent !== value) element.textContent = value;
  }

  function applyBrand() {
    document.title = brand.name;
    document.querySelectorAll('.brand-copy strong, .login-brand h1').forEach(el => setText(el, brand.name));
    document.querySelectorAll('.brand-ring').forEach(el => {
      const background = `url("${brand.logo_url}")`;
      if (el.style.backgroundImage !== background) el.style.backgroundImage = background;
    });
    document.querySelectorAll('.login-department').forEach(el => {
      // Preserve the image element managed by the existing application.
      const node = [...el.childNodes].find(n => n.nodeType === Node.TEXT_NODE);
      if (node && node.textContent !== brand.name) node.textContent = brand.name;
    });
  }

  function mountSettings(tabs) {
    if (document.getElementById('brand-settings')) return;
    const panel = document.createElement('details');
    panel.id = 'brand-settings';
    panel.innerHTML = `
      <summary>主题设置</summary>
      <form class="brand-settings-form">
        <label>平台名称<input name="platform-name" maxlength="60" required autocomplete="off"></label>
        <button type="submit">保存名称</button>
      </form>
      <div class="brand-logo-settings">
        <img alt="当前品牌图片" width="64" height="64">
        <label class="brand-upload">上传品牌图片<input type="file" accept="image/png,image/jpeg,image/webp"></label>
        <button type="button" data-reset-logo>恢复默认图标</button>
      </div>
      <p class="brand-help">支持 PNG、JPEG、WebP，最大 2MB，尺寸不超过 2048 × 2048。</p>
      <p role="status" aria-live="polite"></p>`;
    const input = panel.querySelector('[name="platform-name"]');
    const preview = panel.querySelector('img');
    const status = panel.querySelector('[role="status"]');
    input.value = brand.name;
    preview.src = brand.logo_url;
    let busy = false;
    async function change(options, url, success) {
      if (busy) return;
      busy = true;
      panel.querySelectorAll('button, input').forEach(el => { el.disabled = true; });
      status.textContent = '正在保存…';
      try {
        brand = await request(url, options);
        input.value = brand.name;
        preview.src = brand.logo_url;
        applyBrand();
        status.textContent = success;
      } catch (error) {
        status.textContent = error.message;
      } finally {
        busy = false;
        panel.querySelectorAll('button, input').forEach(el => { el.disabled = false; });
      }
    }
    panel.querySelector('form').addEventListener('submit', event => {
      event.preventDefault();
      change({ method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: input.value }) }, '/api/branding', '平台名称已更新');
    });
    const fileInput = panel.querySelector('[type="file"]');
    fileInput.addEventListener('change', () => {
      const file = fileInput.files[0];
      if (!file) return;
      const body = new FormData();
      body.append('file', file);
      change({ method: 'POST', body }, '/api/branding/logo', '品牌图片已更新').finally(() => { fileInput.value = ''; });
    });
    panel.querySelector('[data-reset-logo]').addEventListener('click', () => {
      change({ method: 'DELETE' }, '/api/branding/logo', '已恢复默认图标');
    });
    tabs.before(panel);
  }

  async function sync() {
    applyBrand();
    if (document.querySelector('.login-page')) {
      user = null;
      document.getElementById('brand-settings')?.remove();
      return;
    }
    const tabs = document.querySelector('.settings-tabs');
    if (!tabs) return;
    if (!user && !checkingUser) {
      checkingUser = true;
      try { user = (await request('/api/me')).user; }
      catch { document.getElementById('brand-settings')?.remove(); }
      finally { checkingUser = false; }
    }
    if (user?.role === 'admin' && !user.must_change_password && tabs.isConnected) mountSettings(tabs);
  }

  async function init() {
    try { brand = await request('/api/branding'); } catch { /* Keep the default brand on temporary failure. */ }
    new MutationObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(sync, 50);
    }).observe(document.getElementById('root'), { childList: true, subtree: true });
    sync();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
