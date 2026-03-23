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

let manifest = null;
let flatTurns = [];
let audio = null;
let currentTurnIdx = -1;
let speedIdx = 1;
let openPassageTurnId = null; // which turn's passage is currently expanded

// ── DOM refs ──
const runSelect   = document.getElementById("run-select");
const expertChips = document.getElementById("expert-chips");
const playBtn     = document.getElementById("play-btn");
const seekBar     = document.getElementById("seek-bar");
const timeDisplay = document.getElementById("time-display");
const speedBtn    = document.getElementById("speed-btn");
const segmentNav  = document.getElementById("segment-nav");
const transcript  = document.getElementById("transcript");
const loading     = document.getElementById("loading");

// ── Init ──
async function init() {
    const runs = await fetch("/api/runs").then(r => r.json());
    if (runs.length === 0) {
        loading.textContent = "No podcast runs with audio found.";
        return;
    }
    runSelect.innerHTML = "";
    for (const run of runs) {
        const opt = document.createElement("option");
        opt.value = run.run_id;
        const mins = Math.round(run.total_duration_ms / 60000);
        const names = run.experts.map(e => e.name).join(", ");
        opt.textContent = `${run.run_id} (${mins}m) — ${names}`;
        runSelect.appendChild(opt);
    }
    runSelect.addEventListener("change", () => loadRun(runSelect.value));
    loadRun(runs[0].run_id);
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
}

// ── Passage helpers ──

function getPassageRefsForTurn(turn) {
    // Collect unique passage refs in order from this turn's utterances
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

        parts.push(chapter + text + summary + meta);
    }
    return parts.join("");
}

function escapeHTML(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function togglePassage(turnId, refs, event) {
    event.stopPropagation(); // don't trigger the turn click (seek)

    const revealEl = document.getElementById(`passage-${turnId}`);
    const handleEl = document.getElementById(`handle-${turnId}`);
    if (!revealEl || !handleEl) return;

    // If this one is already open, close it
    if (openPassageTurnId === turnId) {
        revealEl.classList.remove("open");
        handleEl.classList.remove("open");
        openPassageTurnId = null;
        return;
    }

    // Close any previously open passage
    if (openPassageTurnId) {
        const oldReveal = document.getElementById(`passage-${openPassageTurnId}`);
        const oldHandle = document.getElementById(`handle-${openPassageTurnId}`);
        if (oldReveal) oldReveal.classList.remove("open");
        if (oldHandle) oldHandle.classList.remove("open");
    }

    // Open this one
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
        transcript.appendChild(header);

        for (let ti = 0; ti < seg.turns.length; ti++) {
            const turn = seg.turns[ti];
            const turnId = `${si}-${ti}`;
            const el = document.createElement("div");
            el.className = "turn";
            el.id = `turn-${turnId}`;
            el.addEventListener("click", () => seekToTurn(si, ti));

            const color = SPEAKER_COLORS[turn.speaker] || "#999";
            const refs = getPassageRefsForTurn(turn);

            // Speaker line with optional passage handle
            const speakerEl = document.createElement("div");
            speakerEl.className = "turn-speaker";
            let speakerHTML =
                `<span class="speaker-dot" style="background:${color}"></span>` +
                `<span style="color:${color}">${turn.speaker}</span>`;

            if (refs.length > 0 && manifest.passages) {
                // Only show handle if we actually have passage data for at least one ref
                const hasData = refs.some(r => manifest.passages[r]);
                if (hasData) {
                    const label = refs.length === 1 ? "passage" : `${refs.length} passages`;
                    speakerHTML += `<span class="passage-handle" id="handle-${turnId}"` +
                        ` data-turn-id="${turnId}">&#9736; ${label}</span>`;
                }
            }
            speakerEl.innerHTML = speakerHTML;
            el.appendChild(speakerEl);

            // Attach handle click handler
            if (refs.length > 0) {
                const handle = speakerEl.querySelector(".passage-handle");
                if (handle) {
                    handle.addEventListener("click", (e) => togglePassage(turnId, refs, e));
                }
            }

            // Utterance text
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

            // Passage reveal container (hidden by default)
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

        // Find active turn via binary search
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

        // Update segment nav
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
