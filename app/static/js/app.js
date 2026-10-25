document.addEventListener('DOMContentLoaded', () => {
  const sidebar = document.getElementById('appSidebar');
  const toggle = document.getElementById('menuToggle');
  const scrim = document.getElementById('sidebarScrim');
  const closeSidebar = () => {
    if (!sidebar || !toggle || !scrim) return;
    sidebar.classList.remove('open');
    scrim.classList.remove('show');
    toggle.setAttribute('aria-expanded', 'false');
  };
  if (sidebar && toggle && scrim) {
    toggle.addEventListener('click', () => {
      const open = !sidebar.classList.contains('open');
      sidebar.classList.toggle('open', open);
      scrim.classList.toggle('show', open);
      toggle.setAttribute('aria-expanded', String(open));
    });
    scrim.addEventListener('click', closeSidebar);
    document.addEventListener('keydown', event => { if (event.key === 'Escape') closeSidebar(); });
  }
  const publicToggle = document.getElementById('publicMenuToggle');
  const publicNav = document.querySelector('.public-nav');
  if (publicToggle && publicNav) {
    publicToggle.addEventListener('click', () => {
      const open = !publicNav.classList.contains('open');
      publicNav.classList.toggle('open', open);
      publicToggle.setAttribute('aria-expanded', String(open));
    });
  }
  const category = document.getElementById('business_type');
  const customGroup = document.getElementById('customTypeGroup');
  if (category && customGroup) {
    const updateCategory = () => {
      const show = category.value === 'Other';
      customGroup.hidden = !show;
      const custom = document.getElementById('custom_type');
      if (custom) custom.required = show;
    };
    category.addEventListener('change', updateCategory);
    updateCategory();
  }
  document.querySelectorAll('[data-file-name]').forEach(input => {
    input.addEventListener('change', () => {
      const target = document.getElementById(input.dataset.fileName);
      if (target) target.textContent = input.files && input.files[0] ? input.files[0].name : 'No document selected';
    });
  });
  document.querySelectorAll('[data-confirm]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  document.querySelectorAll('[data-voice-target]').forEach(button => {
    const target = document.getElementById(button.dataset.voiceTarget);
    const status = document.querySelector(`[data-voice-status="${button.dataset.voiceTarget}"]`);
    const setStatus = text => { if (status) status.textContent = text; };
    if (!SpeechRecognition) {
      button.disabled = true;
      button.title = 'Voice input is not supported here; type in the field instead.';
      setStatus('Voice input is not supported in this browser. You can type instead.');
      return;
    }
    button.addEventListener('click', () => {
      if (!target || button.dataset.listening === 'true') return;
      const recognition = new SpeechRecognition();
      recognition.lang = 'en-IN';
      recognition.interimResults = false;
      recognition.maxAlternatives = 1;
      recognition.onstart = () => {
        button.dataset.listening = 'true';
        button.classList.add('is-listening');
        setStatus('Listening… speak now.');
      };
      recognition.onresult = event => {
        const transcript = event.results?.[0]?.[0]?.transcript?.trim();
        if (transcript) {
          const separator = target.value && target.tagName === 'TEXTAREA' ? '\n' : (target.value ? ' ' : '');
          target.value = `${target.value || ''}${separator}${transcript}`.trim();
          target.dispatchEvent(new Event('input', { bubbles: true }));
          setStatus('Text added. Review it before saving.');
        }
      };
      recognition.onerror = event => {
        const message = event.error === 'not-allowed' ? 'Microphone permission was not granted.' : 'Voice entry stopped. You can type instead.';
        setStatus(message);
      };
      recognition.onend = () => {
        button.dataset.listening = 'false';
        button.classList.remove('is-listening');
      };
      try { recognition.start(); } catch (_error) { setStatus('Voice input could not start. You can type instead.'); }
    });
  });

  const ocrButton = document.getElementById('startBillOcr');
  if (ocrButton) {
    const fileInput = document.getElementById('document');
    const status = document.getElementById('billOcrStatus');
    const rawText = document.getElementById('billOcrText');
    const details = document.getElementById('billOcrDetails');
    const setStatus = text => { if (status) status.textContent = text; };
    const put = (id, value) => {
      const input = document.getElementById(id);
      if (input && value && !input.value.trim()) {
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
      }
      return false;
    };
    const toIsoDate = raw => {
      const m = raw.match(/^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$/);
      if (!m) {
        const iso = raw.match(/^(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})$/);
        if (!iso) return '';
        return `${iso[1]}-${iso[2].padStart(2, '0')}-${iso[3].padStart(2, '0')}`;
      }
      let year = Number(m[3]);
      if (year < 100) year += year < 70 ? 2000 : 1900;
      const month = Number(m[2]);
      const day = Number(m[1]);
      const check = new Date(Date.UTC(year, month - 1, day));
      if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) return '';
      return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    };
    ocrButton.addEventListener('click', async () => {
      const file = fileInput?.files?.[0];
      if (!file) { setStatus('Choose a PNG/JPG/JPEG bill image first. PDFs can still be entered manually.'); return; }
      if (!/^image\/(png|jpeg)$/.test(file.type)) { setStatus('Image extraction supports PNG and JPG/JPEG. For PDFs, review and enter the fields manually.'); return; }
      if (!window.Tesseract?.recognize) { setStatus('Image reader did not load. You can still review and enter all fields manually.'); return; }
      ocrButton.disabled = true;
      setStatus('Reading the image in this browser…');
      try {
        const result = await window.Tesseract.recognize(file, 'eng', {
          logger: message => {
            if (message.status === 'recognizing text' && Number.isFinite(message.progress)) {
              setStatus(`Reading bill image: ${Math.round(message.progress * 100)}%.`);
            }
          }
        });
        const text = (result.data?.text || '').trim();
        if (rawText) rawText.textContent = text || 'No readable text was returned.';
        if (details) details.open = true;
        if (!text) { setStatus('No text was recognized. Enter the fields manually and review the uploaded bill.'); return; }
        const lines = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
        const firstLine = lines.find(line => line.length >= 2 && line.length <= 100 && !/^(tax invoice|invoice|bill|receipt|original|duplicate)$/i.test(line));
        const number = text.match(/(?:invoice|bill|inv)\s*(?:no\.?|number|#)?\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\/-]{2,})/i);
        const total = text.match(/(?:grand\s*total|total\s*(?:amount|due|payable)?|amount\s*due|balance\s*due)\s*(?:INR|Rs\.?|₹)?\s*[:\-]?\s*[₹]?\s*([0-9][0-9,]*(?:\.\d{1,2})?)/i);
        const dateToken = '(\\d{1,2}[/.\\-]\\d{1,2}[/.\\-]\\d{2,4}|\\d{4}[/.\\-]\\d{1,2}[/.\\-]\\d{1,2})';
        const issueRaw = text.match(new RegExp('(?:invoice|bill)\\s*date\\s*[:\\-]?\\s*' + dateToken, 'i'))?.[1];
        const dueRaw = text.match(new RegExp('(?:due|payment)\\s*date\\s*[:\\-]?\\s*' + dateToken, 'i'))?.[1];
        const suggested = [];
        if (put('invoice_number', number?.[1] || '')) suggested.push('reference');
        if (put('party_name', firstLine || '')) suggested.push('party name');
        if (put('total_amount', total?.[1]?.replace(/,/g, '') || '')) suggested.push('total');
        if (put('issue_date', issueRaw ? toIsoDate(issueRaw) : '')) suggested.push('invoice date');
        if (put('due_date', dueRaw ? toIsoDate(dueRaw) : '')) suggested.push('due date');
        setStatus(`${suggested.length ? `Suggested ${suggested.join(', ')}.` : 'Text extracted, but no fields matched confidently.'} Review every value against the original bill before saving.`);
      } catch (_error) {
        setStatus('Could not read this image. You can enter the details manually and still upload the original.');
      } finally {
        ocrButton.disabled = false;
      }
    });
  }
});
