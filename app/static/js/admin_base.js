/* extracted from admin/base.html */
(function(){
      const toast = document.getElementById('adminToast');
      const icon = document.getElementById('adminToastIcon');
      const title = document.getElementById('adminToastTitle');
      const msg = document.getElementById('adminToastMsg');
      let t = null;

      function showToast(type, message, ttl){
        if(!toast) return;
        toast.classList.remove('success','warning','error');
        toast.classList.add(type || 'success');
        icon.textContent = (type === 'error') ? '⛔' : ((type === 'warning') ? '⚠️' : '✅');
        title.textContent = ttl || (type === 'error' ? 'Error' : (type === 'warning' ? 'Atención' : 'Éxito'));
        msg.textContent = message || 'Acción realizada.';
        toast.style.display = 'flex';
        clearTimeout(t);
        t = setTimeout(()=>{ toast.style.display='none'; }, 2800);
      }
      window.__adminToast = showToast;

      // Interceptar acciones de calificaciones (cerrar/reabrir/anular) sin navegar a JSON
      document.addEventListener('submit', async (ev)=>{
        const form = ev.target;
        if(!(form instanceof HTMLFormElement)) return;
        if(!form.classList.contains('js-rating-action')) return;

        ev.preventDefault();
        const successMsg = form.dataset.success || 'Acción realizada.';
        const successTitle = form.dataset.successTitle || 'Éxito';

        try{
          const res = await fetch(form.action, { method: 'POST', body: new FormData(form) });
          if(!res.ok){
            const txt = await res.text();
            showToast('error', (txt || 'No se pudo completar la acción.').slice(0,180), '⛔ Error');
            return;
          }
          showToast('success', successMsg, '✅ ' + successTitle);
          setTimeout(()=>window.location.reload(), 700);
        }catch(e){
          showToast('error', 'Error de conexión. Verifica el servidor.', '⛔ Conexión');
        }
      });
    })();
