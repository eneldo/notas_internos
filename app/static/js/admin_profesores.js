/* extracted from admin/profesores.html */
// Cerrar modal al hacer click en el fondo
  document.addEventListener('click', (e) => {
    const dlg = e.target;
    if (dlg && dlg.tagName === 'DIALOG' && dlg.classList.contains('modal')) {
      // si el click fue directamente sobre el backdrop del dialog
      const rect = dlg.getBoundingClientRect();
      const inCard = (
        e.clientX >= rect.left && e.clientX <= rect.right &&
        e.clientY >= rect.top && e.clientY <= rect.bottom
      );
      // En <dialog>, el backdrop es parte del elemento; cuando se hace click fuera del card,
      // el target suele ser el dialog. Cerramos.
      if (inCard) {
        // Si el usuario hizo click sobre el dialog pero no sobre el card, también cerramos.
        // Detectamos si el click está sobre un hijo con clase modal-card.
        const card = dlg.querySelector('.modal-card');
        if (card && !card.contains(e.target)) {
          dlg.close();
        }
      } else {
        dlg.close();
      }
    }
  });
  // Fallback simple: si el target es el dialog (click en backdrop), cerrar
  document.querySelectorAll('dialog.modal').forEach(d => {
    d.addEventListener('click', (e) => {
      if (e.target === d) d.close();
    });
  });

function openTeacherModal(id){
  const el = document.getElementById('tm-' + id);
  if(!el) return;
  el.classList.add('show');
  document.body.style.overflow = 'hidden';
}
function closeTeacherModal(id){
  const el = document.getElementById('tm-' + id);
  if(!el) return;
  el.classList.remove('show');
  document.body.style.overflow = '';
}
// Cerrar con ESC
document.addEventListener('keydown', function(e){
  if(e.key !== 'Escape') return;
  const open = document.querySelector('.tmodal.show');
  if(open){
    open.classList.remove('show');
    document.body.style.overflow = '';
  }
});
