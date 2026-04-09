// Podcast player with synchronized transcript and inline passage reveal

const SPEAKER_COLORS = {
    "Host":               "#f0a500",
    "Eleanor Hartley":    "#4ecdc4",
    "James Blackstone":   "#6c7b95",
    "Caroline Woodcourt": "#c06c84",
    "Narrator":           "#aaaacc",
    "Edmund Leigh":       "#8e7cc3",
    "Daniel Rosen":       "#e07c5a",
    "Oliver Trevelyan":   "#5cb85c",
};

const SPEEDS = [0.75, 1.0, 1.25, 1.5, 2.0];

let novels = {};       // { "Bleak House": [{run_id, experts, ...}, ...], ... }
let currentRuns = []; // runs for the currently selected novel
let manifest = null;
let flatTurns = [];
let audio = null;
let currentTurnIdx = -1;
let speedIdx = 1;
let openPassageTurnId = null;

function versionSortKey(version) {
    const nums = String(version).match(/\d+/g);
    return (nums || ["0"]).map(n => parseInt(n, 10));
}

function compareVersions(a, b) {
    const ak = versionSortKey(a);
    const bk = versionSortKey(b);
    const len = Math.max(ak.length, bk.length);
    for (let i = 0; i < len; i++) {
        const av = ak[i] || 0;
        const bv = bk[i] || 0;
        if (av !== bv) return av - bv;
    }
    return 0;
}

// ── DOM refs ──
const novelTitle      = document.getElementById("novel-title");
const novelSelect     = document.getElementById("novel-select");
const panelSelect     = document.getElementById("panel-select");
const groundingSelect = document.getElementById("grounding-select");
const hostprepSelect  = document.getElementById("hostprep-select");
const expertChips     = document.getElementById("expert-chips");
const playBtn      = document.getElementById("play-btn");
const seekBar      = document.getElementById("seek-bar");
const timeDisplay  = document.getElementById("time-display");
const speedBtn     = document.getElementById("speed-btn");
const segmentNav   = document.getElementById("segment-nav");
const transcript   = document.getElementById("transcript");
const loading      = document.getElementById("loading");

// ── Init ──
async function init() {
    // Direct link: /?run=ext_v01_baseline skips selectors
    const params = new URLSearchParams(window.location.search);
    const directRun = params.get("run");

    novels = await fetch("/api/novels").then(r => r.json());
    const novelNames = Object.keys(novels);

    if (directRun) {
        // Hide selectors, load directly
        novelSelect.style.display = "none";
        showSelect(panelSelect, false);
        showSelect(groundingSelect, false);
        showSelect(hostprepSelect, false);
        // Find the novel for this run
        for (const [name, runs] of Object.entries(novels)) {
            if (runs.some(r => r.run_id === directRun)) {
                novelTitle.textContent = name + " Unpacked";
                document.title = name + " — Literary Podcast";
                break;
            }
        }
        loadRun(directRun);
        return;
    }

    if (novelNames.length === 0) {
        loading.textContent = "No podcast runs with audio found.";
        return;
    }

    novelSelect.innerHTML = "";
    for (const name of novelNames) {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        novelSelect.appendChild(opt);
    }
    novelSelect.addEventListener("change", () => selectNovel(novelSelect.value));
    panelSelect.addEventListener("change", () => onPanelChange());
    groundingSelect.addEventListener("change", () => onGroundingChange());
    hostprepSelect.addEventListener("change", () => onHostprepChange());
    selectNovel(novelNames[0]);
}

// ── Selector helpers ──

function groundingKey(condition) {
    return (condition === "no passages") ? "nop" : "passages";
}

function groundingLabel(gk) {
    return gk === "nop" ? "No passage grounding" : "With passage grounding";
}

function formatPanelLabel(panelField) {
    // "Panel A (Hartley / Blackstone / Woodcourt)" → "Hartley, Blackstone & Woodcourt"
    // "Chen / Martinez / Volkov" → "Chen, Martinez & Volkov"
    const inner = panelField.replace(/^Panel \w+ \((.+)\)$/, "$1");
    const parts = inner.split(" / ").map(s => s.trim());
    if (parts.length === 3) return `${parts[0]}, ${parts[1]} & ${parts[2]}`;
    return parts.join(" & ");
}

