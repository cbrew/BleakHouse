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
let manifest = null;
let flatTurns = [];
let audio = null;
let currentTurnIdx = -1;
let speedIdx = 1;
let openPassageTurnId = null;
let currentRunId = null;
let audioState = null;  // "gemini" or "kokoro"
let kokoroSegAudio = null;  // per-segment Audio element for kokoro mode
let kokoroSegIdx = -1;

// ── DOM refs ──
const novelTitle   = document.getElementById("novel-title");
const novelSelect  = document.getElementById("novel-select");
const runSelect    = document.getElementById("run-select");
const expertChips  = document.getElementById("expert-chips");
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

    novels = await fetch("/api/all-runs").then(r => r.json());
    const novelNames = Object.keys(novels);

    if (directRun) {
        // Hide selectors, load directly
        novelSelect.style.display = "none";
        runSelect.style.display = "none";
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
    selectNovel(novelNames[0]);
}

function selectNovel(novelName) {
    novelTitle.textContent = novelName + " Unpacked";
    document.title = novelName + " — Literary Podcast";

    const runs = novels[novelName] || [];
    runSelect.innerHTML = "";
    for (const run of runs) {
        const opt = document.createElement("option");
        opt.value = run.run_id;
        const mins = Math.round(run.total_duration_ms / 60000);
        const names = run.experts.map(e => e.name).join(", ");
        const cond = run.condition ? ` [${run.condition}]` : "";
        const hp = run.hostprep ? " +hostprep" : "";
        const audioTag = run.audio_state === 'gemini' ? ' ♫' : ' ⚡';
        opt.textContent = `${names}${cond}${hp}${audioTag}`;
        runSelect.appendChild(opt);
    }
    runSelect.onchange = () => loadRun(runSelect.value);
    if (runs.length > 0) {
        loadRun(runs[0].run_id);
    }
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
        btn.addEventListener("click", () => {
            if (audioState === 'gemini') {
                seekToSegment(i);
            } else {
                playKokoroSegment(i);
            }
        });
        segmentNav.appendChild(btn);
    }

    // Determine audio state from the run info
    currentRunId = runId;
    audioState = null;
    for (const runs of Object.values(novels)) {
        const run = runs.find(r => r.run_id === runId);
        if (run) { audioState = run.audio_state || 'kokoro'; break; }
    }

    renderTranscript();

    // Set up audio based on state
    if (audio) { audio.pause(); audio.src = ""; }
    if (kokoroSegAudio) { kokoroSegAudio.pause(); kokoroSegAudio.src = ""; }
    kokoroSegIdx = -1;

    if (audioState === 'gemini') {
        // Full pre-rendered audio
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
        // Kokoro on-demand: no full audio, per-segment rendering
        audio = null;
        loading.style.display = "none";
        timeDisplay.textContent = "On-demand audio";
        playBtn.textContent = "\u25B6";
    }
}

// ── Kokoro per-segment playback ──
async function playKokoroSegment(segIdx) {
    if (kokoroSegAudio) { kokoroSegAudio.pause(); }
    kokoroSegIdx = segIdx;

    const tabs = segmentNav.querySelectorAll('.seg-tab');
    const segTitle = manifest.segments[segIdx].title;

    // Check if already cached
    const statusResp = await fetch(`/api/tts/${currentRunId}/${segIdx}/status`).then(r => r.json());
    if (statusResp.status === 'ready') {
        // Already rendered — play immediately
        kokoroSegAudio = new Audio(`/api/tts/${currentRunId}/${segIdx}`);
        kokoroSegAudio.playbackRate = SPEEDS[speedIdx];
        kokoroSegAudio.addEventListener('canplay', () => {
            if (tabs[segIdx]) tabs[segIdx].textContent = segTitle + ' 🔊';
            kokoroSegAudio.play();
            playBtn.textContent = "\u23F8";
        });
        kokoroSegAudio.addEventListener('ended', () => {
            playBtn.textContent = "\u25B6";
            if (tabs[segIdx]) tabs[segIdx].textContent = segTitle + ' ✓';
            if (segIdx + 1 < manifest.segments.length) playKokoroSegment(segIdx + 1);
        });
        kokoroSegAudio.load();
        return;
    }

    // Not cached — start rendering with progress polling
    if (tabs[segIdx]) tabs[segIdx].textContent = segTitle + ' ⏳ 0%';

    // Start the render (non-blocking — browser will wait for response)
    const audioPromise = fetch(`/api/tts/${currentRunId}/${segIdx}`);

    // Poll progress
    const pollInterval = setInterval(async () => {
        try {
            const prog = await fetch(`/api/tts/${currentRunId}/${segIdx}/status`).then(r => r.json());
            if (prog.status === 'rendering' && prog.total > 0) {
                const pct = Math.round(prog.done / prog.total * 100);
                if (tabs[segIdx]) tabs[segIdx].textContent = segTitle + ` ⏳ ${pct}%`;
            } else if (prog.status === 'ready') {
                clearInterval(pollInterval);
            }
        } catch (e) {}
    }, 2000);

    // Wait for audio to be ready
    try {
        const resp = await audioPromise;
        clearInterval(pollInterval);
        if (!resp.ok) {
            if (tabs[segIdx]) tabs[segIdx].textContent = segTitle + ' ❌';
            return;
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        kokoroSegAudio = new Audio(url);
        kokoroSegAudio.playbackRate = SPEEDS[speedIdx];
        if (tabs[segIdx]) tabs[segIdx].textContent = segTitle + ' 🔊';
        kokoroSegAudio.play();
        playBtn.textContent = "\u23F8";
        kokoroSegAudio.addEventListener('ended', () => {
            playBtn.textContent = "\u25B6";
            if (tabs[segIdx]) tabs[segIdx].textContent = segTitle + ' ✓';
            URL.revokeObjectURL(url);
            if (segIdx + 1 < manifest.segments.length) playKokoroSegment(segIdx + 1);
        });
    } catch (e) {
        clearInterval(pollInterval);
        if (tabs[segIdx]) tabs[segIdx].textContent = segTitle + ' ❌';
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
    if (audioState === 'kokoro') {
        // For Kokoro: play/pause current segment, or start from segment 0
        if (kokoroSegAudio && !kokoroSegAudio.paused) {
            kokoroSegAudio.pause();
            playBtn.textContent = "\u25B6";
        } else if (kokoroSegAudio && kokoroSegAudio.src) {
            kokoroSegAudio.play();
            playBtn.textContent = "\u23F8";
        } else {
            playKokoroSegment(0);
        }
        return;
    }
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
