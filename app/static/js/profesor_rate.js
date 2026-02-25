/* extracted from profesor/rate.html */
(function(){
    const alreadyDone = document.body.dataset.alreadyDone === 'true';

    const $ = (id) => document.getElementById(id);
    const inputs = {
      cognitiva: $('in_cognitiva'),
      aptitudinal: $('in_aptitudinal'),
      actitudinal: $('in_actitudinal'),
      evaluacion: $('in_evaluacion'),
      cpc: $('in_cpc'),
      fallas: $('in_fallas')
    };

    const sumNota = $('sumNota');
    const sumPill = $('sumPill');
    const sumRegla = $('sumRegla');

    function toNum(el){
      if (!el) return null;
      const v = (el.value ?? '').toString().trim();
      if (v === '') return null;
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    }

    function fmt(n){
      return (Math.round(n * 100) / 100).toFixed(2);
    }

    function setPill(text, kind){
      const cls = kind === 'ok' ? 'ok' : (kind === 'bad' ? 'bad' : 'na');
      sumPill.innerHTML = `<span class="badge ${cls}">${text}</span>`;
    }

    function recalc(){
      const fields = [
        {key:'cognitiva', label:'Área cognitiva', el: inputs.cognitiva},
        {key:'aptitudinal', label:'Área aptitudinal', el: inputs.aptitudinal},
        {key:'actitudinal', label:'Área actitudinal', el: inputs.actitudinal},
        {key:'evaluacion', label:'Evaluación', el: inputs.evaluacion},
        {key:'cpc', label:'Participación CPC', el: inputs.cpc},
      ];

      const missing = [];
      const invalid = [];
      const nums = [];

      fields.forEach(f => {
        const n = toNum(f.el);
        // limpiar estados visuales
        if (f.el) {
          f.el.classList.remove('is-missing');
          f.el.classList.remove('is-invalid');
        }

        if (n === null){
          missing.push(f.label);
          if (f.el) f.el.classList.add('is-missing');
          return;
        }
        if (n < 0 || n > 5){
          invalid.push(`${f.label} (0–5)`);
          if (f.el) f.el.classList.add('is-invalid');
          return;
        }
        nums.push(n);
      });

      const fallas = toNum(inputs.fallas);
      if (inputs.fallas){
        inputs.fallas.classList.remove('is-invalid');
      }
      let fallasNum = 0;
      if (fallas === null){
        fallasNum = 0;
      } else if (fallas < 0 || fallas > 100){
        fallasNum = fallas;
        if (inputs.fallas) inputs.fallas.classList.add('is-invalid');
        invalid.push('% fallas (0–100)');
      } else {
        fallasNum = fallas;
      }

      const regla = (Number.isFinite(fallasNum) ? fallasNum : 0) > 10;

      const btn = $('btnGuardar');

      // Mostrar pendientes / errores
      const faltanEl = $('sumFaltan');
      if (faltanEl){
        if (missing.length === 0 && invalid.length === 0){
          faltanEl.textContent = '—';
        } else {
          const parts = [];
          if (missing.length) parts.push('Faltan: ' + missing.join(', '));
          if (invalid.length) parts.push('Revisar: ' + invalid.join(', '));
          faltanEl.textContent = parts.join(' · ');
        }
      }

      // Si no hay ningún número válido todavía
      if (nums.length === 0){
        sumNota.textContent = '—';
        sumRegla.textContent = '—';
        setPill('Sin calcular', 'na');
        if (btn) btn.disabled = true;
        return;
      }

      const avg = nums.reduce((a,b)=>a+b,0) / nums.length;

      // Nota provisional / final según regla
      const provisional = regla ? 0 : avg;

      // Regla de fallas (siempre se informa cuando hay dato de fallas o cuando aplica)
      if (regla){
        sumRegla.textContent = `Fallas ${fmt(fallasNum)}% (>10%): la nota se fija en 0.00`;
      } else {
        sumRegla.textContent = `Fallas ${fmt(fallasNum)}% (<=10%): cálculo normal`;
      }

      const complete = (missing.length === 0 && invalid.length === 0);

      if (complete){
        sumNota.textContent = fmt(provisional);
        setPill('Lista para guardar', regla ? 'bad' : 'ok');
        if (btn) btn.disabled = false;
      } else {
        sumNota.textContent = fmt(provisional);
        setPill('Promedio parcial', 'na');
        if (btn) btn.disabled = true;
      }
    }

    Object.values(inputs).forEach(el => {
      if (!el) return;
      el.addEventListener('input', recalc);
      el.addEventListener('change', recalc);
    });

    recalc();
  })();

