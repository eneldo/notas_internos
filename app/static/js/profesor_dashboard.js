/* extracted from profesor/dashboard.html */
// Toast helper (reutiliza estilos existentes)
    (function(){
      const toast = document.getElementById('toast');
      const icon = document.getElementById('toastIcon');
      const title = document.getElementById('toastTitle');
      const msg = document.getElementById('toastMsg');
      let t = null;
      window.__toast = function(type, message, ttl){
        if(!toast) return;
        toast.classList.remove('success','warning','error');
        toast.classList.add(type || 'success');
        icon.textContent = (type === 'error') ? '⛔' : ((type === 'warning') ? '⚠️' : '✅');
        title.textContent = ttl || (type === 'error' ? 'Error' : (type === 'warning' ? 'Atención' : 'Listo'));
        msg.textContent = message || 'Acción realizada.';
        toast.style.display = 'flex';
        clearTimeout(t);
        t = setTimeout(()=>{ toast.style.display='none'; }, 2600);
      }
    })();
