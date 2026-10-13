(function () {
  const rootId = "entry-manual-widget";
  const roles = ["submitter", "admin"];
  const labels = {
    submitter: "填报人员手册",
    admin: "管理员手册",
  };

  let currentUser = null;
  let manuals = [];
  let open = false;
  let busyRole = "";
  let message = "";

  async function requestJson(url, options) {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...options,
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || "请求失败");
    }
    return response.json();
  }

  function ensureRoot() {
    let root = document.getElementById(rootId);
    if (!root) {
      root = document.createElement("div");
      root.id = rootId;
      document.body.appendChild(root);
    }
    return root;
  }

  function manualByRole(role) {
    return manuals.find((manual) => manual.role === role) || {
      role,
      label: labels[role],
      available: false,
    };
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function render() {
    if (!currentUser) return;
    const root = ensureRoot();
    const admin = currentUser.role === "admin";
    const visibleRoles = admin ? roles : ["submitter"];
    root.innerHTML = `
      <button class="manual-fab" type="button" aria-expanded="${open}" aria-controls="manual-panel">
        <span aria-hidden="true">?</span>
        <strong>操作手册</strong>
      </button>
      <section id="manual-panel" class="manual-panel ${open ? "open" : ""}" aria-label="操作手册">
        <header>
          <div>
            <h2>操作手册</h2>
            <p>${admin ? "查看或更新平台手册文件" : "查看填报操作说明"}</p>
          </div>
          <button class="manual-close" type="button" aria-label="关闭">×</button>
        </header>
        <div class="manual-list">
          ${visibleRoles.map(renderManual).join("")}
        </div>
        ${message ? `<p class="manual-message">${escapeHtml(message)}</p>` : ""}
      </section>
    `;

    root.querySelector(".manual-fab").addEventListener("click", () => {
      open = !open;
      message = "";
      render();
    });
    root.querySelector(".manual-close").addEventListener("click", () => {
      open = false;
      message = "";
      render();
    });
    root.querySelectorAll("[data-upload-role]").forEach((input) => {
      input.addEventListener("change", () => uploadManual(input.dataset.uploadRole, input.files[0]));
    });
  }

  function renderManual(role) {
    const manual = manualByRole(role);
    const admin = currentUser.role === "admin";
    return `
      <article class="manual-card">
        <div>
          <strong>${escapeHtml(manual.label)}</strong>
          <span>${manual.available ? escapeHtml(manual.filename || "已上传") : "尚未上传"}</span>
        </div>
        <div class="manual-actions">
          ${
            manual.available
              ? `<a class="manual-link" href="${manual.url}" target="_blank" rel="noopener">打开</a>`
              : `<button class="manual-link disabled" type="button" disabled>打开</button>`
          }
          ${
            admin
              ? `<label class="manual-upload ${busyRole === role ? "busy" : ""}">
                  ${busyRole === role ? "上传中" : "更新"}
                  <input type="file" accept=".html,.pdf,text/html,application/pdf" data-upload-role="${role}">
                </label>`
              : ""
          }
        </div>
      </article>
    `;
  }

  async function uploadManual(role, file) {
    if (!file) return;
    const name = file.name.toLowerCase();
    if (!name.endsWith(".html") && !name.endsWith(".pdf")) {
      message = "操作手册仅支持 HTML 或 PDF 文件";
      render();
      return;
    }
    busyRole = role;
    message = "";
    render();
    const data = new FormData();
    data.append("file", file);
    try {
      await requestJson(`/api/manuals/${role}`, { method: "POST", body: data });
      await loadManuals();
      message = `${labels[role]}已更新`;
    } catch (error) {
      message = error.message;
    } finally {
      busyRole = "";
      render();
    }
  }

  async function loadManuals() {
    const result = await requestJson("/api/manuals");
    manuals = result.manuals || [];
  }

  async function init() {
    try {
      const me = await requestJson("/api/me");
      currentUser = me.user;
      await loadManuals();
      render();
    } catch (_) {
      const root = document.getElementById(rootId);
      if (root) root.remove();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
