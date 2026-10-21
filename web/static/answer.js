// One answer card, the same on the front page (saved answers) and in the app (live ones).
// opts.citeHref(source) -> a link for a citation, or null for a plain label
// opts.pictureSrc(picture) -> the image URL for a picture the answer rests on
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

const FILE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>`;

// What the route did, in a student's words.
const ROUTE_WORDS = {"sql": "Read from your spreadsheet", "sql -> hybrid": "Checked your spreadsheets, then searched your files",
                     "hybrid": "Searched your files", "solve": "Worked out with methods from your files"};

function citeHTML(src, opts, quote) {
  if (!src) return "";
  // A picture's "loc" names a part of its description, not a place a student can open: leave it out.
  const where = src.loc && !isPicture(src.file) ? " · " + esc(src.loc) : "";
  const label = FILE_ICON + esc(src.file) + where;
  const href = opts.citeHref ? opts.citeHref(src, quote) : null;
  return href ? `<a class="ans-cite" href="${esc(href)}" target="_blank" rel="noopener">${label}</a>`
              : `<span class="ans-cite">${label}</span>`;
}

// opts.state: "writing" while the answer streams in (a caret follows the text being written),
// "checking" once it is written and the checker is running; omitted for a finished answer.
function answerHTML(question, a, opts = {}) {
  const writing = opts.state === "writing", checking = opts.state === "checking";
  const steps0 = a.steps || [];
  // The model writes the steps first, then the final answer: the caret sits on whichever is growing.
  const caretAt = writing ? (a.final_answer ? "final" : steps0.length ? (steps0[steps0.length - 1].quote ? "quote" : "text") : "none") : null;
  const caret = `<span class="caret" aria-hidden="true"></span>`;
  const pics = (a.pictures || []).map(p => `<figure><a href="${esc(opts.pictureSrc(p))}" target="_blank" rel="noopener" title="Open the picture"><img src="${esc(opts.pictureSrc(p))}" alt="${esc(p.kind)} from ${esc(p.file)}"></a>
      <figcaption>${esc(p.note)}</figcaption></figure>`).join("");
  // opts.sources: the page has a Sources panel, so each step ends with a Source button that opens
  // it at the excerpt the step rests on. Without one (or for an answer saved before excerpts were
  // kept), the step ends with a link to the file instead.
  const shown = new Set((a.excerpts || []).map(e => e.id));
  const sourceOf = (s, i) => {
    if (!s.source) return "";
    if (!opts.sources || !shown.has(s.source.id)) return citeHTML(s.source, opts, s.quote);
    const where = s.source.loc && !isPicture(s.source.file) ? s.source.loc : s.source.file;
    return `<button type="button" class="ans-src" data-ex="${esc(s.source.id)}" data-step="${i + 1}"
      title="Show the excerpt from ${esc(s.source.file)}">${FILE_ICON}Source<span>· ${esc(where)}</span></button>`;
  };
  const steps = steps0.map((s, i) => {
    const last = i === steps0.length - 1;
    const calc = s.calc ? `<span class="ans-calc" title="Worked out by code, not by the AI"><code>${esc(s.calc)}</code> = <b>${s.value == null ? "couldn't be worked out" : esc(s.value)}</b></span>` : "";
    return `<li>${esc(s.text)}${last && caretAt === "text" ? caret : ""}
      ${s.quote ? `<span class="ans-quote">“${esc(s.quote)}${last && caretAt === "quote" ? caret : "”"}</span>` : ""}${calc}${sourceOf(s, i)}</li>`;
  }).join("");
  const unsure = a.unsure ? `<div class="ans-unsure"><b>Unsure</b> — part of this answer could not be confirmed against your files:
      <ul>${(a.unsure_reasons || []).map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>` : "";
  const status = writing || checking ? `<div class="ans-status"><span class="thinking"><i></i><i></i><i></i></span>
      ${writing ? "Writing from your files · not checked yet" : "Checking each step against your files…"}</div>` : "";
  const route = ROUTE_WORDS[a.route?.path] || "";
  const readAs = a.standalone && a.standalone !== question ? `<div class="ans-meta">Read as: ${esc(a.standalone)}</div>` : "";
  const final = a.final_answer || !writing
    ? `<div class="ans-final ${a.not_found ? "nf" : ""}">${esc(a.final_answer)}${caretAt === "final" ? caret : ""}</div>`
    : `<div class="ans-final pending">The answer appears here once the steps are written.</div>`;
  return `<div class="ans-q">${esc(question)}</div>
    <div class="ans-card ${pics ? "has-pic" : ""} ${writing ? "is-writing" : ""}"><div>
      ${unsure}${status}
      ${route ? `<div class="ans-route">${esc(route)}</div>` : ""}
      ${final}
      ${a.route?.path === "solve" && !a.not_found ? `<div class="ans-worked">A new problem, worked out with methods from your files - not quoted from them. Every calculation is run as code, and an independent re-solve must agree.</div>` : ""}
      ${steps ? `<div class="ans-how">How this was found</div><ol class="ans-steps">${steps}</ol>` : ""}
      ${readAs}
    </div>${pics ? `<div>${pics}</div>` : ""}</div>`;
}

const isPicture = file => /\.(png|jpe?g|gif|webp)$/i.test(file || "");

// The quoted words, marked inside an excerpt's text. A quote may cross markdown and table marks
// ("G7 | WED"), so the words are matched with any of those between them. Not found: left unmarked.
function markQuotes(text, quotes) {
  const ranges = [];
  for (const {q, step} of quotes) {
    const words = String(q || "").replace(/[“”]/g, "").split(/\s+/).filter(Boolean)
      .map(w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    if (!words.length) continue;
    const m = new RegExp(words.join("[\\s|*_#>`~-]*"), "i").exec(text);
    if (m) ranges.push([m.index, m.index + m[0].length, step]);
  }
  ranges.sort((x, y) => x[0] - y[0]);
  let out = "", pos = 0;
  for (const [s, e, step] of ranges) {
    if (s < pos) continue;  // overlaps an earlier mark
    out += esc(text.slice(pos, s)) + `<mark data-step="${step}">${esc(text.slice(s, e))}</mark>`;
    pos = e;
  }
  return out + esc(text.slice(pos));
}

