// ---- Tabs -----------------------------------------------------------------
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
  });
});

// ---- Helpers --------------------------------------------------------------
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

const CASE_ORDER = ["Nominatīvs", "Ģenitīvs", "Datīvs", "Akuzatīvs", "Lokatīvs", "Vokatīvs"];

// ---- Analyse single word --------------------------------------------------
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

// ---- Sentence -------------------------------------------------------------
async function analyzeSentence() {
  const input = document.getElementById("sentence-input");
  const output = document.getElementById("sentence-output");
  const text = input.value.trim();
  if (!text) {
    output.innerHTML = renderError("Enter a sentence.");
    return;
  }
  const mode = document.querySelector('input[name="sentence-mode"]:checked').value;
  output.innerHTML = "<em>Analysing…</em>";
  try {
    if (mode === "best") {
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
    } else {
      const data = await fetchJson(`/api/analyzesentence/${encodeURIComponent(text)}`);
      output.innerHTML = data.tokens.map((t) => {
        const wfs = dedupReadings(t.wordforms || []);
        if (!wfs.length) {
          return `<div class="sentence-token"><h3>${escapeHtml(t.token)}</h3><p style="color:var(--muted)">No analysis</p></div>`;
        }
        return `
          <div class="sentence-token">
            <h3>${escapeHtml(t.token)}</h3>
            ${wfs.map((wf, i) => renderCard({
              primary: wf.token || t.token,
              tag: wf.tag,
              secondary: wf.lemma && wf.lemma !== (wf.token || t.token) ? `← ${wf.lemma}` : "",
              attrsHtml: attrPairs(wf.attributes),
              isTop: i === 0,
            })).join("")}
          </div>`;
      }).join("");
    }
  } catch (e) {
    output.innerHTML = renderError(e.message);
  }
}

