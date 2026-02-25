// app/static/app.js

const form = document.getElementById('rateForm');

if (form) {
  // Nota: algunos despliegues/plantillas antiguas pueden no tener sidebar con estos IDs.
  // Por eso, todo acceso a estos nodos debe ser "null-safe" para evitar que el JS se rompa
  // (si se rompe, no habrá llamadas XHR y parecerá que "no hay conexión").
  const notaDefEl = document.getElementById('notaDef');
  const reglaEl = document.getElementById('reglaFallas');
  const msgEl = document.getElementById('msg');
  const btnLimpiar = document.getElementById('btnLimpiar');
  const btnSubmit = document.getElementById('btnSubmit');

  const rotSel = document.getElementById('rotSelect');
  const mesSel = document.getElementById('mesSelect');

  // Nueva calificación (limpiar formulario para una nueva calificación)
  function resetForNextRating(opts = {}) {
    const { keepMesRot = true, keepMessage = false } = opts;

    const rotValue = (keepMesRot && rotSel) ? rotSel.value : null;
    const mesValue = (keepMesRot && mesSel) ? mesSel.value : null;

    form.reset();

    // Limpiar campos autocompletados
    if (inpEstNombre) inpEstNombre.value = "";
    if (inpUniversidad) inpUniversidad.value = "";
    if (inpSemestre) inpSemestre.value = "";
    if (inpEstDoc) inpEstDoc.value = "";
    try { clearTeachers(); } catch (_) {}

    // Reset estados/alertas
    showDuplicate(false);
    showStudentNotFound(false);
    isDuplicate = false;
    lastCheckKey = "";
    lastLookupDoc = "";

    // Restaurar mes/rotación si se desea (acelera la operación)
    if (rotSel && rotValue !== null) rotSel.value = rotValue;
    if (mesSel && mesValue !== null) mesSel.value = mesValue;

    // Por defecto, porcentaje fallas = 0
    const fallasEl = form.querySelector('[name="porcentaje_fallas"]');
    if (fallasEl) fallasEl.value = "0";

    // Al quedar en blanco, bloquear submit hasta validar un estudiante existente
    studentIsValid = false;
    if (btnSubmit) {
      btnSubmit.disabled = true;
      btnSubmit.style.opacity = '0.6';
      btnSubmit.style.cursor = 'not-allowed';
    }

    if (!keepMessage && msgEl) msgEl.textContent = "";

    calcPreview();
    syncSidebarIdentity();
    checkDuplicate();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  if (btnLimpiar) {
    btnLimpiar.addEventListener('click', () => {
      resetForNextRating({ keepMesRot: true, keepMessage: false });
    });
  }


  // Sidebar extras
  const pillEstado = document.getElementById('pillEstado');
  const sbEstudiante = document.getElementById('sbEstudiante');
  const sbDocumento = document.getElementById('sbDocumento');

  const inpEstNombre = document.getElementById('estudianteNombre');
  const inpEstDoc = document.getElementById('estudianteDocumento');
  const inpUniversidad = document.getElementById('universidad') || form.querySelector('[name="universidad"]');
  const inpSemestre = document.getElementById('semestre') || form.querySelector('[name="semestre"]');
  // --- Docentes asignados (por estudiante + rotación) ---
  const teacherSel = document.getElementById('teacherSel');
  const teacherHint = document.getElementById('teacherHint');
  const inpEspNombre = document.getElementById('especialistaNombre') || form.querySelector('[name="especialista_nombre"]');
  const inpEspDoc = document.getElementById('especialistaDocumento') || form.querySelector('[name="especialista_documento"]');
  let teachersLoadedForKey = "";

  function clearTeachers(msg = '') {
    if (teacherSel) {
      teacherSel.innerHTML = '<option value="">— Seleccione un docente —</option>';
      teacherSel.value = '';
    }
    if (inpEspNombre) inpEspNombre.value = '';
    if (inpEspDoc) inpEspDoc.value = '';
    teachersLoadedForKey = '';
    if (teacherHint && msg) teacherHint.textContent = msg;
  }

  async function loadAssignedTeachers() {
    if (!teacherSel || !inpEstDoc || !rotSel) return;
    const documento = (inpEstDoc.value || '').trim();
    const rotation_id = parseInt(rotSel.value || '0', 10);
    if (!documento || documento.length < 3 || rotation_id < 1) {
      clearTeachers('Seleccione estudiante y rotación para ver docentes asignados.');
      return;
    }
    if (!studentIsValid) {
      clearTeachers('El estudiante debe existir/estar activo (ADMIN) para cargar docentes.');
      return;
    }
    const key = `${documento}|${rotation_id}`;
    if (key === teachersLoadedForKey) return;
    teachersLoadedForKey = key;

    try {
      const qs = new URLSearchParams({ estudiante_documento: documento, rotation_id: String(rotation_id) });
      const res = await fetch(`/api/teachers/assigned?${qs.toString()}`);
      if (!res.ok) {
        clearTeachers('No fue posible cargar docentes asignados.');
        return;
      }
      const data = await res.json();
      const items = Array.isArray(data?.items) ? data.items : [];
      teacherSel.innerHTML = '<option value="">— Seleccione un docente —</option>' + items.map(t => {
        const nombre = String(t.nombre || '').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        const doc = String(t.documento || '').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        const esp = String(t.especialidad || '').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        const label = esp ? `${nombre} · ${esp}` : nombre;
        return `<option value="${doc}" data-nombre="${nombre}">${label}</option>`;
      }).join('');

      if (items.length === 0) {
        clearTeachers('⚠️ No hay docentes asignados para este estudiante en esta rotación. Asigne en ADMIN → Profesores.');
        // bloquear submit
        if (btnSubmit) { btnSubmit.disabled = true; btnSubmit.style.opacity='0.6'; btnSubmit.style.cursor='not-allowed'; }
        return;
      }

      if (teacherHint) teacherHint.textContent = `Docentes asignados: ${items.length}. Seleccione el evaluador.`;
    } catch (e) {
      clearTeachers('No fue posible cargar docentes asignados.');
    }
  }

  // --- Autocomplete estudiante ---
  let lastLookupDoc = "";
  let lookupAbort = null;
  const studentsDatalist = document.getElementById('studentsDatalist');

  let lastSuggestQ = "";
  let suggestAbort = null;

  let studentIsValid = false; // existe en ADMIN (tabla students)
  const studentNotFoundBox = document.getElementById('studentNotFoundBox');

  // Por seguridad: al cargar, no permitir enviar hasta validar un estudiante existente.
  if (btnSubmit) {
    btnSubmit.disabled = true;
    btnSubmit.style.opacity = '0.6';
    btnSubmit.style.cursor = 'not-allowed';
  }

  function showStudentNotFound(show) {
    studentIsValid = !show;
    if (show) { try { clearTeachers('Seleccione un estudiante válido para cargar docentes.'); } catch (_) {} }
    if (studentNotFoundBox) studentNotFoundBox.style.display = show ? 'block' : 'none';

    // Si no existe, bloquear envío
    if (btnSubmit) {
      btnSubmit.disabled = show || isDuplicate;
      btnSubmit.style.opacity = (show || isDuplicate) ? '0.6' : '1';
      btnSubmit.style.cursor = (show || isDuplicate) ? 'not-allowed' : 'pointer';
    }
  }

  async function refreshStudentSuggestions(forceAll = false) {
    if (!studentsDatalist || !inpEstDoc) return;

    const q = (inpEstDoc.value || '').trim();
    // Si está vacío, opcionalmente traer un listado corto (para que el usuario vea que sí hay conexión)
    if (!q && !forceAll) {
      studentsDatalist.innerHTML = "";
      return;
    }

    // evitar spam
    if (q === lastSuggestQ) return;
    lastSuggestQ = q;

    try { if (suggestAbort) suggestAbort.abort(); } catch (_) {}
    suggestAbort = new AbortController();

    try {
      const qs = new URLSearchParams({ q, limit: forceAll && !q ? '50' : '20' });
      const res = await fetch(`/api/students/search?${qs.toString()}`, { signal: suggestAbort.signal });
      if (!res.ok) return;
      const data = await res.json();
      const items = Array.isArray(data?.items) ? data.items : [];

      // llenar datalist: value=cedula, texto=nombre/universidad
      studentsDatalist.innerHTML = items
        .map(s => {
          const doc = String(s.documento || '').trim();
          const label = [s.nombre, s.universidad, s.semestre].filter(Boolean).join(' · ');
          const safeLabel = String(label).replace(/</g, '&lt;').replace(/>/g, '&gt;');
          const safeDoc = doc.replace(/</g, '&lt;').replace(/>/g, '&gt;');
          return `<option value="${safeDoc}">${safeLabel}</option>`;
        })
        .join('');
    } catch (e) {
      // ignorar
    }
  }

  async function lookupStudent(force = false) {
    const documento = (inpEstDoc?.value || "").trim();
    if (!documento || documento.length < 3) return;

    // Evitar llamadas repetidas (pero permitir reintentos si force=true)
    if (!force && documento === lastLookupDoc) return;

    // Cancelar request anterior (si aplica)
    try { if (lookupAbort) lookupAbort.abort(); } catch (_) {}
    lookupAbort = new AbortController();

    try {
      const qs = new URLSearchParams({ documento });
      const res = await fetch(`/api/students/lookup?${qs.toString()}`, { signal: lookupAbort.signal });
      if (!res.ok) {
        // Si falla, permitir reintentar
        lastLookupDoc = "";
        return;
      }

      const data = await res.json();
      if (!data) {
        lastLookupDoc = "";
        return;
      }

      // ✅ Solo marcamos el documento como "consultado" cuando la respuesta fue OK
      lastLookupDoc = documento;

      // ✅ Reglas de negocio: el estudiante debe existir en ADMIN (tabla students)
      if (!data.found_student) {
        // Limpiar campos autocompletados (si estaban)
        if (inpEstNombre) inpEstNombre.value = "";
        if (inpUniversidad) inpUniversidad.value = "";
        if (inpSemestre) inpSemestre.value = "";
        syncSidebarIdentity();
        showStudentNotFound(true);
        return;
      }

      showStudentNotFound(false);

      if (inpEstNombre && data.nombre) inpEstNombre.value = data.nombre;
      if (inpUniversidad && data.universidad) inpUniversidad.value = data.universidad;
      if (inpSemestre && data.semestre) inpSemestre.value = data.semestre;

      // Mes
      if (mesSel && data.mes) {
        const opt = Array.from(mesSel.options || []).find(o => (o.value || '').trim() === String(data.mes).trim());
        if (opt) mesSel.value = opt.value;
      }

      // Rotación
      if (rotSel && data.rotation_id) {
        const rid = String(data.rotation_id);
        const opt = Array.from(rotSel.options || []).find(o => String(o.value) === rid);
        if (opt) rotSel.value = opt.value;
      }

      // ✅ Cargar docentes asignados (depende de estudiante + rotación)
      try { await loadAssignedTeachers(); } catch (_) {}

      // Si solo hay 1 docente asignado, seleccionarlo automáticamente
      if (teacherSel && teacherSel.options && teacherSel.options.length === 2) {
        teacherSel.selectedIndex = 1;
        teacherSel.dispatchEvent(new Event('change'));
      }

      // Refrescar resumen + revalidar duplicado con los nuevos valores
      syncSidebarIdentity();
      calcPreview();
      checkDuplicate();
    } catch (e) {
      // Ignorar abort y errores de red, pero permitir reintento
      lastLookupDoc = "";
    }
  }

  // Duplicado UI
  const duplicateBox = document.getElementById('duplicateBox');
  const duplicateMeta = document.getElementById('duplicateMeta');

  let isDuplicate = false;
  let lastCheckKey = "";

  function getNumber(name) {
    const el = form.querySelector(`[name="${name}"]`);
    if (!el) return NaN;
    const v = parseFloat(el.value);
    return Number.isFinite(v) ? v : NaN;
  }

  function clamp(n, min, max) {
    if (!Number.isFinite(n)) return n;
    return Math.min(max, Math.max(min, n));
  }

  function setPill(text, kind) {
    if (!pillEstado) return;
    pillEstado.textContent = text;
    pillEstado.classList.remove('ok', 'bad');
    if (kind === 'ok') pillEstado.classList.add('ok');
    if (kind === 'bad') pillEstado.classList.add('bad');
  }

  function syncSidebarIdentity() {
    if (sbEstudiante && inpEstNombre) {
      sbEstudiante.textContent = (inpEstNombre.value || '—').trim() || '—';
    }
    if (sbDocumento && inpEstDoc) {
      const d = (inpEstDoc.value || '').trim();
      sbDocumento.textContent = d ? `Doc: ${d}` : '—';
    }
  }

  function showDuplicate(exists, metaText = "") {
    isDuplicate = !!exists;

    if (duplicateBox) {
      duplicateBox.style.display = exists ? "block" : "none";
    }
    if (duplicateMeta) {
      duplicateMeta.textContent = metaText ? ` · ${metaText}` : "";
    }

    // Bloquear envío si existe duplicado o si el estudiante no es válido
    if (btnSubmit) {
      const blocked = exists || !studentIsValid;
      btnSubmit.disabled = blocked;
      btnSubmit.style.opacity = blocked ? "0.6" : "1";
      btnSubmit.style.cursor = blocked ? "not-allowed" : "pointer";
    }

    if (exists) {
      msgEl.textContent = "⚠️ Este interno ya fue calificado por ESTE profesor para esta rotación y mes. Si requiere cambios, diríjase con el Administrador.";
      setPill("Bloqueado", "bad");
    }
  }

  async function checkDuplicate() {
    const documento = (inpEstDoc?.value || "").trim();
    const mes = (mesSel?.value || "").trim();
    const rotation_id = parseInt(rotSel?.value || "0", 10);
    const especialista_documento = (form.querySelector('[name="especialista_documento"]')?.value || "").trim();

    // Condición mínima para consultar
    if (!documento || documento.length < 3 || !mes || rotation_id < 1 || !especialista_documento) {
      showDuplicate(false);
      isDuplicate = false;
      return;
    }

    const key = `${documento}|${rotation_id}|${mes}|${especialista_documento}`;
    if (key === lastCheckKey) return; // evita llamadas repetidas
    lastCheckKey = key;

    try {
      const qs = new URLSearchParams({ documento, rotation_id: String(rotation_id), mes, especialista_documento });
      const res = await fetch(`/api/ratings/check?${qs.toString()}`);
      if (!res.ok) {
        // Si falla el check, no bloqueamos, pero no mostramos alerta
        showDuplicate(false);
        return;
      }
      const data = await res.json();

      if (data.exists) {
        const meta = data.created_at ? `Registro ID ${data.id} · ${data.created_at} · ${data.estado}` : `Registro ID ${data.id}`;
        showDuplicate(true, meta);
      } else {
        showDuplicate(false);
        isDuplicate = false;
        // Si estaba bloqueado antes, volver a pill normal
        calcPreview();
      }
    } catch (e) {
      showDuplicate(false);
    }
  }

  function calcPreview() {
    const fallas = clamp(getNumber('porcentaje_fallas'), 0, 100);

    const vals = ['cognitiva', 'aptitudinal', 'actitudinal', 'evaluacion', 'cpc']
      .map(getNumber)
      .map(v => clamp(v, 0, 5));

    if (vals.some(v => !Number.isFinite(v)) || !Number.isFinite(fallas)) {
      if (notaDefEl) notaDefEl.textContent = '—';
      if (reglaEl) reglaEl.textContent = '—';
      if (!isDuplicate) setPill('Sin calcular', '');
      return;
    }

    if (fallas > 10) {
      if (notaDefEl) notaDefEl.textContent = '0.00';
      if (reglaEl) reglaEl.textContent = 'Pierde por fallas (>10%)';
      if (!isDuplicate) setPill('Pierde', 'bad');
      return;
    }

    const suma = vals.reduce((a, b) => a + b, 0);
    const nota = Math.round((suma * 0.2) * 100) / 100;

    if (notaDefEl) notaDefEl.textContent = nota.toFixed(2);
    if (reglaEl) reglaEl.textContent = 'OK (≤10%)';

    if (!isDuplicate) {
      if (nota >= 4.0) setPill('Excelente', 'ok');
      else if (nota >= 3.0) setPill('Aprobado', 'ok');
      else setPill('Bajo', 'bad');
    }
  }

  // --- Eventos ---
  form.addEventListener('input', () => {
    calcPreview();
    syncSidebarIdentity();
  });
  form.addEventListener('change', () => {
    calcPreview();
    syncSidebarIdentity();
    // cambios de mes/rotación deben revalidar duplicado
    checkDuplicate();
  });

  // Validar duplicado y autocompletar al escribir documento
  if (inpEstDoc) {
    inpEstDoc.addEventListener('blur', () => {
      lookupStudent(true);
    });
    // "input" cubre escribir, pegar, autocompletar del navegador, móviles, etc.
    inpEstDoc.addEventListener('input', () => {
      // Si el usuario borra el documento, volver a bloquear el envío sin mostrar alerta
      const v = (inpEstDoc.value || '').trim();
      if (v.length < 3) {
        studentIsValid = false;
        if (btnSubmit) {
          btnSubmit.disabled = true;
          btnSubmit.style.opacity = '0.6';
          btnSubmit.style.cursor = 'not-allowed';
        }
        if (studentNotFoundBox) studentNotFoundBox.style.display = 'none';
      }
      // sugerencias (estudiantes creados en ADMIN)
      window.clearTimeout(window.__stSuggestTimer);
      window.__stSuggestTimer = window.setTimeout(() => {
        refreshStudentSuggestions();
      }, 180);

      // si se escribe rápido, esperar un poco
      window.clearTimeout(window.__dupTimer);
      window.__dupTimer = window.setTimeout(() => {
        lookupStudent(false);
        checkDuplicate();
      }, 350);
    });
    // al enfocar, cargar algunas sugerencias
    inpEstDoc.addEventListener('focus', () => {
      // traer un listado corto incluso si el input está vacío
      refreshStudentSuggestions(true);
    });
  }

  // Botón opcional (🔎) para forzar búsqueda/autocompletado (útil si el navegador no dispara eventos)
  const btnBuscarEst = document.getElementById('btnBuscarEst');
  if (btnBuscarEst && inpEstDoc) {
    btnBuscarEst.addEventListener('click', () => {
      lookupStudent(true);
      checkDuplicate();
      refreshStudentSuggestions(true);
      inpEstDoc.focus();
    });
  }

  // ===== Modal: Lista de estudiantes (solo lectura) + indicador calificado (mes/rotación actual) =====
  const btnOpenStudents   = document.getElementById('btnOpenStudents');
  const studentsModal     = document.getElementById('studentsModal');
  const btnCloseStudents  = document.getElementById('btnCloseStudents');
  const btnCloseStudents2 = document.getElementById('btnCloseStudents2');
  const studentsSearch    = document.getElementById('studentsSearch');
  const btnReloadStudents = document.getElementById('btnReloadStudents');
  const studentsTbody     = document.getElementById('studentsTbody');
  const studentsCount     = document.getElementById('studentsCount');

  function openStudentsModal() {
    if (!studentsModal) return;
    studentsModal.style.display = 'flex';
    // Al abrir, cargamos con el mes/rotación actuales
    loadStudents('');
    window.setTimeout(() => studentsSearch?.focus(), 0);
  }

  function closeStudentsModal() {
    if (!studentsModal) return;
    studentsModal.style.display = 'none';
  }

  function badgeHtml(calificado) {
    if (calificado === true) return '<span class="badge ok">● Sí</span>';
    if (calificado === false) return '<span class="badge no">● No</span>';
    return '<span class="badge na">—</span>';
  }

  async function loadStudents(q) {
    if (!studentsTbody) return;

    const mes = (mesSel?.value || '').trim();
    const rotation_id = parseInt(rotSel?.value || '0', 10);

    studentsTbody.innerHTML = '<tr><td colspan="6" class="muted">Cargando...</td></tr>';
    try {
      const qs = new URLSearchParams({
        q: (q || '').trim(),
        limit: '300',
      });
      // Si hay mes/rotación, pedir que el backend calcule "calificado"
      if (mes && rotation_id > 0) {
        qs.set('mes', mes);
        qs.set('rotacion', String(rotation_id));
      }

      const res = await fetch(`/api/students/search?${qs.toString()}`);
      if (!res.ok) {
        studentsTbody.innerHTML = '<tr><td colspan="6" class="muted">No se pudo cargar.</td></tr>';
        return;
      }

      const data = await res.json();
      const items = Array.isArray(data?.items) ? data.items : [];
      if (studentsCount) studentsCount.textContent = `Mostrados: ${items.length}`;

      if (items.length === 0) {
        studentsTbody.innerHTML = '<tr><td colspan="6" class="muted">Sin resultados.</td></tr>';
        return;
      }

      studentsTbody.innerHTML = items.map(s => {
        const estado = s.activa ? '<span class="badge ok">ACTIVO</span>' : '<span class="badge no">INACTIVO</span>';
        return `
          <tr data-doc="${String(s.documento || '').replace(/"/g,'')}">
            <td><b>${s.documento || ''}</b></td>
            <td>${s.nombre || ''}</td>
            <td>${s.universidad || ''}</td>
            <td>${s.semestre || ''}</td>
            <td>${estado}</td>
            <td>${badgeHtml(s.calificado)}</td>
          </tr>
        `;
      }).join('');

      // Click en fila => seleccionar estudiante y autocompletar
      studentsTbody.querySelectorAll('tr[data-doc]').forEach(tr => {
        tr.addEventListener('click', async () => {
          const doc = (tr.getAttribute('data-doc') || '').trim();
          if (inpEstDoc) inpEstDoc.value = doc;
          closeStudentsModal();
          await lookupStudent(true);
          await checkDuplicate();
          inpEstDoc?.focus();
        });
      });
    } catch (e) {
      studentsTbody.innerHTML = '<tr><td colspan="6" class="muted">Error cargando estudiantes.</td></tr>';
    }
  }

  btnOpenStudents?.addEventListener('click', openStudentsModal);
  btnCloseStudents?.addEventListener('click', closeStudentsModal);
  btnCloseStudents2?.addEventListener('click', closeStudentsModal);

  studentsModal?.addEventListener('click', (e) => {
    if (e.target === studentsModal) closeStudentsModal();
  });

  btnReloadStudents?.addEventListener('click', () => loadStudents(studentsSearch?.value || ''));

  let modalSearchTimer = null;
  studentsSearch?.addEventListener('input', () => {
    window.clearTimeout(modalSearchTimer);
    modalSearchTimer = window.setTimeout(() => {
      loadStudents(studentsSearch.value);
    }, 180);
  });

  // Si cambian mes/rotación mientras el modal está abierto, recalcular columna "Calificado"
  function refreshModalIfOpen() {
    if (studentsModal && studentsModal.style.display === 'flex') {
      loadStudents(studentsSearch?.value || '');
    }
  }
  rotSel?.addEventListener('change', refreshModalIfOpen);
  mesSel?.addEventListener('change', refreshModalIfOpen);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && studentsModal?.style.display === 'flex') closeStudentsModal();
  });

  // también si cambian mes/rotación
  if (rotSel) rotSel.addEventListener('change', async () => {
    // al cambiar rotación, recargar docentes asignados
    try { clearTeachers('Cargando docentes asignados...'); } catch (_) {}
    try { await loadAssignedTeachers(); } catch (_) {}
    // auto-selección si solo hay 1
    if (teacherSel && teacherSel.options && teacherSel.options.length === 2) {
      teacherSel.selectedIndex = 1;
      teacherSel.dispatchEvent(new Event('change'));
    }
    checkDuplicate();
  });
  if (mesSel) mesSel.addEventListener('change', checkDuplicate);

  // Docente evaluador: llenar campos y validar duplicado
  if (teacherSel) {
    teacherSel.addEventListener('change', () => {
      const opt = teacherSel.options[teacherSel.selectedIndex];
      const doc = (teacherSel.value || '').trim();
      const nombre = (opt?.getAttribute('data-nombre') || '').trim();
      if (inpEspNombre) inpEspNombre.value = nombre;
      if (inpEspDoc) inpEspDoc.value = doc;
      // ✅ Revalidar duplicado cuando cambia el docente
      // ✅ Revalidar duplicado cuando cambia el docente
      checkDuplicate();
      // si no hay docente seleccionado, bloquear
      if (btnSubmit) {
        const blocked = !doc || isDuplicate || !studentIsValid;
        btnSubmit.disabled = blocked;
        btnSubmit.style.opacity = blocked ? '0.6' : '1';
        btnSubmit.style.cursor = blocked ? 'not-allowed' : 'pointer';
      }
    });
  }

  calcPreview();
  syncSidebarIdentity();
  checkDuplicate();
  // precargar sugerencias para mostrar conexión con el módulo ADMIN
  refreshStudentSuggestions(true);

  // Nueva calificación (deja el formulario listo para una nueva calificación)
  function clearForNext(keepMesRot = true, keepMessage = true) {
    const rotValue = (keepMesRot && rotSel) ? rotSel.value : null;
    const mesValue = (keepMesRot && mesSel) ? mesSel.value : null;
    const prevMsg = msgEl ? msgEl.textContent : '';

    form.reset();

    // Mantener mes/rotación si se solicita
    if (rotSel && rotValue !== null) rotSel.value = rotValue;
    if (mesSel && mesValue !== null) mesSel.value = mesValue;

    // Reglas por defecto
    const fallasEl = form.querySelector('[name="porcentaje_fallas"]');
    if (fallasEl) fallasEl.value = '0';

    // Limpiar identidad (estudiante) y estados
    lastCheckKey = '';
    lastLookupDoc = '';
    studentIsValid = false;
    isDuplicate = false;

    if (inpEstDoc) inpEstDoc.value = '';
    if (inpEstNombre) inpEstNombre.value = '';
    if (inpUniversidad) inpUniversidad.value = '';
    if (inpSemestre) inpSemestre.value = '';

    try { clearTeachers(); } catch (_) {}

    if (studentNotFoundBox) studentNotFoundBox.style.display = 'none';
    if (duplicateBox) duplicateBox.style.display = 'none';

    // Bloquear envío hasta que se seleccione un estudiante válido
    if (btnSubmit) {
      btnSubmit.disabled = true;
      btnSubmit.style.opacity = '0.6';
      btnSubmit.style.cursor = 'not-allowed';
    }

    // Mantener mensaje (por defecto) para que el usuario vea el OK
    if (msgEl) {
      msgEl.textContent = keepMessage ? prevMsg : '';
    }

    calcPreview();
    syncSidebarIdentity();
    checkDuplicate();

    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  if (btnLimpiar) {
    btnLimpiar.addEventListener('click', () => {
      // Para "Nueva calificación" mantenemos mes/rotación y limpiamos el mensaje
      clearForNext(true, false);
    });
  }

  // Submit
  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    // Si está duplicado, bloquear
    if (isDuplicate) {
      msgEl.textContent = "⚠️ Este interno ya fue calificado por ESTE profesor para esta rotación y mes. Si requiere cambios, diríjase con el Administrador.";
      return;
    }

    // Si el estudiante no existe en ADMIN, bloquear
    if (!studentIsValid) {
      msgEl.textContent = "⛔ Estudiante no registrado. Debe estar creado/activo en el módulo Administrador.";
      showStudentNotFound(true);
      return;
    }

    msgEl.textContent = 'Enviando...';

    const fd = new FormData(form);
    const payload = Object.fromEntries(fd.entries());

    payload.rotation_id = parseInt(payload.rotation_id, 10);

    payload.cognitiva = clamp(parseFloat(payload.cognitiva), 0, 5);
    payload.aptitudinal = clamp(parseFloat(payload.aptitudinal), 0, 5);
    payload.actitudinal = clamp(parseFloat(payload.actitudinal), 0, 5);
    payload.evaluacion = clamp(parseFloat(payload.evaluacion), 0, 5);
    payload.cpc = clamp(parseFloat(payload.cpc), 0, 5);
    payload.porcentaje_fallas = clamp(parseFloat(payload.porcentaje_fallas), 0, 100);

    try {
      const res = await fetch('/api/ratings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.status === 401) {
        msgEl.textContent = '🔒 Requiere autenticación (usuario/clave). Intenta de nuevo.';
        return;
      }

      // ✅ si backend detecta duplicado
      if (res.status === 409) {
        const t = await res.text();
        showDuplicate(true);
        msgEl.textContent = "⚠️ Este interno ya fue calificado por ESTE profesor para esta rotación y mes. Si requiere cambios, diríjase con el Administrador.";
        return;
      }

      if (!res.ok) {
        let errText = '';
        try { errText = await res.text(); } catch (_) {}
        throw new Error(errText || 'Error guardando');
      }

      const data = await res.json();
      msgEl.textContent =
        `✅ Guardado. ID: ${data.id} · Nota: ${Number(data.nota_definitiva).toFixed(2)} (${data.nota_en_letras}).`;
      setPill('Guardado', 'ok');

      // ✅ Modo pro: dejar el formulario listo para una nueva calificación
      // (se mantiene mes/rotación para agilizar, y se conserva el mensaje de OK)
      clearForNext(true, true);

    } catch (err) {
      msgEl.textContent = '❌ ' + (err?.message || 'Error');
      setPill('Error', 'bad');
    }
  });
}