/* Safe, lightweight Markdown-style renderer used by every AI answer panel. */
window.AIFormatter = (() => {
  const escapeHtml = value => String(value || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const inline = value => value
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/__(.+?)__/g, '<u>$1</u>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');

  function render(answer) {
    const lines = escapeHtml(answer).replace(/\r/g, '').split('\n');
    let html = '', list = '', code = false, codeLines = [];
    const closeList = () => { if (list) { html += `</${list}>`; list = ''; } };
    const closeCode = () => { if (code) { html += `<pre class="ai-diagram">${codeLines.join('\n')}</pre>`; code = false; codeLines = []; } };

    for (const raw of lines) {
      if (raw.trim().startsWith('```')) { if (code) closeCode(); else { closeList(); code = true; } continue; }
      if (code) { codeLines.push(raw); continue; }
      const h = raw.match(/^(#{1,4})\s+(.+)$/);
      const bullet = raw.match(/^\s*[-*•]\s+(.+)$/);
      const number = raw.match(/^\s*\d+[.)]\s+(.+)$/);
      const quote = raw.match(/^&gt;\s*(.+)$/);
      if (h) { closeList(); html += `<h${Math.min(4, h[1].length + 1)}>${inline(h[2])}</h${Math.min(4, h[1].length + 1)}>`; }
      else if (bullet || number) {
        const type = number ? 'ol' : 'ul';
        if (list !== type) { closeList(); html += `<${type}>`; list = type; }
        html += `<li>${inline((bullet || number)[1])}</li>`;
      } else if (quote) { closeList(); html += `<blockquote>${inline(quote[1])}</blockquote>`; }
      else if (raw.trim()) { closeList(); html += `<p>${inline(raw)}</p>`; }
      else { closeList(); }
    }
    closeCode(); closeList();
    return html || '<p>No answer received.</p>';
  }
  return { render, escapeHtml };
})();
