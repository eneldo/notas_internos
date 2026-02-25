/* extracted from rate.html */
const btnWA  = document.getElementById('btnWA');
    const btnQR  = document.getElementById('btnQR');
    const btnWA2 = document.getElementById('btnWA2');
    const btnQR2 = document.getElementById('btnQR2');

    const rotSel = document.getElementById('rotSelect');
    const mesSel = document.getElementById('mesSelect');

    const rotLbl = document.getElementById('rotacionLabel');
    const mesLbl = document.getElementById('mesLabel');

    const sbRot  = document.getElementById('sbRotacion');
    const sbMes  = document.getElementById('sbMes');

    function refreshLinks(){
      const r = rotSel.value;
      const mes = mesSel.value || "";
      const mesEnc = encodeURIComponent(mes);

      const waHref = `/go/wa?r=${r}&mes=${mesEnc}`;
      const qrHref = `/qr/${r}?mes=${mesEnc}`;

      btnWA.href = waHref; btnQR.href = qrHref;
      btnWA2.href = waHref; btnQR2.href = qrHref;

      const rotText = rotSel.options[rotSel.selectedIndex]?.text || "—";
      rotLbl.textContent = rotText;
      mesLbl.textContent = mes || "—";

      sbRot.textContent = rotText;
      sbMes.textContent = mes || "—";
    }

    rotSel.addEventListener('change', refreshLinks);
    mesSel.addEventListener('change', refreshLinks);
    refreshLinks();