// ---- Tokenise -------------------------------------------------------------
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
        ${data.tokens.length} tokens — Splitting.java FSA port
      </p>`;
  } catch (e) {
    output.innerHTML = renderError(e.message);
  }
}

// ---- Inflect a lemma ------------------------------------------------------
async function inflectLemma() {
  const input = document.getElementById("lemma-input");
  const output = document.getElementById("inflect-output");
  const lemma = input.value.trim();
  if (!lemma) {
    output.innerHTML = renderError("Enter a lemma.");
    return;
  }
  const paradigm = document.getElementById("inflect-paradigm").value.trim();
  const lang = document.getElementById("inflect-lang").value;
  const stem1 = document.getElementById("inflect-stem1").value.trim();
  const stem2 = document.getElementById("inflect-stem2").value.trim();
  const stem3 = document.getElementById("inflect-stem3").value.trim();

  const params = new URLSearchParams();
  if (paradigm) params.set("paradigm", paradigm);
  if (stem1) params.set("stem1", stem1);
  if (stem2) params.set("stem2", stem2);
  if (stem3) params.set("stem3", stem3);

  const url = `/api/inflect/json/${lang}/${encodeURIComponent(lemma)}${params.toString() ? "?" + params : ""}`;
  output.innerHTML = "<em>Inflecting…</em>";
  try {
    const data = await fetchJson(url);
    if (!data.forms || !data.forms.length) {
      output.innerHTML = renderError(`No forms for "${lemma}".`);
      return;
    }
    const total = data.forms.length;
    const shown = data.forms.slice(0, 100);
    const more = total > 100
      ? `<p style="color:var(--muted);margin-top:1rem">…and ${total - 100} more.</p>`
      : "";
    output.innerHTML =
      `<p style="color:var(--muted);margin-bottom:0.5rem">${total} forms${paradigm ? ` · paradigm <code>${escapeHtml(paradigm)}</code>` : ""}</p>` +
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

// ---- Suitable paradigms ---------------------------------------------------
async function findParadigms() {
  const input = document.getElementById("paradigm-input");
  const output = document.getElementById("paradigm-output");
  const lemma = input.value.trim();
  if (!lemma) {
    output.innerHTML = renderError("Enter a lemma.");
    return;
  }
  output.innerHTML = "<em>Searching…</em>";
  try {
    const data = await fetchJson(`/api/suitable_paradigm/${encodeURIComponent(lemma)}`);
    if (!data.length) {
      output.innerHTML = renderError(`No paradigm could generate "${lemma}".`);
      return;
    }
    output.innerHTML = `
      <table class="api-table">
        <thead><tr><th>Rank</th><th>ID</th><th>Paradigm</th></tr></thead>
        <tbody>
          ${data.map((p, i) => `
            <tr><td>${i + 1}</td><td>${p.ID}</td><td><code>${escapeHtml(p.Description)}</code></td></tr>
          `).join("")}
        </tbody>
      </table>
      <p style="color:var(--muted);margin-top:0.75rem;font-size:0.85em">Sorted by ending frequency in the gold corpus (most common first).</p>`;
  } catch (e) {
    output.innerHTML = renderError(e.message);
  }
}

// ---- Phrase: inflect + normalise ------------------------------------------
async function inflectPhrase() {
  const input = document.getElementById("phrase-input");
  const output = document.getElementById("phrase-output");
  const text = input.value.trim();
  if (!text) {
    output.innerHTML = renderError("Enter a phrase.");
    return;
  }
  const cat = document.getElementById("phrase-category").value;
  const url = `/api/inflect_phrase/${encodeURIComponent(text)}${cat ? `?category=${cat}` : ""}`;
  output.innerHTML = "<em>Inflecting…</em>";
  try {
    const data = await fetchJson(url);
    const cases = ["Nominatīvs", "Ģenitīvs", "Datīvs", "Akuzatīvs", "Lokatīvs"];
    const meta = data.Dzimte ? `<p style="color:var(--muted);margin-top:0.75rem;font-size:0.85em">Detected gender: <strong>${escapeHtml(data.Dzimte)}</strong></p>` : "";
    output.innerHTML = `
      <table class="phrase-table">
        <tbody>
          ${cases.map((c) => data[c]
            ? `<tr><td class="case">${escapeHtml(c)}</td><td>${escapeHtml(data[c])}</td></tr>`
            : "").join("")}
        </tbody>
      </table>${meta}`;
  } catch (e) {
    output.innerHTML = renderError(e.message);
  }
}

async function normalisePhrase() {
  const input = document.getElementById("phrase-input");
  const output = document.getElementById("phrase-output");
  const text = input.value.trim();
  if (!text) {
    output.innerHTML = renderError("Enter a phrase.");
    return;
  }
  const cat = document.getElementById("phrase-category").value;
  const url = `/api/normalize_phrase/${encodeURIComponent(text)}${cat ? `?category=${cat}` : ""}`;
  output.innerHTML = "<em>Normalising…</em>";
  try {
    const data = await fetchJson(url);
    output.innerHTML = `
      <div class="reading-card top">
        <div class="reading-head">
          <span class="reading-lemma">${escapeHtml(data)}</span>
          <span class="reading-pos">← ${escapeHtml(text)}</span>
        </div>
      </div>`;
  } catch (e) {
    output.innerHTML = renderError(e.message);
  }
}

// ---- People ---------------------------------------------------------------
async function inflectPeople() {
  const input = document.getElementById("people-input");
  const output = document.getElementById("people-output");
  const text = input.value.trim();
  if (!text) {
    output.innerHTML = renderError("Enter a name.");
    return;
  }
  const gender = document.getElementById("people-gender").value;
  const url = `/api/inflect_people/json/${encodeURIComponent(text)}${gender ? `?gender=${gender}` : ""}`;
  output.innerHTML = "<em>Inflecting…</em>";
  try {
    const data = await fetchJson(url);
    output.innerHTML = data.map((component) => {
      if (component.length === 1 && Object.keys(component[0]).length === 1) {
        return `<div class="phrase-component"><h3>${escapeHtml(component[0].Vārds)}</h3><p style="color:var(--muted)">No matching gender / not inflectable.</p></div>`;
      }
      const byNumberCase = {};
      for (const f of component) byNumberCase[`${f.Skaitlis}|${f.Locījums}`] = f.Vārds;
      const head = component[0];
      const meta = [head.Dzimte, head.Deklinācija ? `${head.Deklinācija}. dekl.` : ""].filter(Boolean).join(" · ");
      return `
        <div class="phrase-component">
          <h3>${escapeHtml(head.Vārds)}<span class="reading-pos">${escapeHtml(meta)}</span></h3>
          <table class="phrase-table">
            <thead><tr><th></th><th>Vienskaitlis</th><th>Daudzskaitlis</th></tr></thead>
            <tbody>
              ${CASE_ORDER.map((c) => `
                <tr>
                  <td class="case">${escapeHtml(c)}</td>
                  <td>${escapeHtml(byNumberCase[`Vienskaitlis|${c}`] || "—")}</td>
                  <td>${escapeHtml(byNumberCase[`Daudzskaitlis|${c}`] || "—")}</td>
                </tr>`).join("")}
            </tbody>
          </table>
        </div>`;
    }).join("");
  } catch (e) {
    output.innerHTML = renderError(e.message);
  }
}

// ---- Wire up --------------------------------------------------------------
function bind(inputId, btnId, handler) {
  document.getElementById(btnId).addEventListener("click", handler);
  document.getElementById(inputId).addEventListener("keydown", (e) => {
    if (e.key === "Enter") handler();
  });
}

bind("word-input",     "analyze-btn",  analyzeWord);
bind("sentence-input", "sentence-btn", analyzeSentence);
bind("tokenize-input", "tokenize-btn", tokenize);
bind("lemma-input",    "inflect-btn",  inflectLemma);
bind("paradigm-input", "paradigm-btn", findParadigms);
bind("phrase-input",   "phrase-btn",   inflectPhrase);
document.getElementById("phrase-normalize-btn").addEventListener("click", normalisePhrase);
bind("people-input",   "people-btn",   inflectPeople);