// The Sources panel for one answer: the excerpts its steps rest on, open, with the quoted words
// marked; then whatever else was searched, closed (its text shows only when opened).
// state: "reading" (still searching), "writing" (excerpts found, answer being written), or done.
function sourcesHTML(question, a, opts = {}, state) {
  const top = `<div class="src-for">For: ${esc(question)}</div>`;
  if (state === "reading" || !a) return top + `<div class="src-empty"><span class="thinking"><i></i><i></i><i></i></span> Searching your Library…</div>`;
  const ex = (a.excerpts || []).map(e => ({...e, text: String(e.text || "").replace(/&amp;/g, "&")}));
  if (!ex.length) return top + `<div class="src-empty">${a.excerpts ? "Nothing was read from your Library for this answer."
                                                                  : "This answer was saved before sources were kept."}</div>`;
  const by = {};
  (a.steps || []).forEach((s, i) => { if (s.source?.id) (by[s.source.id] ||= []).push({q: s.quote, step: i + 1}); });
  const cited = ex.filter(e => by[e.id]).sort((x, y) => by[x.id][0].step - by[y.id][0].step);
  const rest = ex.filter(e => !by[e.id]);
  const head = e => `<div class="xc-head">${FILE_ICON}<span class="xc-file">${esc(e.file)}</span>${e.loc && !isPicture(e.file) ? `<span class="xc-loc">${esc(e.loc)}</span>` : ""}</div>`;
  const open = e => { const h = opts.citeHref ? opts.citeHref(e, by[e.id]?.[0]?.q) : null;
                      return h ? `<a class="xc-open" href="${esc(h)}" target="_blank" rel="noopener">Open in the file ↗</a>` : ""; };
  const gone = `<div class="xc-text"><i>This file has been deleted from your Library.</i></div>`;
  const card = e => `<article class="xc" data-ex="${esc(e.id)}">${head(e)}
      <div class="xc-meta"><span>${by[e.id].map(x => `Step ${x.step}`).join(" · ")}</span>${e.deleted ? "" : open(e)}</div>
      ${e.deleted ? gone : `<div class="xc-text">${markQuotes(e.text, by[e.id])}</div>`}</article>`;
  const closed = e => `<details class="xc" data-ex="${esc(e.id)}"><summary>${head(e)}</summary>
      <div class="xc-meta"><span></span>${e.deleted ? "" : open(e)}</div>${e.deleted ? gone : `<div class="xc-text">${esc(e.text)}</div>`}</details>`;
  const intro = cited.length ? `<div class="src-label">Found in ${cited.length} excerpt${cited.length === 1 ? "" : "s"}</div>`
    : state === "writing" ? `<div class="src-label">Read ${ex.length} excerpt${ex.length === 1 ? "" : "s"}; the steps will point to the ones they use</div>`
    : `<div class="src-label">No excerpt answered this</div>`;
  const label = state === "writing" ? "Also read" : "Also read, not used in this answer";
  return top + intro + cited.map(card).join("")
    + (rest.length ? `<div class="src-label muted">${label} (${rest.length})</div>` + rest.map(closed).join("") : "");
}

function thinkingHTML(question, label) {
  return `<div class="ans-q">${esc(question)}</div>
    <div class="ans-card"><div class="thinking"><i></i><i></i><i></i> ${esc(label || "Reading your Library…")}</div></div>`;
}

const ANCHOR_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="5" r="2.5"/><path d="M12 7.5V21"/><path d="M8 11h8"/><path d="M4.5 13.5a7.5 7.5 0 0 0 15 0"/><path d="M2.5 15.5l2-2 2 2"/><path d="M17.5 15.5l2-2 2 2"/></svg>`;
const SEND_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5"/><path d="M5 12l7-7 7 7"/></svg>`;
