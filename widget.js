(() => {
  const API_BASE = (document.currentScript && new URL(document.currentScript.src).origin) || "";

  function el(tag, attrs = {}, children = []) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else n.setAttribute(k, v);
    }
    for (const c of children) n.appendChild(c);
    return n;
  }

  function escapeText(s) {
    return (s || "").replace(/[&<>]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch]));
  }

  function buildPrompt(p) {
    const lines = [];
    lines.push("Infer the transformation rule from these examples:");
    for (const ex of p.examples) lines.push(`${ex.input} -> ${ex.output}`);
    lines.push("");
    lines.push(`Apply the same rule to: ${p.challenge}`);
    lines.push("Return ONLY the final transformed string.");
    return lines.join("\n");
  }

  async function fetchJSON(url, opts) {
    const r = await fetch(url, opts);
    const t = await r.text();
    let j;
    try { j = JSON.parse(t); } catch { j = { raw: t }; }
    if (!r.ok) throw new Error(j.error || j.detail || `HTTP ${r.status}`);
    return j;
  }

  async function initOne(root) {
    const sitekey = root.dataset.sitekey || "public-demo";
    const action = root.dataset.action || "default";
    const tokenTarget = root.dataset.tokenTarget || "ai_captcha_token";

    root.classList.add("aicaptcha");

    const header = el("div", { class: "aicaptcha__header" }, [
      el("div", { class: "aicaptcha__title", text: "AI Check" }),
      el("div", { class: "aicaptcha__meta", text: `sitekey: ${sitekey}` }),
    ]);

    const body = el("div", { class: "aicaptcha__body" });
    const status = el("div", { class: "aicaptcha__status" });

    const table = el("div", { class: "aicaptcha__table" });

    const input = el("input", { class: "aicaptcha__input", placeholder: "answer…", autocomplete: "off" });
    const btnVerify = el("button", { class: "aicaptcha__btn", type: "button", text: "verify" });
    const btnCopy = el("button", { class: "aicaptcha__btn aicaptcha__btn--secondary", type: "button", text: "copy prompt" });
    const btnReload = el("button", { class: "aicaptcha__btn aicaptcha__btn--secondary", type: "button", text: "new" });

    const controls = el("div", { class: "aicaptcha__controls" }, [btnVerify, btnCopy, btnReload]);

    body.appendChild(table);
    body.appendChild(controls);
    body.appendChild(input);

    root.innerHTML = "";
    root.appendChild(header);
    root.appendChild(body);
    root.appendChild(status);

    let puzzle = null;

    async function load() {
      status.textContent = "loading…";
      input.value = "";
      btnVerify.disabled = true;
      puzzle = await fetchJSON(`${API_BASE}/generate?sitekey=${encodeURIComponent(sitekey)}`);
      btnVerify.disabled = false;

      table.innerHTML = "";
      const ex = el("div", { class: "aicaptcha__examples" });
      for (const row of puzzle.examples) {
        ex.appendChild(el("div", { class: "aicaptcha__row" }, [
          el("div", { class: "aicaptcha__cell", text: row.input }),
          el("div", { class: "aicaptcha__arrow", text: "→" }),
          el("div", { class: "aicaptcha__cell", text: row.output }),
        ]));
      }
      const ch = el("div", { class: "aicaptcha__challenge" }, [
        el("div", { class: "aicaptcha__cell", text: puzzle.challenge }),
        el("div", { class: "aicaptcha__arrow", text: "→" }),
        el("div", { class: "aicaptcha__cell aicaptcha__cell--empty", text: "?" }),
      ]);
      table.appendChild(ex);
      table.appendChild(ch);

      status.textContent = `difficulty ${puzzle.difficulty} • attempts ${puzzle.max_attempts}`;
    }

    async function verify() {
      if (!puzzle) return;
      const answer = input.value.trim();
      if (!answer) return;

      btnVerify.disabled = true;
      status.textContent = "verifying…";
      try {
        const res = await fetchJSON(`${API_BASE}/verify`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ puzzle_id: puzzle.puzzle_id, answer, action })
        });

        if (!res.pass) {
          const left = res.attempts_left != null ? ` • left ${res.attempts_left}` : "";
          status.textContent = `nope (${res.reason || "fail"})${left}`;
          btnVerify.disabled = false;
          return;
        }

        // success
        const token = res.token;
        const score = res.score;
        status.textContent = `✅ verified (score ${score?.toFixed ? score.toFixed(2) : score})`;

        const tgt = document.getElementById(tokenTarget) || document.querySelector(`[name='${tokenTarget}']`);
        if (tgt) tgt.value = token;

        // emit event hook (idea #9)
        root.dispatchEvent(new CustomEvent("aicaptcha:verified", { detail: { token, score, sitekey, puzzle_id: puzzle.puzzle_id } }));
        if (typeof window.aiCaptchaVerified === "function") {
          window.aiCaptchaVerified({ token, score, sitekey, puzzle_id: puzzle.puzzle_id });
        }

        // lock widget
        btnVerify.disabled = true;
        input.disabled = true;

      } catch (e) {
        status.textContent = `error: ${e.message || e}`;
        btnVerify.disabled = false;
      }
    }

    btnVerify.addEventListener("click", verify);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") verify(); });

    btnCopy.addEventListener("click", async () => {
      if (!puzzle) return;
      const txt = buildPrompt(puzzle);
      try {
        await navigator.clipboard.writeText(txt);
        status.textContent = "copied prompt";
      } catch {
        status.textContent = "copy failed";
      }
    });

    btnReload.addEventListener("click", async () => {
      input.disabled = false;
      btnVerify.disabled = false;
      await load();
    });

    await load();
  }

  async function boot() {
    const roots = document.querySelectorAll(".ai-captcha");
    for (const r of roots) {
      try { await initOne(r); } catch (e) { console.error("aicaptcha init failed", e); }
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
