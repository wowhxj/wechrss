(() => {
  "use strict";

  const toast = document.querySelector(".toast");
  let toastTimer;

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 1800);
  }

  async function copyText(value) {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
    } catch (_) {
      const field = document.createElement("textarea");
      field.value = value;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      document.execCommand("copy");
      field.remove();
    }
    showToast("已复制到剪贴板");
  }

  document.addEventListener("click", (event) => {
    const dismiss = event.target.closest("[data-dismiss]");
    if (dismiss) {
      dismiss.closest(".flash")?.remove();
      return;
    }

    const trigger = event.target.closest("[data-copy], [data-copy-target]");
    if (!trigger) return;
    const target = trigger.dataset.copyTarget
      ? document.querySelector(trigger.dataset.copyTarget)
      : null;
    copyText(target ? target.value || target.textContent : trigger.dataset.copy);
  });

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  document.querySelectorAll("form[data-loading-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (event.defaultPrevented) return;
      const button = form.querySelector('button[type="submit"], button:not([type])');
      if (!button) return;
      button.disabled = true;
      button.dataset.originalLabel = button.textContent.trim();
      button.textContent = form.dataset.loadingLabel || "处理中…";
    });
  });

  const loginPanel = document.querySelector("[data-login-panel]");
  if (loginPanel) {
    const active = new Set(["requesting", "waiting", "scanned", "exchanging", "initializing"]);
    const labels = {
      idle: "空闲",
      requesting: "正在生成",
      waiting: "等待扫码",
      scanned: "等待确认",
      exchanging: "正在登录",
      initializing: "正在初始化",
      success: "已登录",
      expired: "已过期",
      declined: "已拒绝",
      cancelled: "已取消",
      error: "失败",
    };
    const titles = {
      requesting: "正在生成二维码",
      waiting: "等待微信扫码",
      scanned: "已扫码，请在手机上确认",
      exchanging: "正在连接微信读书",
      initializing: "正在初始化账号",
      success: "账号连接成功",
      expired: "二维码已过期",
      declined: "本次登录已拒绝",
      cancelled: "扫码登录已取消",
      error: "登录没有完成",
    };
    const badge = document.getElementById("login-badge");
    const title = document.getElementById("login-title");
    const message = document.getElementById("login-message");
    const wrap = document.getElementById("qr-wrap");
    const image = document.getElementById("qr-image");

    function applyLoginState(state) {
      const status = state.status || "idle";
      if (badge) {
        badge.textContent = labels[status] || status;
        badge.className = "badge " + status;
      }
      if (title && titles[status]) title.textContent = titles[status];
      if (message && state.message) message.textContent = state.message;
      if (wrap && image) {
        if (state.qr) {
          image.src = state.qr;
          wrap.hidden = false;
        } else {
          wrap.hidden = true;
          image.removeAttribute("src");
        }
      }
      return status;
    }

    async function pollLogin() {
      try {
        const response = await fetch("/api/login/status", {
          cache: "no-store",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) throw new Error("status request failed");
        const state = await response.json();
        const status = applyLoginState(state);
        if (status === "success") {
          setTimeout(() => {
            window.location.href = "/settings?message=" + encodeURIComponent("扫码登录成功");
          }, 700);
          return;
        }
        if (active.has(status)) setTimeout(pollLogin, 1200);
      } catch (_) {
        setTimeout(pollLogin, 2500);
      }
    }

    pollLogin();
  }
})();
