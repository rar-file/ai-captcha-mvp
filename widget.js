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
      el("div", { class: "aicaptcha__brand" }, [
        el("div", { class: "aicaptcha__logo", text: "AI" }),
        el("div", {}, [
          el("div", { class: "aicaptcha__title", text: "AI Verification" }),
          el("div", { class: "aicaptcha__meta", text: "quick check before continuing" })
        ])
      ]),
      el("div", { class: "aicaptcha__meta", text: `sitekey: ${sitekey}` }),
    ]);

    const checkInput = el("input", { type: "checkbox" });
    const checkBox = el("label", { class: "aicaptcha__checkbox" }, [checkInput]);

    const checkRow = el("div", { class: "aicaptcha__checkrow" }, [
      el("div", { class: "aicaptcha__checkleft" }, [
        checkBox,
        el("div", { class: "aicaptcha__label", text: "I’m not a human (AI/agent check)" })
      ]),
      el("div", { class: "aicaptcha__badge", text: "privacy-friendly" })
    ]);

    const body = el("div", { class: "aicaptcha__body" });
    const panel = el("div", { class: "aicaptcha__panel" });
    const status = el("div", { class: "aicaptcha__status" });

    const table = el("div", { class: "aicaptcha__table" });

    const input = el("input", { class: "aicaptcha__input", placeholder: "answer", autocomplete: "off" });
    const btnVerify = el("button", { class: "aicaptcha__btn aicaptcha__btn--primary", type: "button", text: "Verify" });
    const btnCopy = el("button", { class: "aicaptcha__btn", type: "button", text: "Copy prompt" });
    const btnReload = el("button", { class: "aicaptcha__btn", type: "button", text: "New" });

    const controls = el("div", { class: "aicaptcha__controls" }, [btnVerify, btnCopy, btnReload]);

    panel.appendChild(table);
    panel.appendChild(controls);
    panel.appendChild(input);

    body.appendChild(panel);

    root.innerHTML = "";
    root.appendChild(header);
    root.appendChild(checkRow);
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
          status.textContent = `not verified (${res.reason || "fail"})${left}`;
          btnVerify.disabled = false;
          return;
        }

        const token = res.token;
        const score = res.score;
        status.innerHTML = `✅ <strong>verified</strong> • score ${typeof score === 'number' ? score.toFixed(2) : score}`;

        const tgt = document.getElementById(tokenTarget) || document.querySelector(`[name='${tokenTarget}']`);
        if (tgt) tgt.value = token;

        root.dispatchEvent(new CustomEvent("aicaptcha:verified", { detail: { token, score, sitekey, puzzle_id: puzzle.puzzle_id } }));
        if (typeof window.aiCaptchaVerified === "function") {
          window.aiCaptchaVerified({ token, score, sitekey, puzzle_id: puzzle.puzzle_id });
        }

        // lock
        btnVerify.disabled = true;
        input.disabled = true;
        btnReload.disabled = false;

      } catch (e) {
        status.textContent = `error: ${e.message || e}`;
        btnVerify.disabled = false;
      }
    }

    checkInput.addEventListener("change", async () => {
      if (checkInput.checked) {
        root.classList.add("aicaptcha--open");
        input.disabled = false;
        btnReload.disabled = false;
        await load();
      } else {
        root.classList.remove("aicaptcha--open");
      }
    });

    btnVerify.addEventListener("click", verify);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") verify(); });

    btnCopy.addEventListener("click", async () => {
      if (!puzzle) return;
      const txt = buildPrompt(puzzle);
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(txt);
        } else {
          // fallback for older/locked-down browsers
          const ta = document.createElement('textarea');
          ta.value = txt;
          ta.style.position = 'fixed';
          ta.style.left = '-9999px';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          ta.remove();
        }
        status.textContent = "prompt copied";
      } catch {
        status.textContent = "copy failed";
      }
    });

    btnReload.addEventListener("click", async () => {
      input.disabled = false;
      btnVerify.disabled = false;
      await load();
    });

    // start closed (captcha feel)
    status.textContent = "check the box to start";
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