function showSelect(el, show) {
    // Hide/show the wrapper group div (label + select) if present, else the select itself
    const group = el.parentElement && el.parentElement.id.endsWith("-group")
        ? el.parentElement : el;
    group.style.display = show ? "" : "none";
}

// ── Novel / selector logic ──

function selectNovel(novelName) {
    novelTitle.textContent = novelName + " Unpacked";
    document.title = novelName + " — Literary Podcast";
    currentRuns = novels[novelName] || [];

    // Populate panel selector
    const panelMap = new Map(); // panel field → display label
    for (const run of currentRuns) {
        if (!panelMap.has(run.panel)) panelMap.set(run.panel, formatPanelLabel(run.panel));
    }
    panelSelect.innerHTML = "";
    for (const [key, label] of panelMap) {
        const opt = document.createElement("option");
        opt.value = key;
        opt.textContent = label;
        panelSelect.appendChild(opt);
    }
    showSelect(panelSelect, panelMap.size > 1);

    onPanelChange();
}

function onPanelChange() {
    const panel = panelSelect.value;
    const panelRuns = currentRuns.filter(r => r.panel === panel);
    const prevGrounding = groundingSelect.value;

    // Populate grounding for this panel
    const groundings = [...new Set(panelRuns.map(r => groundingKey(r.condition)))];
    groundingSelect.innerHTML = "";
    for (const gk of groundings) {
        const opt = document.createElement("option");
        opt.value = gk;
        opt.textContent = groundingLabel(gk);
        groundingSelect.appendChild(opt);
    }
    if (groundings.includes(prevGrounding)) groundingSelect.value = prevGrounding;
    showSelect(groundingSelect, groundings.length > 1);

    onGroundingChange(panelRuns);
}

function onGroundingChange(panelRuns) {
    if (!panelRuns) panelRuns = currentRuns.filter(r => r.panel === panelSelect.value);
    const grounding = groundingSelect.value;
    const prevHostprep = hostprepSelect.value;

    const groundedRuns = panelRuns.filter(r => groundingKey(r.condition) === grounding);
    const hostpreps = [...new Set(groundedRuns.map(r => r.hostprep))].sort();

    hostprepSelect.innerHTML = "";
    for (const hp of hostpreps) {
        const opt = document.createElement("option");
        opt.value = hp ? "prep" : "noprep";
        opt.textContent = hp ? "Prepared host" : "No host prep";
        hostprepSelect.appendChild(opt);
    }
    const available = [...hostprepSelect.options].map(o => o.value);
    if (available.includes(prevHostprep)) hostprepSelect.value = prevHostprep;
    showSelect(hostprepSelect, hostpreps.length > 1);

    onHostprepChange(groundedRuns);
}

function onHostprepChange(groundedRuns) {
    if (!groundedRuns) {
        const panel = panelSelect.value;
        const grounding = groundingSelect.value;
        groundedRuns = currentRuns.filter(r =>
            r.panel === panel && groundingKey(r.condition) === grounding
        );
    }
    const wantPrep = hostprepSelect.value === "prep";
    const match = groundedRuns.find(r => r.hostprep === wantPrep) || groundedRuns[0];
    if (match) loadRun(match.run_id);
}