(function () {
      const toast = document.getElementById("toast");
      const toastMsg = document.getElementById("toast_msg");
      const toastIcon = document.getElementById("toast_icon");
      const toastClose = document.getElementById("toast_close");
      let t;

      const ICONS = {
        success: "✅",
        warning: "⚠️",
        error: "⛔"
      };

      function showToast(message, type = "warning") {
        if (!toast || !toastMsg) return;
        toastMsg.textContent = message;
        toast.dataset.type = type;
        if (toastIcon) toastIcon.textContent = ICONS[type] || "⚠️";
        toast.classList.add("show");
        clearTimeout(t);
        t = setTimeout(() => toast.classList.remove("show"), 2800);
      }

      toastClose?.addEventListener("click", () => {
        toast.classList.remove("show");
        clearTimeout(t);
      });

      function getMinMax(inp) {
        const maxAttr = inp.getAttribute("max");
        const minAttr = inp.getAttribute("min");
        const max = maxAttr !== null ? Number(maxAttr) : null;
        const min = minAttr !== null ? Number(minAttr) : null;
        return { min, max };
      }

      // Very strict: block characters that would make the value invalid or out of range.
      function setupStrictNumberInput(inp) {
        // Track last valid value (for IME / edge cases)
        inp.dataset.lastValid = inp.value ?? "";

        inp.addEventListener("focus", () => {
          inp.dataset.lastValid = inp.value ?? "";
        });

        // Prevent wheel from bumping values silently
        inp.addEventListener("wheel", (e) => {
          inp.blur();
        }, { passive: true });

        const numericPattern = /^\d*(?:\.\d*)?$/; // only digits and one dot

        inp.addEventListener("beforeinput", (e) => {
          // Allow deletions / undo / navigation
          const it = e.inputType || "";
          if (it.startsWith("delete") || it === "historyUndo" || it === "historyRedo") return;

          // Some browsers may not provide selection info for certain inputTypes
          const start = inp.selectionStart ?? (inp.value?.length ?? 0);
          const end = inp.selectionEnd ?? (inp.value?.length ?? 0);

          const data = (e.data ?? "");
          const cur = (inp.value ?? "").toString();

          // Build next value as if the input happened
          const next = cur.slice(0, start) + data + cur.slice(end);

          // Allow empty while editing
          if (next === "") return;

          // Block anything non-numeric format (letters, multiple dots, etc.)
          if (!numericPattern.test(next)) {
            e.preventDefault();
            showToast("Solo se permiten números (0 a 5).", "warning");
            return;
          }

          const v = Number(next);
          if (Number.isNaN(v)) return;

          const { min, max } = getMinMax(inp);

          if (max !== null && Number.isFinite(max) && v > max) {
            e.preventDefault();
            showToast(max === 5 ? "La calificación es solo hasta 5." : ("Máximo permitido: " + max + "."), "warning");
            return;
          }
          if (min !== null && Number.isFinite(min) && v < min) {
            e.preventDefault();
            showToast("Mínimo permitido: " + min + ".", "warning");
            return;
          }
        });

        // Block paste if it would exceed range or be invalid
        inp.addEventListener("paste", (e) => {
          const pasted = (e.clipboardData?.getData("text") ?? "").trim();
          if (!pasted) return;

          const start = inp.selectionStart ?? (inp.value?.length ?? 0);
          const end = inp.selectionEnd ?? (inp.value?.length ?? 0);
          const cur = (inp.value ?? "").toString();
          const next = cur.slice(0, start) + pasted + cur.slice(end);

          const numericPattern = /^\d*(?:\.\d*)?$/;
          if (next !== "" && !numericPattern.test(next)) {
            e.preventDefault();
            showToast("Pegado inválido. Solo números (0 a 5).", "warning");
            return;
          }

          const v = Number(next);
          if (Number.isNaN(v)) return;

          const { min, max } = getMinMax(inp);
          if (max !== null && Number.isFinite(max) && v > max) {
            e.preventDefault();
            showToast(max === 5 ? "La calificación es solo hasta 5." : ("Máximo permitido: " + max + "."), "warning");
            return;
          }
          if (min !== null && Number.isFinite(min) && v < min) {
            e.preventDefault();
            showToast("Mínimo permitido: " + min + ".", "warning");
            return;
          }
        });

        // Fallback clamp (for browsers that skip beforeinput in some cases)
        inp.addEventListener("input", () => {
          const raw = (inp.value ?? "").toString().trim();
          if (raw === "") {
            inp.dataset.lastValid = "";
            return;
          }

          // normalize comma to dot
          const norm = raw.replace(",", ".");
          if (norm !== raw) inp.value = norm;

          const v = Number(inp.value);
          if (Number.isNaN(v)) {
            inp.value = inp.dataset.lastValid ?? "";
            showToast("Valor inválido. Usa números (0 a 5).", "warning");
            return;
          }

          const { min, max } = getMinMax(inp);

          if (max !== null && Number.isFinite(max) && v > max) {
            inp.value = String(max);
            inp.dataset.lastValid = String(max);
            showToast(max === 5 ? "La calificación es solo hasta 5." : ("Máximo permitido: " + max + "."), "warning");
            return;
          }
          if (min !== null && Number.isFinite(min) && v < min) {
            inp.value = String(min);
            inp.dataset.lastValid = String(min);
            showToast("Mínimo permitido: " + min + ".", "warning");
            return;
          }

          inp.dataset.lastValid = inp.value;
        });
      }

      // Apply strict behavior to all numeric inputs
      const numericInputs = Array.from(document.querySelectorAll('input[type="number"]'));
      numericInputs.forEach(setupStrictNumberInput);

      // Extra: if server returned an error message, show it as toast too.
      const serverError = document.querySelector('[data-server-error]');
      if (serverError) {
        showToast(serverError.getAttribute('data-server-error') || "Revisa los campos del formulario.", "error");
      }
    })();
