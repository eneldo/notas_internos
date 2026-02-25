/* extracted from admin/qr.html */
function copyLink(){
    const el = document.getElementById('formUrl');
    el.select();
    el.setSelectionRange(0, 99999);
    try { document.execCommand('copy'); } catch (e) {}
  }
