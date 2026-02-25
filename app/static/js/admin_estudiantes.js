/* extracted from admin/estudiantes.html */
function openStudentModal(id){
    const el = document.getElementById('sm-' + id);
    if(!el) return;
    el.classList.add('show');
    document.body.style.overflow = 'hidden';
  }
  function closeStudentModal(id){
    const el = document.getElementById('sm-' + id);
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
