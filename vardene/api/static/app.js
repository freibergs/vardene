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

const CORE_ATTRS_LV = [
  "Vārdšķira", "Lietvārda tips", "Darbības vārda tips", "Vietniekvārda tips",
  "Dzimte", "Skaitlis", "Locījums", "Persona",
  "Laiks", "Izteiksme", "Pakāpe", "Noliegums",
];

const CORE_ATTRS_EN = [
  "Part of speech", "Noun type", "Verb type", "Pronoun type",
  "Gender", "Number", "Case", "Person",
  "Tense", "Mood", "Degree", "Negation",
];

function attrPairs(attrs, language = "lv") {
  if (!attrs) return "";
  const keys = language === "en" ? CORE_ATTRS_EN : CORE_ATTRS_LV;
  return keys
    .filter((k) => attrs[k] !== undefined && attrs[k] !== "Nepiemīt" && attrs[k] !== "Not applicable")
    .map((k) => `<span><strong>${escapeHtml(k)}:</strong> ${escapeHtml(attrs[k])}</span>`)
    .join("");
}

/**
 * Card layout. `headPrimary` is the big bold word (lemma in analyse, surface
 * form in inflect), `headSecondary` is the smaller annotation (e.g. "← rakt"
 * for inflected forms, or POS for analysis readings).
 */
function renderCard({ primary, tag, secondary = "", attrsHtml = "", isTop = false }) {
  return `
    <div class="reading-card ${isTop ? "top" : ""}">
      <div class="reading-head">
        <span class="reading-lemma">${escapeHtml(primary)}</span>
        <span class="reading-tag">${escapeHtml(tag || "—")}</span>
        ${secondary ? `<span class="reading-pos">${escapeHtml(secondary)}</span>` : ""}
      </div>
      ${attrsHtml ? `<div class="reading-attrs">${attrsHtml}</div>` : ""}
    </div>`;
}

function renderError(msg) {
  return `<div class="error">${escapeHtml(msg)}</div>`;
}

/**
 * Deduplicate readings by (lemma, tag). The lexicon ships multiple entries
 * for the same word (e.g. "raksts" appears in both `tezaurs` and `valerijs`
 * source files), and they surface as identical-looking cards. Keep the first
 * occurrence.
 */
function dedupReadings(readings) {
  const seen = new Set();
  const out = [];
  for (const wf of readings) {
    const key = `${wf.lemma}|${wf.tag}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(wf);
  }
  return out;
}

// ---- Analyse ---------------------------------------------------------------

async function analyzeWord() {
  const input = document.getElementById("word-input");
  const output = document.getElementById("analyze-output");
  const enToggle = document.getElementById("analyze-en");
  const word = input.value.trim();
  if (!word) {
    output.innerHTML = renderError("Enter a word.");
    return;
  }
  const language = enToggle.checked ? "en" : "lv";
  const url = language === "en"
    ? `/api/analyze/en/${encodeURIComponent(word)}`
    : `/api/analyze/${encodeURIComponent(word)}`;
  output.innerHTML = "<em>Analysing…</em>";
  try {
    const data = await fetchJson(url);
    const unique = dedupReadings(data.wordforms || []);
    if (!unique.length) {
      output.innerHTML = renderError(`No analysis for "${word}".`);
      return;
    }
    const posKey = language === "en" ? "Part of speech" : "Vārdšķira";
    output.innerHTML = unique
      .map((wf, i) => {
        // Show the surface form (what the user typed) prominently, with
        // the lemma as a small "← raksts" annotation. Mirrors how
        // api.tezaurs.lv distinguishes Vārds (form) from Pamatforma (lemma).
        const surface = wf.token || word;
        const lemmaAnno = wf.lemma && wf.lemma !== surface ? `← ${wf.lemma}` : "";
        const pos = (wf.attributes && wf.attributes[posKey]) || "";
        const secondary = lemmaAnno ? (pos ? `${lemmaAnno} · ${pos}` : lemmaAnno) : pos;
        return renderCard({
          primary: surface,
          tag: wf.tag,
          secondary,
          attrsHtml: attrPairs(wf.attributes, language),
          isTop: i === 0,
        });
      })
      .join("");
  } catch (e) {
    output.innerHTML = renderError(e.message);
  }
}

// ---- Sentence --------------------------------------------------------------

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
        return `
          <div class="token-block">
            <span class="token">${escapeHtml(t.token)}</span>
            <span class="best">→ ${escapeHtml(best.lemma || "—")}
              <span class="reading-tag">${escapeHtml(best.tag || "—")}</span>
            </span>
          </div>`;
      })
      .join("");
  } catch (e) {
    output.innerHTML = renderError(e.message);
  }
}

// ---- Inflect ---------------------------------------------------------------

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
    // For inflected forms the user wants to see the actual surface form
    // (`token`) prominently, with the lemma as a smaller annotation.
    const total = data.forms.length;
    const shown = data.forms.slice(0, 100);
    const more = total > 100
      ? `<p style="color:var(--muted);margin-top:1rem">…and ${total - 100} more.</p>`
      : "";
    output.innerHTML =
      shown
        .map((f) =>
          renderCard({
            primary: f.token || "—",
            tag: f.tag,
            secondary: f.lemma && f.lemma !== f.token ? `← ${f.lemma}` : "",
            attrsHtml: attrPairs(f.attributes),
          }),
        )
        .join("") + more;
  } catch (e) {
    output.innerHTML = renderError(e.message);
  }
}

// ---- Tokenize --------------------------------------------------------------

async function tokenize() {
  const input = document.getElementById("tokenize-input");
  const output = document.getElementById("tokenize-output");
  const text = input.value.trim();
  if (!text) {
    output.innerHTML = renderError("Enter text.");
    return;
  }
  output.innerHTML = "<em>Tokenising…</em>";
  try {
    const data = await fetchJson(`/api/tokenize/${encodeURIComponent(text)}`);
    output.innerHTML = `
      <div class="token-list">
        ${data.tokens.map((t) => `<span class="token-chip">${escapeHtml(t)}</span>`).join("")}
      </div>
      <p style="color:var(--muted);margin-top:0.75rem;font-size:0.85em">
        ${data.tokens.length} tokens — using regex fallback (Splitting.java port pending)
      </p>`;
  } catch (e) {
    output.innerHTML = renderError(e.message);
  }
}

// ---- Wire up ---------------------------------------------------------------

function bind(inputId, btnId, handler) {
  document.getElementById(btnId).addEventListener("click", handler);
  document.getElementById(inputId).addEventListener("keydown", (e) => {
    if (e.key === "Enter") handler();
  });
}

bind("word-input", "analyze-btn", analyzeWord);
bind("sentence-input", "sentence-btn", analyzeSentence);
bind("lemma-input", "inflect-btn", inflectLemma);
bind("tokenize-input", "tokenize-btn", tokenize);
