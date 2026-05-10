// Phase C: shards-mode audio player + click-to-seek + highlight.
//
// Reads /audio/<run_id>/shards.json (built server-side from content.db,
// each shard carries its R2 url) and plays shards back-to-back via
// the <audio> element. Audio bytes bypass the server entirely — the
// browser fetches mp3s directly from R2.
//
// Click any .turn[data-segment-idx][data-turn-idx] to seek to that
// turn. The current shard's matching turn gets .turn-current; on
// shard advance the current turn auto-scrolls into view (only while
// playing). Speed cycles 0.75 / 1.0 / 1.25 / 1.5 / 2.0 and persists
// in localStorage.
//
// Pure ES module; no framework. ~150 lines including comments.

(function () {
    "use strict";

    const SPEEDS = [0.75, 1.0, 1.25, 1.5, 2.0];
    const SPEED_KEY = "niot:speedIdx";

    const transcript = document.querySelector(".transcript");
    if (!transcript) return;
    const runId = transcript.dataset.runId;
    if (!runId) return;

    const audio       = document.getElementById("player-audio");
    const playBtn     = document.getElementById("player-play");
    const speedBtn    = document.getElementById("player-speed");
    const counterEl   = document.getElementById("player-counter");
    const progressEl  = document.getElementById("player-progress");
    if (!audio || !playBtn || !speedBtn || !counterEl || !progressEl) return;

    let shards = [];
    let cursor = -1;
    let prefetch = null;
    let speedIdx = 1;

    // ── Speed (persisted) ──
    const saved = parseInt(localStorage.getItem(SPEED_KEY) || "1", 10);
    if (!Number.isNaN(saved) && saved >= 0 && saved < SPEEDS.length) {
        speedIdx = saved;
    }
    audio.playbackRate = SPEEDS[speedIdx];
    speedBtn.textContent = SPEEDS[speedIdx] + "×";

    // ── Init ──
    init().catch((err) => {
        console.error("player init failed:", err);
        counterEl.textContent = "Audio error";
    });

    async function init() {
        const resp = await fetch("/audio/" + encodeURIComponent(runId) + "/shards.json");
        if (!resp.ok) {
            counterEl.textContent = resp.status === 404
                ? "Audio unavailable"
                : "Audio error";
            return;
        }
        const data = await resp.json();
        shards = (data.shards || []).filter((s) => s.url);
        if (shards.length === 0) {
            counterEl.textContent = "No audio";
            return;
        }
        wireControls();
        wireTurnClicks();
        loadShard(0, /*autoplay=*/false);
    }

    // ── Shard loading + prefetch ──
    function loadShard(idx, autoplay) {
        if (idx < 0 || idx >= shards.length) return;
        cursor = idx;
        audio.src = shards[idx].url;
        if (autoplay) audio.play().catch(() => {});
        updateUI();
        prefetchNext();
    }

    function prefetchNext() {
        const next = shards[cursor + 1];
        if (!next) return;
        if (prefetch) prefetch.src = "";
        prefetch = new Audio();
        prefetch.preload = "auto";
        prefetch.src = next.url;
    }

    // ── UI sync ──
    function updateUI() {
        const shard = shards[cursor];
        counterEl.textContent = "Shard " + (cursor + 1) + " of " + shards.length;
        document.querySelectorAll(".turn-current").forEach((el) => {
            el.classList.remove("turn-current");
        });
        if (shard.kind !== "turn") return;
        const sel =
            '.turn[data-segment-idx="' + shard.segment_index +
            '"][data-turn-idx="' + shard.turn_index + '"]';
        const turnEl = transcript.querySelector(sel);
        if (!turnEl) return;
        turnEl.classList.add("turn-current");
        if (!audio.paused) {
            const rect = turnEl.getBoundingClientRect();
            const inView = rect.top >= 0 && rect.bottom <= window.innerHeight;
            if (!inView) {
                turnEl.scrollIntoView({ behavior: "smooth", block: "center" });
            }
        }
    }

    function updateProgress() {
        if (!audio.duration || !isFinite(audio.duration)) {
            progressEl.style.width = "0%";
            return;
        }
        progressEl.style.width = ((audio.currentTime / audio.duration) * 100) + "%";
    }

    // ── Controls ──
    function wireControls() {
        playBtn.addEventListener("click", togglePlay);
        speedBtn.addEventListener("click", cycleSpeed);
        audio.addEventListener("ended", () => {
            if (cursor + 1 < shards.length) {
                loadShard(cursor + 1, /*autoplay=*/true);
            } else {
                playBtn.textContent = "Play";
            }
        });
        audio.addEventListener("play",  () => { playBtn.textContent = "Pause"; });
        audio.addEventListener("pause", () => { playBtn.textContent = "Play"; });
        audio.addEventListener("timeupdate", updateProgress);
        document.addEventListener("keydown", (e) => {
            if (e.code !== "Space") return;
            const tag = (e.target && e.target.tagName) || "";
            if (tag === "INPUT" || tag === "TEXTAREA") return;
            e.preventDefault();
            togglePlay();
        });
    }

    function wireTurnClicks() {
        transcript.addEventListener("click", (e) => {
            const turnEl = e.target.closest(".turn[data-segment-idx][data-turn-idx]");
            if (!turnEl) return;
            const segIdx  = parseInt(turnEl.dataset.segmentIdx, 10);
            const turnIdx = parseInt(turnEl.dataset.turnIdx, 10);
            const idx = shards.findIndex((s) =>
                s.kind === "turn" &&
                s.segment_index === segIdx &&
                s.turn_index === turnIdx
            );
            if (idx >= 0) loadShard(idx, /*autoplay=*/true);
        });
    }

    function togglePlay() {
        if (audio.paused) audio.play().catch(() => {});
        else audio.pause();
    }

    function cycleSpeed() {
        speedIdx = (speedIdx + 1) % SPEEDS.length;
        audio.playbackRate = SPEEDS[speedIdx];
        speedBtn.textContent = SPEEDS[speedIdx] + "×";
        localStorage.setItem(SPEED_KEY, String(speedIdx));
    }
})();

// ── Passage reveal toggle (Phase D) ──
//
// Each passage-ref button has hx-get pointing at /reveal/<run>/<ref>
// and hx-target="next .reveal-slot". On first click, htmx fetches the
// fragment and fills the slot. On second click, this listener
// preempts htmx's request and clears the slot — turning the
// fetch-once button into a toggle.
//
// Uses htmx:beforeRequest so we cancel cleanly via evt.preventDefault
// without racing htmx's own click handler.
document.addEventListener("htmx:beforeRequest", (evt) => {
    const btn = evt.detail.elt;
    if (!btn || !btn.matches || !btn.matches("button.passage-ref")) return;
    const utt = btn.closest(".utterance");
    const slot = utt && utt.nextElementSibling;
    if (!slot || !slot.classList.contains("reveal-slot")) return;
    if (slot.children.length > 0) {
        evt.preventDefault();
        slot.innerHTML = "";
    }
});