async function loadRun(runId) {
    loading.style.display = "flex";
    transcript.innerHTML = "";
    segmentNav.innerHTML = "";
    openPassageTurnId = null;

    manifest = await fetch(`/api/runs/${runId}/manifest`).then(r => r.json());

    // Expert chips
    expertChips.innerHTML = "";
    for (const exp of manifest.experts) {
        const chip = document.createElement("span");
        chip.className = "expert-chip";
        chip.style.borderColor = SPEAKER_COLORS[exp.name] || "#666";
        chip.style.color = SPEAKER_COLORS[exp.name] || "#ccc";
        chip.textContent = exp.name;
        expertChips.appendChild(chip);
    }

    // Flatten turns for fast lookup
    flatTurns = [];
    for (let si = 0; si < manifest.segments.length; si++) {
        const seg = manifest.segments[si];
        for (let ti = 0; ti < seg.turns.length; ti++) {
            const turn = seg.turns[ti];
            flatTurns.push({ segIdx: si, turnIdx: ti, ...turn });
        }
    }

    // Segment nav tabs
    for (let i = 0; i < manifest.segments.length; i++) {
        const seg = manifest.segments[i];
        const btn = document.createElement("button");
        btn.className = "seg-tab";
        btn.textContent = seg.title;
        btn.dataset.segIdx = i;
        btn.addEventListener("click", () => seekToSegment(i));
        segmentNav.appendChild(btn);
    }

    renderTranscript();

    // Determine if this run has audio
    const runMeta = currentRuns.find(r => r.run_id === runId);
    const hasAudio = runMeta ? runMeta.has_audio : true;
    const playerBar = document.getElementById("player-bar");

    if (hasAudio) {
        playerBar.style.display = "";
        // Set up audio
        if (audio) { audio.pause(); audio.src = ""; }
        audio = new Audio(`/audio/${runId}/podcast.mp3`);
        audio.preload = "auto";
        audio.playbackRate = SPEEDS[speedIdx];

        seekBar.value = 0;
        timeDisplay.textContent = "0:00 / 0:00";
        currentTurnIdx = -1;
        playBtn.textContent = "\u25B6";

        audio.addEventListener("loadedmetadata", () => {
            seekBar.max = audio.duration;
            loading.style.display = "none";
        });

        audio.addEventListener("ended", () => {
            playBtn.textContent = "\u25B6";
        });

        if (audio.readyState >= 1) {
            seekBar.max = audio.duration;
            loading.style.display = "none";
        }
    } else {
        // Script-only: hide audio controls, show transcript immediately
        playerBar.style.display = "none";
        if (audio) { audio.pause(); audio.src = ""; audio = null; }
        loading.style.display = "none";
    }
}

// ── Passage helpers ──

function getPassageRefsForTurn(turn) {
    const refs = [];
    const seen = new Set();
    for (const utt of turn.utterances) {
        if (utt.passage_ref && !seen.has(utt.passage_ref)) {
            seen.add(utt.passage_ref);
            refs.push(utt.passage_ref);
        }
    }
    return refs;
}

function buildPassageRevealHTML(refs) {
    const parts = [];
    for (const ref of refs) {
        const p = manifest.passages && manifest.passages[ref];
        if (!p) continue;

        // Match quality badge for ungrounded passages
        let warning = "";
        if (p.match_category) {
            const cat = p.match_category;
            const ratio = p.match_ratio !== undefined ? Math.round(p.match_ratio * 100) : 0;
            if (cat === "verified") {
                warning = `<div class="passage-match-badge verified">Verified quote (${ratio}% match)</div>`;
            } else if (cat === "paraphrase") {
                warning = `<div class="passage-match-badge paraphrase">Likely paraphrase (${ratio}% match) — wording altered from source</div>`;
            } else {
                warning = `<div class="passage-match-badge confabulation">Probable confabulation (${ratio}% match) — no close source found</div>`;
            }
        } else if (p.suggested) {
            warning = `<div class="passage-reveal-warning">Closest match from the novel — not a source passage for this discussion</div>`;
        }

        const chNum = (p.chapter_id || "").replace("c", "");
        const chapter = chNum ? `<div class="passage-reveal-chapter">Chapter ${chNum}</div>` : "";
        const text = `<div class="passage-reveal-text">${escapeHTML(p.text)}</div>`;
        const summary = p.summary ? `<div class="passage-reveal-summary">${escapeHTML(p.summary)}</div>` : "";

        let chips = "";
        for (const c of (p.characters_present || [])) {
            chips += `<span class="passage-chip character">${escapeHTML(c)}</span>`;
        }
        for (const t of (p.themes || [])) {
            chips += `<span class="passage-chip theme">${escapeHTML(t)}</span>`;
        }
        for (const e of (p.emotional_register || [])) {
            chips += `<span class="passage-chip emotion">${escapeHTML(e)}</span>`;
        }
        const meta = chips ? `<div class="passage-reveal-meta">${chips}</div>` : "";
        parts.push(warning + chapter + text + summary + meta);
    }
    return parts.join("");
}

