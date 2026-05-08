// Tabs
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
  });
});

// Helpers
async function fetchJson(url, opts = {}) {
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}

const CORE_ATTRS = [
  "Vārdšķira",
  "Lietvārda tips",
  "Darbības vārda tips",
  "Vietniekvārda tips",
  "Dzimte",
  "Skaitlis",
  "Locījums",
  "Persona",
  "Laiks",
  "Izteiksme",
  "Pakāpe",
  "Noliegums",
];

function renderReading(wf, isTop) {
  const lemma = wf.lemma || "—";
  const tag = wf.tag || "—";
  const pos = wf.attributes && wf.attributes["Vārdšķira"];
  const attrs = wf.attributes || {};
  const attrPairs = CORE_ATTRS.filter((k) => attrs[k] !== undefined && attrs[k] !== "Nepiemīt")
    .map((k) => `<span><strong>${escapeHtml(k)}:</strong> ${escapeHtml(attrs[k])}</span>`)
    .join("");
  return `
    <div class="reading-card ${isTop ? "top" : ""}">
      <div class="reading-head">
        <span class="reading-lemma">${escapeHtml(lemma)}</span>
        <span class="reading-tag">${escapeHtml(tag)}</span>
        ${pos ? `<span class="reading-pos">${escapeHtml(pos)}</span>` : ""}
      </div>
      ${attrPairs ? `<div class="reading-attrs">${attrPairs}</div>` : ""}
    </div>`;
}

function renderError(msg) {
  return `<div class="error">${escapeHtml(msg)}</div>`;
}

// Single-word analysis
async function analyzeWord() {
  const input = document.getElementById("word-input");
  const output = document.getElementById("analyze-output");
  const word = input.value.trim();
  if (!word) {
    output.innerHTML = renderError("Enter a word.");
    return;
  }
  output.innerHTML = "<em>Analysing…</em>";
  try {
    const data = await fetchJson(`/api/analyze/${encodeURIComponent(word)}`);
    if (!data.wordforms.length) {
      output.innerHTML = renderError(`No analysis for "${word}".`);
      return;
    }
    output.innerHTML = data.wordforms
      .map((wf, i) => renderReading(wf, i === 0))
      .join("");
  } catch (e) {
    output.innerHTML = renderError(e.message);
  }
}

// Sentence analysis
async function analyzeSentence() {
  const input = document.getElementById("sentence-input");
  const output = document.getElementById("sentence-output");
  const text = input.value.trim();
  if (!text) {
    output.innerHTML = renderError("Enter a sentence.");
    return;
  }
  output.innerHTML = "<em>Analysing…</em>";
  try {
    const data = await fetchJson(`/api/morphotagger/${encodeURIComponent(text)}`);
    output.innerHTML = data.tokens
      .map((t) => {
        const best = t.best;
        if (!best) {
          return `<div class="token-block"><span class="token">${escapeHtml(t.token)}</span><span class="best">— no analysis</span></div>`;
        }
        const lemma = best.lemma || "—";
        const tag = best.tag || "—";
        return `
          <div class="token-block">
            <span class="token">${escapeHtml(t.token)}</span>
            <span class="best">→ ${escapeHtml(lemma)} <span class="reading-tag">${escapeHtml(tag)}</span></span>
          </div>`;
      })
      .join("");
  } catch (e) {
    output.innerHTML = renderError(e.message);
  }
}

// Inflection
async function inflectLemma() {
  const input = document.getElementById("lemma-input");
  const output = document.getElementById("inflect-output");
  const lemma = input.value.trim();
  if (!lemma) {
    output.innerHTML = renderError("Enter a lemma.");
    return;
  }
  output.innerHTML = "<em>Inflecting…</em>";
  try {
    const data = await fetchJson(`/api/v1/inflections/${encodeURIComponent(lemma)}`);
    if (!data.forms.length) {
      output.innerHTML = renderError(`No forms for "${lemma}".`);
      return;
    }
    const total = data.forms.length;
    const shown = data.forms.slice(0, 50);
    const more = total > 50 ? `<p style="color:var(--muted)">…and ${total - 50} more.</p>` : "";
    output.innerHTML =
      shown.map((f) => renderReading(f, false)).join("") + more;
  } catch (e) {
    output.innerHTML = renderError(e.message);
  }
}

// Wire up
document.getElementById("analyze-btn").addEventListener("click", analyzeWord);
document.getElementById("word-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") analyzeWord();
});

document.getElementById("sentence-btn").addEventListener("click", analyzeSentence);
document.getElementById("sentence-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") analyzeSentence();
});

document.getElementById("inflect-btn").addEventListener("click", inflectLemma);
document.getElementById("lemma-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") inflectLemma();
});
