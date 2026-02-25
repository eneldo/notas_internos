/* extracted from auth/login.html */
(function(){
      const buttons = document.querySelectorAll('.auth-toggle-btn');
      const roleInput = document.getElementById('role_hint');
      buttons.forEach(btn => {
        btn.addEventListener('click', () => {
          buttons.forEach(b => {
            b.classList.remove('is-active');
            b.setAttribute('aria-selected', 'false');
          });
          btn.classList.add('is-active');
          btn.setAttribute('aria-selected', 'true');
          roleInput.value = btn.dataset.role || 'admin';
        });
      });
    })();