function escapeHTML(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function togglePassage(turnId, refs, event) {
    event.stopPropagation();

    const revealEl = document.getElementById(`passage-${turnId}`);
    const handleEl = document.getElementById(`handle-${turnId}`);
    if (!revealEl || !handleEl) return;

    if (openPassageTurnId === turnId) {
        revealEl.classList.remove("open");
        handleEl.classList.remove("open");
        openPassageTurnId = null;
        return;
    }

    if (openPassageTurnId) {
        const oldReveal = document.getElementById(`passage-${openPassageTurnId}`);
        const oldHandle = document.getElementById(`handle-${openPassageTurnId}`);
        if (oldReveal) oldReveal.classList.remove("open");
        if (oldHandle) oldHandle.classList.remove("open");
    }

    revealEl.innerHTML = buildPassageRevealHTML(refs);
    revealEl.classList.add("open");
    handleEl.classList.add("open");
    openPassageTurnId = turnId;
}

// ── Transcript rendering ──

function renderTranscript() {
    transcript.innerHTML = "";
    for (let si = 0; si < manifest.segments.length; si++) {
        const seg = manifest.segments[si];
        const header = document.createElement("div");
        header.className = "segment-header";
        header.id = `seg-${si}`;
        header.textContent = seg.title;

        // For ungrounded runs, add a segment-level suggested passages handle
        const suggestedRefs = seg.suggested_passages || [];
        if (suggestedRefs.length > 0 && manifest.passages) {
            const validRefs = suggestedRefs.filter(r => manifest.passages[r]);
            if (validRefs.length > 0) {
                const segHandleId = `seg-handle-${si}`;
                const handle = document.createElement("span");
                handle.className = "passage-handle suggested";
                handle.id = segHandleId;
                handle.innerHTML = `&#9736; ${validRefs.length} related passage${validRefs.length > 1 ? "s" : ""}`;
                handle.addEventListener("click", (e) => {
                    e.stopPropagation();
                    togglePassage(segHandleId, validRefs, e);
                });
                header.appendChild(document.createTextNode(" "));
                header.appendChild(handle);

            }
        }

        transcript.appendChild(header);

        // Reveal container for segment-level suggested passages (after header in DOM)
        if (suggestedRefs.length > 0 && manifest.passages) {
            const validRefs = suggestedRefs.filter(r => manifest.passages[r]);
            if (validRefs.length > 0) {
                const revealEl = document.createElement("div");
                revealEl.className = "passage-reveal";
                revealEl.id = `passage-seg-handle-${si}`;
                transcript.appendChild(revealEl);
            }
        }

        for (let ti = 0; ti < seg.turns.length; ti++) {
            const turn = seg.turns[ti];
            const turnId = `${si}-${ti}`;
            const el = document.createElement("div");
            el.className = "turn";
            el.id = `turn-${turnId}`;
            el.addEventListener("click", () => seekToTurn(si, ti));

            const color = SPEAKER_COLORS[turn.speaker] || "#999";
            const refs = getPassageRefsForTurn(turn);

            const speakerEl = document.createElement("div");
            speakerEl.className = "turn-speaker";
            let speakerHTML =
                `<span class="speaker-dot" style="background:${color}"></span>` +
                `<span style="color:${color}">${turn.speaker}</span>`;

            if (refs.length > 0 && manifest.passages) {
                const hasData = refs.some(r => manifest.passages[r]);
                if (hasData) {
                    // Determine worst match category in this turn's passages
                    let worstCat = "verified";
                    for (const r of refs) {
                        const p = manifest.passages[r];
                        if (p && p.match_category) {
                            if (p.match_category === "confabulation") worstCat = "confabulation";
                            else if (p.match_category === "paraphrase" && worstCat !== "confabulation") worstCat = "paraphrase";
                        }
                    }
                    const catClass = manifest.passage_source === "ungrounded" && worstCat ? ` ${worstCat}` : "";
                    const label = refs.length === 1 ? "passage" : `${refs.length} passages`;
                    speakerHTML += `<span class="passage-handle${catClass}" id="handle-${turnId}"` +
                        ` data-turn-id="${turnId}">&#9736; ${label}</span>`;
                }
            }
            speakerEl.innerHTML = speakerHTML;
            el.appendChild(speakerEl);

            if (refs.length > 0) {
                const handle = speakerEl.querySelector(".passage-handle");
                if (handle) {
                    handle.addEventListener("click", (e) => togglePassage(turnId, refs, e));
                }
            }

            const textEl = document.createElement("div");
            textEl.className = "turn-text";
            for (const utt of turn.utterances) {
                const span = document.createElement("span");
                span.className = "utterance";
                if (utt.is_quote) span.classList.add("is-quote");
                if (utt.quote_mode === "reading") {
                    span.classList.remove("is-quote");
                    span.classList.add("quote-reading");
                }
                span.textContent = utt.text + " ";
                textEl.appendChild(span);
            }
            el.appendChild(textEl);

            if (refs.length > 0 && manifest.passages && refs.some(r => manifest.passages[r])) {
                const revealEl = document.createElement("div");
                revealEl.className = "passage-reveal";
                revealEl.id = `passage-${turnId}`;
                el.appendChild(revealEl);
            }

            transcript.appendChild(el);
        }
    }
}

// ── Playback controls ──
playBtn.addEventListener("click", () => {
    if (!audio) return;
    if (audio.paused) {
        audio.play();
        playBtn.textContent = "\u275A\u275A";
    } else {
        audio.pause();
        playBtn.textContent = "\u25B6";
    }
});

seekBar.addEventListener("input", () => {
    if (!audio) return;
    audio.currentTime = parseFloat(seekBar.value);
});

speedBtn.addEventListener("click", () => {
    speedIdx = (speedIdx + 1) % SPEEDS.length;
    const speed = SPEEDS[speedIdx];
    speedBtn.textContent = speed + "x";
    if (audio) audio.playbackRate = speed;
});

function seekToSegment(segIdx) {
    if (!audio || !manifest) return;
    const seg = manifest.segments[segIdx];
    audio.currentTime = seg.start_ms / 1000;
    if (audio.paused) {
        audio.play();
        playBtn.textContent = "\u275A\u275A";
    }
}

function seekToTurn(segIdx, turnIdx) {
    if (!audio || !manifest) return;
    const turn = manifest.segments[segIdx].turns[turnIdx];
    audio.currentTime = turn.start_ms / 1000;
    if (audio.paused) {
        audio.play();
        playBtn.textContent = "\u275A\u275A";
    }
}

// ── Sync loop ──
function syncLoop() {
    if (audio && !audio.paused) {
        const ms = audio.currentTime * 1000;
        seekBar.value = audio.currentTime;
        timeDisplay.textContent = formatTime(audio.currentTime) + " / " + formatTime(audio.duration || 0);

        let newIdx = -1;
        let lo = 0, hi = flatTurns.length - 1;
        while (lo <= hi) {
            const mid = (lo + hi) >> 1;
            if (flatTurns[mid].start_ms <= ms) {
                newIdx = mid;
                lo = mid + 1;
            } else {
                hi = mid - 1;
            }
        }
        if (newIdx >= 0 && ms > flatTurns[newIdx].end_ms) {
            newIdx = -1;
        }

        if (newIdx !== currentTurnIdx) {
            updateHighlight(newIdx);
            currentTurnIdx = newIdx;
        }

        if (newIdx >= 0) {
            const activeSegIdx = flatTurns[newIdx].segIdx;
            document.querySelectorAll(".seg-tab").forEach((tab, i) => {
                tab.classList.toggle("active", i === activeSegIdx);
            });
        }
    }
    requestAnimationFrame(syncLoop);
}

function updateHighlight(newIdx) {
    document.querySelectorAll(".turn.active, .turn.past").forEach(el => {
        el.classList.remove("active", "past");
    });

    if (newIdx < 0) return;

    for (let i = 0; i < newIdx; i++) {
        const t = flatTurns[i];
        const el = document.getElementById(`turn-${t.segIdx}-${t.turnIdx}`);
        if (el) el.classList.add("past");
    }

    const active = flatTurns[newIdx];
    const activeEl = document.getElementById(`turn-${active.segIdx}-${active.turnIdx}`);
    if (activeEl) {
        activeEl.classList.add("active");
        activeEl.scrollIntoView({ behavior: "smooth", block: "center" });
    }
}

function formatTime(secs) {
    if (!secs || isNaN(secs)) return "0:00";
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return m + ":" + (s < 10 ? "0" : "") + s;
}

// ── Keyboard shortcuts ──
document.addEventListener("keydown", (e) => {
    if (!audio) return;
    if (e.code === "Space" && e.target === document.body) {
        e.preventDefault();
        playBtn.click();
    }
    if (e.code === "ArrowLeft") {
        audio.currentTime = Math.max(0, audio.currentTime - 10);
    }
    if (e.code === "ArrowRight") {
        audio.currentTime = Math.min(audio.duration, audio.currentTime + 10);
    }
});

// ── Start ──
requestAnimationFrame(syncLoop);
init();
