// core/dom.js — DOM & markdown render primitives (phase-2 U2 carve from main.js).
// esc: HTML-escape via a detached div (the 497-site import floor).
// renderMarkdown: CommonMark subset — keeps its OWN private esc (left as-is).
// renderMarkdownBasic: lightweight heading/bold renderer; uses this module's esc.

export function esc(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }

// escAttr: HTML-escape for ATTRIBUTE-VALUE context. esc() (textContent→innerHTML)
// escapes &<> but NOT quotes, so `attr="${esc(x)}"` with an untrusted x is a
// quote-breakout XSS (`x=" onmouseover="…`). escAttr additionally escapes " and
// ' so a value can't break out of either quoting style. Use it — not esc() — on
// untrusted data that lands inside an attribute (title/data-*/value/href).
export function escAttr(t) {
  return String(t == null ? '' : t)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// safeUrl: sanitize a URL bound for an href/src attribute. Two hazards: (1) a
// `javascript:`/`data:`/`vbscript:` scheme executes on click even when the
// string is HTML-escaped; (2) an unescaped quote breaks out of the attribute.
// Returns '#' for a disallowed scheme, else the URL escAttr'd for the attribute
// context. http/https/mailto/tel and scheme-relative / path / fragment / query
// URLs are allowed (no scheme = same-origin relative).
export function safeUrl(u) {
  const s = String(u == null ? '' : u).trim();
  if (!s) return '#';
  // A scheme is letters/digits/+-. before the first ':' and before any /?#.
  const m = s.match(/^([a-zA-Z][a-zA-Z0-9+.-]*):/);
  if (m) {
    const scheme = m[1].toLowerCase();
    if (!['http', 'https', 'mailto', 'tel'].includes(scheme)) return '#';
  }
  return escAttr(s);
}

export function renderMarkdown(text, opts) {
  if (text == null) return '';
  opts = opts || {};
  const esc = s => String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  // Pull fenced code blocks out first so their contents aren't mangled. In
  // chat mode each block gets a header bar (language label + Copy + "→ step"
  // hand-off to the composer); the raw body is parked in window._mdCode so the
  // buttons can reach it by id without inlining multi-line code into onclick.
  const codeBlocks = [];
  text = text.replace(/```([\w+-]*)\n([\s\S]*?)```/g, (_, lang, body) => {
    body = body.replace(/\n$/, '');
    if (opts.chat) {
      const reg = (window._mdCode = window._mdCode || []);
      const gid = reg.length;
      reg.push({ code: body, lang: lang || '' });
      const bar = '<div class="md-codebar"><span class="md-codelang">' + esc(lang || 'text') + '</span>' +
        '<span class="md-codeacts">' +
        '<button type="button" class="md-codebtn" onclick="ChatCode.copy(' + gid + ')">copy</button>' +
        '<button type="button" class="md-codebtn accent" onclick="ChatCode.toStep(' + gid + ')" title="Send this block to the composer as a workflow step">&rarr; step</button>' +
        '</span></div>';
      codeBlocks.push('<div class="md-codewrap">' + bar + '<pre class="md-code"><code>' + esc(body) + '</code></pre></div>');
    } else {
      codeBlocks.push('<pre class="md-code"><code>' + esc(body) + '</code></pre>');
    }
    return ` CODEBLOCK${codeBlocks.length - 1} `;
  });

  // Escape the rest, then apply inline + block patterns.
  let html = esc(text);

  // GFM pipe tables — a header row, a |---|---| separator, then body rows.
  html = html.replace(/(?:^|\n)(\|.+\|[ \t]*\n\|[ \t:|-]+\|[ \t]*\n(?:\|.+\|[ \t]*\n?)*)/g, (m, block) => {
    const rows = block.trim().split('\n').map(r => r.trim());
    if (rows.length < 2) return m;
    const cells = r => r.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
    const head = cells(rows[0]);
    const body = rows.slice(2).map(cells);
    const th = head.map(c => `<th>${c}</th>`).join('');
    const trs = body.map(r => '<tr>' + head.map((_, i) => `<td>${r[i] != null ? r[i] : ''}</td>`).join('') + '</tr>').join('');
    return '\n<table class="md-table"><thead><tr>' + th + '</tr></thead><tbody>' + trs + '</tbody></table>\n';
  });

  // Headings (H1..H6).
  for (let n = 6; n >= 1; n--) {
    const re = new RegExp('^#{' + n + '} +(.*)$', 'gm');
    html = html.replace(re, (_, t) => `<h${n} class="md-h${n}">${t}</h${n}>`);
  }

  // Blockquotes — collapse consecutive "> " lines.
  html = html.replace(/(?:^|\n)((?:&gt; .*(?:\n|$))+)/g, (_, block) => {
    const inner = block.trim().split('\n').map(l => l.replace(/^&gt; ?/, '')).join('<br>');
    return '\n<blockquote class="md-quote">' + inner + '</blockquote>';
  });

  // Lists: collapse consecutive list lines into <ul>/<ol>.
  html = html.replace(/(?:^|\n)((?:[*-] .+\n?)+)/g, (_, block) => {
    const items = block.trim().split(/\n/).map(l => l.replace(/^[*-] /, '').trim());
    return '\n<ul class="md-ul">' + items.map(i => `<li>${i}</li>`).join('') + '</ul>';
  });
  html = html.replace(/(?:^|\n)((?:\d+\. .+\n?)+)/g, (_, block) => {
    const items = block.trim().split(/\n/).map(l => l.replace(/^\d+\. /, '').trim());
    return '\n<ol class="md-ol">' + items.map(i => `<li>${i}</li>`).join('') + '</ol>';
  });

  // Inline: code, links, bold, italic.
  html = html.replace(/`([^`\n]+)`/g, '<code class="md-inline-code">$1</code>');
  html = html.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, t, u) => {
    if (!/^https?:\/\//.test(u) && !u.startsWith('/')) return m; // safety: only allow http(s) or root-relative
    // Belt AND braces: the allowlist above already rejects every dangerous
    // scheme, so safeUrl is a no-op for anything that reaches here — but it
    // makes "no esc() into an href, ever" an invariant with no exception,
    // which is what the source scan in tests/ui/test_safeurl_sweep.py pins.
    return `<a href="${safeUrl(u)}" rel="noopener" target="_blank">${t}</a>`;
  });
  html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');

  // Paragraphs: split on blank lines, wrap non-block chunks.
  html = html.split(/\n{2,}/).map(chunk => {
    const t = chunk.trim();
    if (!t) return '';
    if (/^<(h[1-6]|ul|ol|pre|div|table|blockquote)/.test(t)) return t;
    if (/^CODEBLOCK\d+$/.test(t)) return t;  // standalone code block — don't wrap in <p>
    return `<p>${t.replace(/\n/g, '<br>')}</p>`;
  }).join('\n');

  // Restore code blocks (space-independent: the paragraph pass may trim the
  // sentinel's surrounding whitespace when a block stands alone).
  html = html.replace(/CODEBLOCK(\d+)/g, (_, i) => codeBlocks[+i]);

  return html;
}

export function renderMarkdownBasic(text) {
  if (!text) return '';
  let html = esc(text);
  // Headings
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');
  // Bold
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // Italic
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  // Code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Citations [N] → links
  html = html.replace(/\[(\d+)\]/g, '<sup style="color:var(--amber)">[$1]</sup>');
  // Bullet lists
  html = html.replace(/^[•\-\*] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
  // Numbered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  // Paragraphs (double newlines)
  html = html.replace(/\n{2,}/g, '</p><p>');
  html = '<p>' + html + '</p>';
  // Single newlines
  html = html.replace(/([^>])\n([^<])/g, '$1<br>$2');
  // Cleanup empty p tags
  html = html.replace(/<p>\s*<\/p>/g, '');
  html = html.replace(/<p>(<h[23]>)/g, '$1');
  html = html.replace(/(<\/h[23]>)<\/p>/g, '$1');
  html = html.replace(/<p>(<ul>)/g, '$1');
  html = html.replace(/(<\/ul>)<\/p>/g, '$1');
  return html;
}
