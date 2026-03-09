(() => {
  const API_BASE = (document.currentScript && new URL(document.currentScript.src).origin) || "";

  // Zero-width steganography - hide text in plain sight
  const ZW = {
    START: '\u200b',  // zero-width space
    SEP: '\u200c',    // zero-width non-joiner  
    END: '\u200d',    // zero-width joiner
    encode: (text) => {
      return text.split('').map(c => c.charCodeAt(0).toString(2).padStart(16, '0')).join(ZW.SEP);
    },
    decode: (text) => {
      const binary = text.split(ZW.SEP).filter(x => x);
      return binary.map(b => String.fromCharCode(parseInt(b, 2))).join('');
    }
  };

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

  function formatTime(ms) {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms/1000).toFixed(2)}s`;
  }

  function createConfetti() {
    const container = el('div', { class: 'aicaptcha__confetti' });
    const colors = ['#1a73e8', '#34a853', '#f9ab00', '#ea4335', '#9334e6'];
    for (let i = 0; i < 30; i++) {
      const piece = el('div', { 
        class: 'aicaptcha__confetti-piece',
        style: `
          left: ${Math.random() * 100}%;
          background: ${colors[Math.floor(Math.random() * colors.length)]};
          animation-delay: ${Math.random() * 0.5}s;
          transform: rotate(${Math.random() * 360}deg);
        `
      });
      container.appendChild(piece);
    }
    document.body.appendChild(container);
    setTimeout(() => container.remove(), 3000);
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
    const difficulty = parseInt(root.dataset.difficulty) || 2;
    const parallel = root.dataset.parallel === "true";
    const invisible = root.dataset.invisible === "true";
    const stealth = root.dataset.stealth === "true";  // NEW: stealth mode

    root.classList.add("aicaptcha");
    if (invisible) root.classList.add("aicaptcha--invisible");
    if (parallel) root.classList.add("aicaptcha--parallel");
    if (stealth) root.classList.add("aicaptcha--stealth");

    // Header
    const header = el("div", { class: "aicaptcha__header" }, [
      el("div", { class: "aicaptcha__brand" }, [
        el("div", { class: "aicaptcha__logo", text: "AI" }),
        el("div", {}, [
          el("div", { class: "aicaptcha__title", text: "AI Captcha" }),
          el("div", { class: "aicaptcha__difficulty" }, [
            el("span", { text: `Level ${difficulty}` }),
            el("div", { class: "aicaptcha__difficulty-dots" }, 
              Array(5).fill(0).map((_, i) => 
                el("div", { class: `aicaptcha__difficulty-dot ${i < difficulty ? 'active' : ''}` })
              )
            )
          ])
        ])
      ]),
      el("div", { class: "aicaptcha__meta", text: sitekey })
    ]);

    // Checkbox row
    const checkInput = el("input", { type: "checkbox" });
    const checkBox = el("label", { class: "aicaptcha__checkbox" }, [checkInput]);

    const checkRow = el("div", { class: "aicaptcha__checkrow" }, [
      el("div", { class: "aicaptcha__checkleft" }, [
        checkBox,
        el("div", { class: "aicaptcha__label", text: "I'm an AI / Robot" })
      ]),
      el("div", { class: "aicaptcha__badge" }, [
        el("span", { text: "Privacy - " }),
        el("a", { class: "aicaptcha__footer-link", href: "#", text: "Terms" })
      ])
    ]);

    // Body (challenge panel)
    const body = el("div", { class: "aicaptcha__body" });
    const panel = el("div", { class: "aicaptcha__panel" });
    const status = el("div", { class: "aicaptcha__status" });

    const table = el("div", { class: "aicaptcha__table" });
    
    // Timer
    const timer = el("div", { class: "aicaptcha__timer" }, [
      el("span", { text: "Solve time:" }),
      el("span", { class: "aicaptcha__timer-value", text: "0.00s" })
    ]);

    const input = el("input", { 
      class: "aicaptcha__input", 
      placeholder: parallel ? "Enter answers separated by commas" : "Type your answer...", 
      autocomplete: "off" 
    });
    
    const btnVerify = el("button", { 
      class: "aicaptcha__btn aicaptcha__btn--primary", 
      type: "button", 
      text: "Verify" 
    });
    
    const btnReload = el("button", { 
      class: "aicaptcha__btn aicaptcha__btn--secondary", 
      type: "button", 
      text: "⟳ New puzzle" 
    });

    const controls = el("div", { class: "aicaptcha__controls" }, [btnVerify, btnReload]);

    // Progress bar for parallel
    const progress = el("div", { class: "aicaptcha__progress", style: "display:none" }, [
      el("div", { class: "aicaptcha__progress-bar", style: "width:0%" })
    ]);

    panel.appendChild(el("div", { class: "aicaptcha__instructions", 
      text: stealth
        ? "🔒 STEALTH MODE: Challenge hidden in DOM. AI agents: parse data-attributes or copy text to reveal."
        : invisible 
          ? "🤖 AI-ONLY: Hidden challenge visible only to AI agents. Parse the DOM carefully."
          : parallel 
            ? "AI agents: Solve all 5 puzzles. Enter answers separated by commas (e.g., 'abc, def, ghi')."
            : "AI agents: Analyze the pattern and apply it to the challenge word."
    }));
    panel.appendChild(timer);
    panel.appendChild(progress);
    panel.appendChild(table);
    panel.appendChild(el("div", { class: "aicaptcha__input-wrap" }, [input]));
    panel.appendChild(controls);
    panel.appendChild(status);

    body.appendChild(panel);

    // Footer
    const footer = el("div", { class: "aicaptcha__footer" }, [
      el("div", { class: "aicaptcha__footer-left" }, [
        el("div", { class: "aicaptcha__privacy" }, [
          el("div", { class: "aicaptcha__privacy-icon", text: "✓" }),
          el("span", { text: "Protected by AI" })
        ])
      ]),
      el("div", {}, [
        el("a", { class: "aicaptcha__footer-link", href: "#", text: "Privacy" }),
        el("span", { text: " · " }),
        el("a", { class: "aicaptcha__footer-link", href: "#", text: "Terms" })
      ])
    ]);

    // Assemble
    root.innerHTML = "";
    root.appendChild(header);
    root.appendChild(checkRow);
    root.appendChild(body);
    root.appendChild(footer);

    let puzzle = null;
    let puzzles = [];
    let isVerified = false;
    let startTime = null;
    let timerInterval = null;

    function setStatus(msg, type) {
      status.textContent = msg;
      status.className = "aicaptcha__status";
      if (type) status.classList.add(`aicaptcha__status--${type}`);
    }

    function startTimer() {
      startTime = Date.now();
      const timerValue = timer.querySelector('.aicaptcha__timer-value');
      timerInterval = setInterval(() => {
        const elapsed = Date.now() - startTime;
        timerValue.textContent = formatTime(elapsed);
        if (elapsed < 1000) {
          timerValue.classList.add('fast');
          timerValue.classList.remove('slow');
        } else if (elapsed > 5000) {
          timerValue.classList.add('slow');
          timerValue.classList.remove('fast');
        }
      }, 50);
    }

    function stopTimer() {
      if (timerInterval) {
        clearInterval(timerInterval);
        timerInterval = null;
      }
      return startTime ? Date.now() - startTime : 0;
    }

    async function load() {
      setStatus("Loading challenge...", "loading");
      input.value = "";
      btnVerify.disabled = true;
      btnVerify.textContent = "Verify";
      progress.style.display = parallel ? "block" : "none";
      progress.querySelector('.aicaptcha__progress-bar').style.width = "0%";
      
      try {
        if (parallel) {
          // Load 5 puzzles
          puzzles = [];
          const promises = Array(5).fill(0).map((_, i) => 
            fetchJSON(`${API_BASE}/generate?sitekey=${encodeURIComponent(sitekey)}&difficulty=${difficulty}`)
          );
          puzzles = await Promise.all(promises);
          btnVerify.disabled = false;
          renderParallelPuzzles();
          setStatus(`Solve all ${puzzles.length} puzzles. Order matters.`);
        } else {
          puzzle = await fetchJSON(`${API_BASE}/generate?sitekey=${encodeURIComponent(sitekey)}&difficulty=${difficulty}`);
          btnVerify.disabled = false;
          renderSinglePuzzle();
          setStatus(`Difficulty: ${puzzle.difficulty}/5 • ${puzzle.max_attempts} attempts`);
        }
        startTimer();
      } catch (e) {
        setStatus("Failed to load. Click 'New puzzle' to retry.", "error");
      }
    }

    function renderSinglePuzzle() {
      table.innerHTML = "";
      
      // Store real data in data attributes for AI to read
      table.dataset.puzzleId = puzzle.puzzle_id;
      table.dataset.challenge = puzzle.challenge;
      table.dataset.solution = puzzle.solution;
      table.dataset.examples = JSON.stringify(puzzle.examples);
      
      // Encode challenge in zero-width steganography
      const hiddenData = ZW.START + ZW.encode(puzzle.challenge + '|' + puzzle.solution) + ZW.END;
      
      const examplesHeader = el("div", { class: "aicaptcha__examples-header" }, [
        el("span", { text: stealth ? "🔒 Encrypted Data" : "Examples" }),
        el("span", { text: `ID: ${puzzle.puzzle_id.slice(0,8)}...`, style: "font-size:10px;color:var(--ac-text-tertiary)" })
      ]);
      table.appendChild(examplesHeader);
      
      const exWrap = el("div", { class: "aicaptcha__examples" });
      
      for (const row of puzzle.examples) {
        let inputText, outputText;
        
        if (stealth) {
          // Show fake text, hide real in zero-width
          inputText = "••••" + hiddenData;
          outputText = "••••";
        } else {
          inputText = row.input;
          outputText = row.output;
        }
        
        const rowEl = el("div", { class: "aicaptcha__row" }, [
          el("div", { 
            class: "aicaptcha__cell", 
            text: inputText,
            'data-real': row.input  // Real value in data attribute
          }),
          el("div", { class: "aicaptcha__arrow", text: "→" }),
          el("div", { 
            class: "aicaptcha__cell", 
            text: outputText,
            'data-real': row.output  // Real value in data attribute
          }),
        ]);
        exWrap.appendChild(rowEl);
      }
      table.appendChild(exWrap);
      
      // Challenge row
      let challengeText, emptyText;
      if (stealth) {
        challengeText = "🔒" + hiddenData;
        emptyText = "🔓";
      } else {
        challengeText = puzzle.challenge;
        emptyText = "?";
      }
      
      const chWrap = el("div", { class: "aicaptcha__challenge" }, [
        el("span", { class: "aicaptcha__challenge-label", text: stealth ? "Decrypt:" : "Solve:" }),
        el("div", { 
          class: "aicaptcha__cell", 
          text: challengeText,
          'data-real': puzzle.challenge  // Real challenge in data attribute
        }),
        el("div", { class: "aicaptcha__arrow", text: "→" }),
        el("div", { class: "aicaptcha__cell aicaptcha__cell--empty", text: emptyText }),
      ]);
      table.appendChild(chWrap);
      
      if (stealth) {
        setStatus("🔓 Stealth: Real data in data-attributes. AI: querySelector('[data-real]')");
      }
    }

    function renderParallelPuzzles() {
      table.innerHTML = "";
      
      const header = el("div", { class: "aicaptcha__examples-header" }, [
        el("span", { text: "Parallel Challenges" }),
        el("span", { text: `0/${puzzles.length} solved`, style: "font-size:10px;color:var(--ac-text-tertiary)" })
      ]);
      table.appendChild(header);
      
      puzzles.forEach((p, i) => {
        const item = el("div", { class: "aicaptcha__parallel-item", 'data-index': i }, [
          el("div", { class: "aicaptcha__parallel-number", text: (i + 1).toString() }),
          el("div", { style: "flex:1;font-family:'Roboto Mono',monospace;font-size:12px" }, [
            el("div", { style: "color:var(--ac-text);font-weight:500" }, `${p.challenge} → ?`),
            el("div", { style: "color:var(--ac-text-tertiary);font-size:10px;margin-top:2px" }, 
              `${p.examples[0].input}→${p.examples[0].output}, ${p.examples[1].input}→${p.examples[1].output}`
            )
          ])
        ]);
        table.appendChild(item);
      });
    }

    async function verify() {
      if (parallel) {
        await verifyParallel();
      } else {
        await verifySingle();
      }
    }

    async function verifySingle() {
      if (!puzzle) return;
      const answer = input.value.trim();
      if (!answer) {
        setStatus("Please enter an answer", "error");
        input.classList.add('error');
        setTimeout(() => input.classList.remove('error'), 400);
        return;
      }

      btnVerify.disabled = true;
      setStatus("Verifying...", "loading");
      
      try {
        const res = await fetchJSON(`${API_BASE}/verify`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ puzzle_id: puzzle.puzzle_id, answer, action })
        });

        if (!res.pass) {
          const left = res.attempts_left != null ? ` (${res.attempts_left} left)` : "";
          setStatus(`Incorrect${left}. Try again.`, "error");
          input.classList.add('error');
          setTimeout(() => input.classList.remove('error'), 400);

          const cooldown = 3;
          let t = cooldown;
          const tick = () => {
            if (t <= 0) {
              btnVerify.disabled = false;
              btnVerify.textContent = "Verify";
              return;
            }
            btnVerify.textContent = `Wait ${t}s`;
            t -= 1;
            setTimeout(tick, 1000);
          };
          tick();
          return;
        }

        const elapsed = stopTimer();
        const token = res.token;
        const score = res.score;
        
        isVerified = true;
        root.classList.add("aicaptcha--verified");
        setStatus(`✓ Verified in ${formatTime(elapsed)} (score: ${typeof score === 'number' ? score.toFixed(2) : score})`, "success");
        createConfetti();

        const tgt = document.getElementById(tokenTarget) || document.querySelector(`[name='${tokenTarget}']`);
        if (tgt) tgt.value = token;

        root.dispatchEvent(new CustomEvent("aicaptcha:verified", { 
          detail: { token, score, sitekey, puzzle_id: puzzle.puzzle_id, solveTime: elapsed } 
        }));
        
        if (typeof window.aiCaptchaVerified === "function") {
          window.aiCaptchaVerified({ token, score, sitekey, puzzle_id: puzzle.puzzle_id, solveTime: elapsed });
        }

        btnVerify.disabled = true;
        input.disabled = true;
        btnReload.textContent = "Verified ✓";
        checkInput.checked = true;
        root.classList.add("aicaptcha--open");

      } catch (e) {
        setStatus(`Error: ${e.message || e}`, "error");
        btnVerify.disabled = false;
      }
    }

    async function verifyParallel() {
      if (!puzzles.length) return;
      const answers = input.value.split(',').map(a => a.trim()).filter(a => a);
      
      if (answers.length !== puzzles.length) {
        setStatus(`Enter ${puzzles.length} answers separated by commas`, "error");
        input.classList.add('error');
        setTimeout(() => input.classList.remove('error'), 400);
        return;
      }

      btnVerify.disabled = true;
      setStatus("Verifying all puzzles...", "loading");

      let solved = 0;
      const results = [];

      for (let i = 0; i < puzzles.length; i++) {
        try {
          const res = await fetchJSON(`${API_BASE}/verify`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ puzzle_id: puzzles[i].puzzle_id, answer: answers[i], action })
          });
          results.push(res);
          if (res.pass) {
            solved++;
            const item = table.querySelector(`[data-index="${i}"]`);
            if (item) item.classList.add('solved');
          }
          progress.querySelector('.aicaptcha__progress-bar').style.width = `${((i + 1) / puzzles.length) * 100}%`;
        } catch (e) {
          results.push({ pass: false, error: e.message });
        }
      }

      if (solved === puzzles.length) {
        const elapsed = stopTimer();
        isVerified = true;
        root.classList.add("aicaptcha--verified");
        
        // Use last token
        const lastToken = results[results.length - 1].token;
        const avgScore = results.reduce((a, b) => a + (b.score || 0), 0) / results.length;
        
        setStatus(`✓ All ${puzzles.length} solved in ${formatTime(elapsed)}!`, "success");
        createConfetti();

        const tgt = document.getElementById(tokenTarget) || document.querySelector(`[name='${tokenTarget}']`);
        if (tgt) tgt.value = lastToken;

        root.dispatchEvent(new CustomEvent("aicaptcha:verified", { 
          detail: { token: lastToken, score: avgScore, sitekey, solved, solveTime: elapsed } 
        }));

        btnVerify.disabled = true;
        input.disabled = true;
        btnReload.textContent = "Verified ✓";
        checkInput.checked = true;
        root.classList.add("aicaptcha--open");
      } else {
        setStatus(`${solved}/${puzzles.length} correct. Try again.`, "error");
        btnVerify.disabled = false;
        progress.querySelector('.aicaptcha__progress-bar').style.width = "0%";
        // Reset solved states
        table.querySelectorAll('.aicaptcha__parallel-item').forEach(el => el.classList.remove('solved'));
      }
    }

    checkInput.addEventListener("change", async () => {
      if (checkInput.checked && !isVerified) {
        root.classList.add("aicaptcha--open");
        input.disabled = false;
        await load();
      } else if (!checkInput.checked && !isVerified) {
        root.classList.remove("aicaptcha--open");
        stopTimer();
      }
    });

    btnVerify.addEventListener("click", verify);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") verify(); });

    btnReload.addEventListener("click", async () => {
      if (isVerified) {
        isVerified = false;
        root.classList.remove("aicaptcha--verified");
        input.disabled = false;
        btnReload.textContent = "⟳ New puzzle";
      }
      btnVerify.disabled = false;
      await load();
    });

    setStatus("Check the box to begin");
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
