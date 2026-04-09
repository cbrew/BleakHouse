#!/usr/bin/env node
/**
 * Build BleakHouse MSLD 2026 poster as PowerPoint (40×30 inches)
 * Run from poster/workspace/ with: node build.js
 */
'use strict';

const sharp = require('sharp');
const pptxgen = require('pptxgenjs');
const html2pptx = require('/Users/brewc/.claude/plugins/marketplaces/anthropic-agent-skills/document-skills/pptx/scripts/html2pptx');
const fs = require('fs');
const path = require('path');

const WORKSPACE = __dirname;
const POSTER_DIR = path.join(WORKSPACE, '..');
const SCREENSHOTS = path.join(POSTER_DIR, 'screenshots');

// ─────────────────────────────────────────────────────────────────────────────
// 1. FLOW DIAGRAM SVG → PNG
// ─────────────────────────────────────────────────────────────────────────────

function makeFlowDiagramSVG() {
  // Canvas: 860×540
  // Columns: Clusters(90), Dimensions(275), Personas(555), Segments(770)
  // Node box: 100×44, rounded 6
  const W = 860, H = 580;

  // Colors
  const C = {
    gothic:  '#8B7355', legal:   '#B07D6A', char: '#7A8B5E', social: '#C4A070',
    dim:     '#7B9B6B',
    eleanor: '#D45B5B', james:   '#D4935B', caroline: '#8B6BAA', oliver: '#5BAA7B',
    opening: '#D45B5B', deep:    '#5B82AA', close: '#8B6BAA', discuss: '#AA8B5B',
    hdr:     '#5a5a5a', line:    '#888888', text: '#ffffff',
  };

  // Column x-centers
  const cx = { clusters: 90, dims: 272, personas: 555, segs: 770 };

  // Row y-centers (header at 25, nodes start at 65)
  const yc = (arr) => arr;
  const y_cl = [88, 210, 332, 454];
  const y_di = [75, 183, 291, 399, 490];
  const y_pe = [88, 210, 332, 454];
  const y_se = [88, 210, 332, 454];

  const BW = 105, BH = 44, BR = 5; // box width, height, radius

  function box(cx, cy, color, line1, line2) {
    const x = cx - BW/2, y = cy - BH/2;
    const mid = cy - (line2 ? 6 : 0);
    return `
      <rect x="${x}" y="${y}" width="${BW}" height="${BH}" rx="${BR}" fill="${color}"/>
      <text x="${cx}" y="${mid}" text-anchor="middle" dominant-baseline="middle"
            font-family="Arial" font-size="11" font-weight="bold" fill="${C.text}">${line1}</text>
      ${line2 ? `<text x="${cx}" y="${cy+8}" text-anchor="middle" dominant-baseline="middle"
            font-family="Arial" font-size="11" fill="${C.text}">${line2}</text>` : ''}`;
  }

  function hdr(cx, label) {
    return `<text x="${cx}" y="22" text-anchor="middle" font-family="Arial"
            font-size="12" font-weight="bold" fill="${C.hdr}">${label}</text>`;
  }

  function line(x1, y1, x2, y2, color) {
    return `<line x1="${x1+BW/2}" y1="${y1}" x2="${x2-BW/2}" y2="${y2}"
            stroke="${color}" stroke-width="1" stroke-opacity="0.25"/>`;
  }

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <rect width="${W}" height="${H}" fill="#fafafa"/>

  <!-- Column headers -->
  ${hdr(cx.clusters,  'Passage Clusters')}
  ${hdr(cx.dims,      'Enrichment Dimensions')}
  ${hdr(cx.personas,  'Expert Personas')}
  ${hdr(cx.segs,      'Episode Segments')}

  <!-- Connection lines: Clusters → Dimensions -->
  ${line(cx.clusters, y_cl[0], cx.dims, y_di[0], C.gothic)}
  ${line(cx.clusters, y_cl[0], cx.dims, y_di[1], C.gothic)}
  ${line(cx.clusters, y_cl[0], cx.dims, y_di[2], C.gothic)}
  ${line(cx.clusters, y_cl[1], cx.dims, y_di[1], C.legal)}
  ${line(cx.clusters, y_cl[1], cx.dims, y_di[3], C.legal)}
  ${line(cx.clusters, y_cl[2], cx.dims, y_di[2], C.char)}
  ${line(cx.clusters, y_cl[2], cx.dims, y_di[1], C.char)}
  ${line(cx.clusters, y_cl[3], cx.dims, y_di[3], C.social)}
  ${line(cx.clusters, y_cl[3], cx.dims, y_di[4], C.social)}
  ${line(cx.clusters, y_cl[3], cx.dims, y_di[2], C.social)}

  <!-- Connection lines: Dimensions → Personas -->
  ${line(cx.dims, y_di[0], cx.personas, y_pe[0], C.dim)}
  ${line(cx.dims, y_di[1], cx.personas, y_pe[0], C.dim)}
  ${line(cx.dims, y_di[1], cx.personas, y_pe[1], C.dim)}
  ${line(cx.dims, y_di[2], cx.personas, y_pe[1], C.dim)}
  ${line(cx.dims, y_di[2], cx.personas, y_pe[2], C.dim)}
  ${line(cx.dims, y_di[3], cx.personas, y_pe[1], C.dim)}
  ${line(cx.dims, y_di[3], cx.personas, y_pe[2], C.dim)}
  ${line(cx.dims, y_di[4], cx.personas, y_pe[3], C.dim)}
  ${line(cx.dims, y_di[4], cx.personas, y_pe[2], C.dim)}
  ${line(cx.dims, y_di[0], cx.personas, y_pe[2], C.dim)}

  <!-- Connection lines: Personas → Segments -->
  ${line(cx.personas, y_pe[0], cx.segs, y_se[0], C.eleanor)}
  ${line(cx.personas, y_pe[0], cx.segs, y_se[1], C.eleanor)}
  ${line(cx.personas, y_pe[1], cx.segs, y_se[1], C.james)}
  ${line(cx.personas, y_pe[1], cx.segs, y_se[2], C.james)}
  ${line(cx.personas, y_pe[2], cx.segs, y_se[2], C.caroline)}
  ${line(cx.personas, y_pe[2], cx.segs, y_se[1], C.caroline)}
  ${line(cx.personas, y_pe[3], cx.segs, y_se[3], C.oliver)}
  ${line(cx.personas, y_pe[3], cx.segs, y_se[2], C.oliver)}

  <!-- Cluster nodes -->
  ${box(cx.clusters, y_cl[0], C.gothic,  'Gothic', 'atmosphere')}
  ${box(cx.clusters, y_cl[1], C.legal,   'Legal', 'satire')}
  ${box(cx.clusters, y_cl[2], C.char,    'Character', 'crisis')}
  ${box(cx.clusters, y_cl[3], C.social,  'Social', 'critique')}

  <!-- Dimension nodes -->
  ${box(cx.dims, y_di[0], C.dim, 'atmosphere', '')}
  ${box(cx.dims, y_di[1], C.dim, 'narrative', 'technique')}
  ${box(cx.dims, y_di[2], C.dim, 'character', 'development')}
  ${box(cx.dims, y_di[3], C.dim, 'social', 'critique')}
  ${box(cx.dims, y_di[4], C.dim, 'humor', '')}

  <!-- Persona nodes -->
  ${box(cx.personas, y_pe[0], C.eleanor,  'Eleanor', '(craft)')}
  ${box(cx.personas, y_pe[1], C.james,    'James', '(history)')}
  ${box(cx.personas, y_pe[2], C.caroline, 'Caroline', '(reading)')}
  ${box(cx.personas, y_pe[3], C.oliver,   'Oliver', '(perf.)')}

  <!-- Segment nodes -->
  ${box(cx.segs, y_se[0], C.opening, 'Opening:', 'The Fog')}
  ${box(cx.segs, y_se[1], C.deep,    'Deep Dive:', "Jo's World")}
  ${box(cx.segs, y_se[2], C.close,   'Close Reading:', 'Secrets')}
  ${box(cx.segs, y_se[3], C.discuss, 'Discussion:', 'Comedy')}
</svg>`;
  return svg;
}

async function createFlowDiagramPNG() {
  const pngPath = path.join(WORKSPACE, 'flow_diagram.png');
  const svg = makeFlowDiagramSVG();
  await sharp(Buffer.from(svg))
    .resize(860, 580)
    .png()
    .toFile(pngPath);
  console.log('  ✓ flow_diagram.png');
  return pngPath;
}

// ─────────────────────────────────────────────────────────────────────────────
// 2. POSTER HTML
// ─────────────────────────────────────────────────────────────────────────────

function barRow(novel, author, pct, color) {
  const maxW = 200;  // pt
  const filledW = Math.round(pct / 57 * maxW);
  return `
  <div style="display:flex;align-items:center;gap:6pt;margin:3pt 0;">
    <div style="width:175pt;text-align:right;">
      <p style="margin:0;font-size:14pt;font-family:Georgia;font-style:italic;color:#2D2926;">${novel} <span style="font-size:12pt;color:#7A6E62;">${author}</span></p>
    </div>
    <div style="display:flex;align-items:center;gap:4pt;">
      <div style="width:${filledW}pt;height:14pt;background:${color};border-radius:2pt;"></div>
      <div style="width:${maxW - filledW}pt;height:14pt;background:#eeeeee;border-radius:2pt;"></div>
      <p style="margin:0;font-family:Courier New;font-size:14pt;color:#2D2926;">${pct}</p>
    </div>
  </div>`;
}

function dialogueTurn(color, speaker, text) {
  return `
  <div style="border-left:4pt solid ${color};background:${color}18;padding:4pt 8pt;margin:3pt 0;border-radius:0 3pt 3pt 0;">
    <p style="margin:0 0 2pt;font-size:15pt;font-family:Arial;font-weight:bold;color:${color};">${speaker}</p>
    <p style="margin:0;font-size:15pt;font-family:Georgia;font-style:italic;color:#7A6E62;">${text}</p>
  </div>`;
}

function sectionHead(title) {
  return `
  <div style="margin-bottom:6pt;">
    <p style="margin:0;font-size:26pt;font-family:Arial;font-weight:bold;color:#722F37;">${title}</p>
    <div style="height:3pt;width:140pt;background:#B8860B;margin-top:2pt;"></div>
  </div>`;
}

function subsectionHead(title) {
  return `<p style="margin:6pt 0 2pt;font-size:20pt;font-family:Arial;font-weight:bold;color:#722F37;">${title}</p>`;
}

function quoteBox(text, attribution) {
  return `
  <div style="border-left:4pt solid #B8860B;background:#F0E2C008;padding:6pt 8pt;margin:6pt 0;border-radius:0 3pt 3pt 0;">
    <p style="margin:0 0 3pt;font-size:16pt;font-family:Georgia;font-style:italic;color:#2D2926;">"${text}"</p>
    <p style="margin:0;font-size:14pt;font-family:Georgia;color:#7A6E62;">— ${attribution}</p>
  </div>`;
}

function statBox(number, label) {
  return `
  <div style="flex:1;background:#EDE5D8;border-radius:4pt;padding:8pt 4pt;text-align:center;">
    <p style="margin:0;font-size:32pt;font-family:Arial;font-weight:bold;color:#722F37;">${number}</p>
    <p style="margin:2pt 0 0;font-size:14pt;font-family:Arial;color:#7A6E62;">${label}</p>
  </div>`;
}

function sectionBox(content, style = '') {
  return `
  <div style="background:white;border:0.5pt solid #e0dada;border-radius:4pt;padding:10pt 10pt;margin-bottom:10pt;box-shadow:1pt 1pt 0 rgba(0,0,0,0.04);${style}">
    ${content}
  </div>`;
}

function createPosterHTML(diagramPng, landingPng, playerPng) {
  const diagramRelPath = path.relative(WORKSPACE, diagramPng).replace(/\\/g, '/');
  const landingRelPath = path.relative(WORKSPACE, landingPng).replace(/\\/g, '/');
  const playerRelPath = path.relative(WORKSPACE, playerPng).replace(/\\/g, '/');

  // ── Column 1 ──────────────────────────────────────────────────────────────
  const col1 = `
  ${sectionBox(`
    ${sectionHead('The Question')}
    <p style="margin:4pt 0;font-size:16pt;font-family:Georgia;font-style:italic;color:#7A6E62;">
      A reader who surveys a novel broadly and a reader who studies it narrowly will assemble different evidence. Do they arrive at different discussions?
    </p>
    <p style="margin:4pt 0;font-size:16pt;font-family:Georgia;color:#2D2926;">
      Google's NotebookLM popularised LLM-generated podcast conversations, but the conversational design is largely unexamined. What makes a multi-voice discussion cohere — sound like a genuine conversation rather than parallel monologues? What levers does a designer have, and which ones actually matter?
    </p>
    <p style="margin:4pt 0;font-size:16pt;font-family:Georgia;color:#2D2926;">
      We implement two reading strategies as passage-selection algorithms applied to <strong>15 Victorian novels</strong>, then generate structured multi-voice literary discussions from each selection.
    </p>
    <div style="display:flex;gap:8pt;margin:8pt 0;">
      ${statBox('15', 'novels')}
      ${statBox('60,774', 'passages')}
      ${statBox('180', 'conditions')}
    </div>
    <p style="margin:4pt 0;font-size:14pt;font-family:Georgia;color:#7A6E62;">
      Seven authors (Dickens, Eliot, Gaskell, Forster, Collins, Gissing, Oliphant), seven decades (1850–1924).
    </p>
    ${quoteBox('And all that night the coffin stands ready by the old portmanteau; and the lonely figure on the bed, whose path in life has lain through five and forty years, lies there with no more track behind him that any one can trace than a deserted infant.',
      'Bleak House, Ch. 11 — The death of Nemo')}
  `)}

  ${sectionBox(`
    ${sectionHead('Min-Cost Flow Selection')}
    <p style="margin:0 0 6pt;font-size:14pt;font-family:Georgia;color:#7A6E62;">
      Passages flow through enrichment dimensions and expert demand nodes to episode segments. Every arc is inspectable and adjustable.
    </p>
    <img src="${diagramRelPath}" style="width:100%;max-height:280pt;object-fit:contain;" alt="Flow diagram"/>
    ${subsectionHead('Two Reading Strategies')}
    <p style="margin:4pt 0;font-size:15pt;font-family:Georgia;color:#2D2926;">
      <strong>Synoptic</strong> (min-cost flow): <code style="font-family:Courier New;">59</code> passages from 28 chapters. Favours character development (+8.3 pp) and plot (+10.2 pp). Zero LLM tokens, &lt;1 s.
    </p>
    <p style="margin:4pt 0;font-size:15pt;font-family:Georgia;color:#2D2926;">
      <strong>Analytical</strong> (embeddings + LLM curation): <code style="font-family:Courier New;">32</code> passages from 20 chapters. Favours social critique (+13.4 pp) and thematic depth (+6.9 pp).
    </p>
    <p style="margin:4pt 0;font-size:15pt;font-family:Georgia;color:#2D2926;">
      <strong>No-passages:</strong> LLM discusses from prior knowledge alone.
    </p>
  `)}

  ${sectionBox(`
    ${sectionHead('Why Not RAG?')}
    <p style="margin:4pt 0;font-size:16pt;font-family:Georgia;color:#2D2926;">
      Standard RAG retrieves by embedding similarity and feeds results to an LLM. Effective but opaque: the user cannot see <em>why</em> a passage was selected, cannot adjust criteria, and cannot explore how different priorities reshape the output.
    </p>
    <p style="margin:4pt 0;font-size:16pt;font-family:Georgia;color:#2D2926;">
      Min-cost flow makes every decision visible as a <strong>cost</strong>, a <strong>flow</strong>, and a <strong>constraint</strong>. Solving a flow costs &lt;1 s and zero LLM tokens — a <strong>thinking tool</strong> for rapid exploration of alternatives.
    </p>
  `)}

  ${sectionBox(`
    ${sectionHead('References')}
    <p style="margin:2pt 0;font-size:14pt;font-family:Georgia;color:#2D2926;">Fish, S. (1980). <em>Is There a Text in This Class?</em> Harvard UP.</p>
    <p style="margin:2pt 0;font-size:14pt;font-family:Georgia;color:#2D2926;">Bayard, P. (2007). <em>How to Talk About Books You Haven't Read.</em> Bloomsbury.</p>
    <p style="margin:2pt 0;font-size:14pt;font-family:Georgia;color:#2D2926;">Carlini, N. et al. (2021, 2023). Extracting/quantifying memorization in LLMs. <em>USENIX Security; ICLR.</em></p>
    <p style="margin:2pt 0;font-size:14pt;font-family:Georgia;color:#2D2926;">Ahuja, R., Magnanti, T. &amp; Orlin, J. (1993). <em>Network Flows.</em> Prentice Hall.</p>
    <p style="margin:2pt 0;font-size:14pt;font-family:Georgia;color:#2D2926;">Moretti, F. (2013). <em>Distant Reading.</em> Verso.</p>
  `)}

  ${sectionBox(`
    ${subsectionHead('Interactive Demo &amp; Acknowledgements')}
    <p style="margin:4pt 0;font-size:18pt;font-family:Arial;font-weight:bold;color:#2D6B5E;">bleakhouse-demo.fly.dev</p>
    <p style="margin:2pt 0;font-size:14pt;font-family:Georgia;color:#2D2926;">Browse 180 conditions, listen to episodes, inspect passage backlinks.</p>
    <p style="margin:4pt 0;font-size:14pt;font-family:Georgia;color:#7A6E62;">Thanks to The Ohio State University College of Engineering and LexisNexis Legal &amp; Professional.</p>
  `, 'background:#EDE5D8;border-color:#c8b89a;')}
  `;

  // ── Column 2 ──────────────────────────────────────────────────────────────
  const col2 = `
  ${sectionBox(`
    ${sectionHead('The Reader Makes the Reading')}
    <p style="margin:4pt 0;font-size:16pt;font-family:Georgia;font-style:italic;color:#7A6E62;">
      The pipeline privileges expert identity at every stage — enrichment dimensions match demand profiles, the selector optimises for demand satisfaction, host preparation targets specific experts, and the script prompt reinforces perspectives. Convergence follows from this engineering.
    </p>
    <p style="margin:4pt 0;font-size:16pt;font-family:Georgia;color:#2D2926;">
      The system exposes four independently manipulable levers: <strong>expert personas</strong> (demand profiles); <strong>passage grounding</strong> (anchoring quotation and preventing confabulation); <strong>conversational design</strong> (quote handling, reactive language, turn structure); and <strong>segment continuity</strong> (bridging between independently generated segments).
    </p>
    <div style="display:flex;gap:8pt;align-items:flex-start;margin:8pt 0;">
      <div style="flex:1;background:#E0F0EC80;border:1pt solid #3D8B7A50;border-radius:4pt;padding:8pt;">
        <p style="margin:0 0 2pt;font-size:20pt;font-family:Arial;font-weight:bold;color:#2D6B5E;">Synoptic</p>
        <p style="margin:2pt 0;font-size:14pt;font-family:Georgia;color:#2D2926;"><code style="font-family:Courier New;">59</code> passages, <code style="font-family:Courier New;">28</code> chapters</p>
        <p style="margin:2pt 0;font-size:14pt;font-family:Georgia;color:#2D2926;">Character &amp; plot focused</p>
        <p style="margin:2pt 0;font-size:14pt;font-family:Georgia;color:#2D2926;">Min-cost flow solver</p>
      </div>
      <div style="flex:0 0 80pt;text-align:center;padding-top:14pt;">
        <p style="margin:0;font-size:17pt;font-family:Arial;font-weight:bold;color:#722F37;">J = 0.057</p>
        <p style="margin:2pt 0;font-size:12pt;font-family:Georgia;color:#7A6E62;">&lt;6% overlap in passages</p>
      </div>
      <div style="flex:1;background:#F0E2C080;border:1pt solid #D4A84350;border-radius:4pt;padding:8pt;">
        <p style="margin:0 0 2pt;font-size:20pt;font-family:Arial;font-weight:bold;color:#B8860B;">Analytical</p>
        <p style="margin:2pt 0;font-size:14pt;font-family:Georgia;color:#2D2926;"><code style="font-family:Courier New;">32</code> passages, <code style="font-family:Courier New;">20</code> chapters</p>
        <p style="margin:2pt 0;font-size:14pt;font-family:Georgia;color:#2D2926;">Critique &amp; theme focused</p>
        <p style="margin:2pt 0;font-size:14pt;font-family:Georgia;color:#2D2926;">Embedding retrieval + LLM</p>
      </div>
    </div>
    ${subsectionHead('Yet: Expert Airtime Stable to ±2%')}
    <p style="margin:4pt 0;font-size:15pt;font-family:Georgia;color:#2D2926;">
      Eleanor Hartley (literary critic): <strong>32–37%</strong> &nbsp;&nbsp;
      James Blackstone (social historian): <strong>30–37%</strong> &nbsp;&nbsp;
      Caroline Woodcourt (close reader): <strong>29–34%</strong>
    </p>
    <p style="margin:4pt 0;font-size:15pt;font-family:Georgia;color:#2D2926;">
      Each stage reinforces the framework. The convergence is suggestive of Fish's (1980) thesis — but the engineering is the mechanism, and we name it honestly.
    </p>
  `)}

  ${sectionBox(`
    ${sectionHead('Three Panels Discuss <em>Bleak House</em>')}
    ${subsectionHead('Literary Panel')}
    ${dialogueTurn('#722F37', 'Eleanor Hartley (Literary Critic):',
      'What strikes me about that Nemo sentence is the grammatical audacity of it. "A deserted infant" — Dickens reaches for the most helpless possible image of erasure. The infant image should be about beginning, and Dickens flips it into a closing.')}
    ${dialogueTurn('#722F37', 'James Blackstone (Social Historian):',
      'The fog is not decoration. It is the Court of Chancery made visible. "Lies there with no more track behind him that any one can trace than a deserted infant." That sentence is the whole novel compressed into a single image.')}
    ${dialogueTurn('#722F37', 'Caroline Woodcourt (Close Reader):',
      'Readers sometimes use the fog as a kind of permission — "this is a great symbolic novel, I\'m in the presence of Literature with a capital L" — and then they stop actually listening to what Dickens is telling them. What moves me is something far quieter — the moment where a human life is described as leaving no trace.')}

    ${subsectionHead('Interdisciplinary Panel')}
    ${dialogueTurn('#2D6B5E', 'Sarah Chen (NLP Scientist):',
      'That is a noun phrase with four pre-nominal modifiers, each compounded — and then "brazen-faced" pulls the floor out. The first three feel like nautical specifications — they\'re doing the register of technical competence — and the fourth is an insult.')}
    ${dialogueTurn('#2D6B5E', 'Elena Volkov (Musicologist):',
      'Institutions don\'t announce their corruption — they announce their solidity, their procedure, their continuity. I spent years studying how Soviet conservatories presented themselves as nurturing talent while systematically destroying composers who stepped out of line.')}
    ${dialogueTurn('#2D6B5E', 'Rebecca Martinez (Astronomer):',
      'The ships of Law and Equity aren\'t sunk, they\'re in reserve. In my field, we\'d say the system is in a quasi-stable state. The energy is there. Nothing has been resolved. The fog is the natural atmosphere of a system that has never actually resolved anything.')}
    <p style="margin:6pt 0 0;font-size:15pt;font-family:Georgia;color:#2D2926;">
      The experts bring their <strong>metaphors</strong> (quasi-stable states, leitmotifs, phrase structure) but not their <strong>methods</strong> — the scaffold imports literary-critical norms regardless of the persona.
    </p>

    ${subsectionHead('Alternative Panel')}
    ${dialogueTurn('#8B6030', 'Oliver Trevelyan (Actor &amp; Narrator):',
      'When I first read it aloud — really <em>performed</em> it — I remember stopping and thinking: this is incantation, not description. He builds an atmosphere so thick and particular it becomes a character in its own right.')}
    ${dialogueTurn('#8B6030', 'Daniel Rosen (Marxist Historian):',
      'The fog is doing what Chancery does throughout the novel — it penetrates everywhere, it afflicts everyone, but it does not afflict everyone equally. The ancient Greenwich pensioners wheeze by their firesides — they at least have firesides. The boy on deck has nothing between him and the weather but his own skin.')}
    ${dialogueTurn('#8B6030', 'Edmund Leigh (Moral Philosopher):',
      'One must be a little careful not to flatten the novel into a single spatial metaphor, however seductive. Dickens gives us Bleak House — the actual building — and Esther\'s description of it is one of the warmest passages in the book.')}
  `)}

  ${sectionBox(`
    ${sectionHead('Deliberate Stereotypes')}
    <p style="margin:4pt 0;font-size:16pt;font-family:Georgia;color:#2D2926;">
      The expert personas are deliberately <em>caricatures</em>: the literary critic always finds prose rhythm; the social historian always finds institutional critique; the close reader always finds texture. By making the stereotypes explicit — encoded as <strong>demand vectors</strong> rather than implicit in a prompt — the system turns editorial bias into a first-class object that can be inspected, compared, and argued about.
    </p>
  `)}

  `; // screenshots omitted from PPTX — add manually in PowerPoint

  // ── Column 3 ──────────────────────────────────────────────────────────────
  const barsHTML = [
    barRow('Middlemarch',       'Eliot',   57, '#2D6B5E'),
    barRow('Bleak House',       'Dickens', 53, '#3D8B7A'),
    barRow('David Copperfield', 'Dickens', 44, '#5BA08F'),
    barRow('Passage to India',  'Forster', 39, '#7EB5A6'),
    barRow('Cranford',          'Gaskell', 33, '#B8860B'),
    barRow('Our Mutual Friend', 'Dickens', 29, '#C8962B'),
    barRow('New Grub Street',   'Gissing', 20, '#B07D6A'),
    barRow('The Odd Women',     'Gissing',  6, '#9B4A54'),
    barRow('North and South',   'Gaskell',  2, '#722F37'),
    barRow('Hester',            'Oliphant', 0, '#4E1F26'),
    barRow('No Name',           'Collins',  0, '#4E1F26'),
  ].join('');

  const col3 = `
  ${sectionBox(`
    ${sectionHead('The Knowledge Gradient')}
    <div style="background:#E0F0EC60;border-radius:4pt;padding:8pt;margin:6pt 0;">
      <p style="margin:0;font-size:15pt;font-family:Georgia;color:#2D2926;">
        <strong style="font-size:28pt;color:#2D6B5E;">82%</strong> of invented quotes draw 90–100% of their words from the novel's own vocabulary. Mean overlap: 95.1%.
      </p>
    </div>
    <p style="margin:4pt 0;font-size:16pt;font-family:Georgia;font-style:italic;color:#7A6E62;">Without passage grounding, the LLM produces graduated pastiche — not hallucination. Fidelity tracks novel prominence.</p>
    ${subsectionHead('Ungrounded Quote Verification (%)')}
    ${barsHTML}
    <p style="margin:6pt 0 0;font-size:14pt;font-family:Georgia;color:#2D2926;">
      Grounded conditions achieve <strong>97–98%</strong> for <em>all</em> novels. The gradient reflects analytical reinforcement in training data (Carlini et al., 2021, 2023), not prose style.
    </p>
  `)}

  ${sectionBox(`
    ${sectionHead('Pastiche in Action')}
    ${quoteBox(
      'Name, Jo. Nothing else that he knows on. Don\'t know that everybody has two names. Never heerd of sich a think. No father, no mother, no friends. Never been to school.',
      'Bleak House, Ch. 11 — Jo\'s testimony')}
    <div style="background:#E0F0EC40;border:0.5pt solid #3D8B7A30;border-radius:3pt;padding:4pt 8pt;margin:4pt 0;">
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <p style="margin:0;font-size:14pt;font-family:Georgia;font-style:italic;color:#2D2926;">"Fog everywhere. Fog up the river…"</p>
        <div style="background:#2D6B5E;border-radius:3pt;padding:2pt 6pt;">
          <p style="margin:0;font-size:12pt;font-family:Arial;font-weight:bold;color:white;">Verified 100%</p>
        </div>
      </div>
      <p style="margin:2pt 0 0;font-size:12pt;font-family:Georgia;color:#7A6E62;">Reproduced verbatim from LLM memory</p>
    </div>
    <div style="background:#72003710;border:0.5pt solid #72003720;border-radius:3pt;padding:4pt 8pt;margin:4pt 0;">
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <p style="margin:0;font-size:14pt;font-family:Georgia;font-style:italic;color:#2D2926;">"I am very weak, but I shall begin the world."</p>
        <div style="background:#9B4A54;border-radius:3pt;padding:2pt 6pt;">
          <p style="margin:0;font-size:12pt;font-family:Arial;font-weight:bold;color:white;">Invented · 100% vocab</p>
        </div>
      </div>
      <p style="margin:2pt 0 0;font-size:12pt;font-family:Georgia;color:#7A6E62;">Every word appears in the novel, but this sentence does not exist</p>
    </div>
    <div style="background:#72003710;border:0.5pt solid #72003720;border-radius:3pt;padding:4pt 8pt;margin:4pt 0;">
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <p style="margin:0;font-size:14pt;font-family:Georgia;font-style:italic;color:#2D2926;">"I don't know nothink."</p>
        <div style="background:#9B4A54;border-radius:3pt;padding:2pt 6pt;">
          <p style="margin:0;font-size:12pt;font-family:Arial;font-weight:bold;color:white;">Invented · 80% vocab</p>
        </div>
      </div>
      <p style="margin:2pt 0 0;font-size:12pt;font-family:Georgia;color:#7A6E62;">Jo's dialect remembered; phrasing reconstructed</p>
    </div>
  `)}

  ${sectionBox(`
    ${sectionHead('Alternative Expert Panels')}
    <p style="margin:4pt 0;font-size:15pt;font-family:Georgia;color:#2D2926;">
      Beyond the primary literary triumvirate (Hartley / Blackstone / Woodcourt), the system includes three further specialist personas with distinct analytical toolkits.
    </p>
    <div style="display:flex;gap:6pt;margin:6pt 0;">
      <div style="flex:1;background:#8B735508;border-left:3pt solid #8B7355;border-radius:0 3pt 3pt 0;padding:5pt 7pt;">
        <p style="margin:0 0 2pt;font-size:18pt;font-family:Arial;font-weight:bold;color:#8B7355;">Edmund Leigh</p>
        <p style="margin:0 0 4pt;font-size:13pt;font-family:Arial;color:#7A6E62;">Moral Philosopher</p>
        <p style="margin:0;font-size:14pt;font-family:Georgia;font-style:italic;color:#2D2926;">"Skimpole is the finest comic villain in the book, and I use that term with some precision. He is not a villain by malice — he is a villain by abdication."</p>
      </div>
      <div style="flex:1;background:#5B82AA08;border-left:3pt solid #5B82AA;border-radius:0 3pt 3pt 0;padding:5pt 7pt;">
        <p style="margin:0 0 2pt;font-size:18pt;font-family:Arial;font-weight:bold;color:#5B82AA;">Oliver Trevelyan</p>
        <p style="margin:0 0 4pt;font-size:13pt;font-family:Arial;color:#7A6E62;">Actor &amp; Narrator</p>
        <p style="margin:0;font-size:14pt;font-family:Georgia;font-style:italic;color:#2D2926;">"That phrase — 'forsworn and abjured' — is extraordinary to read aloud. Those are legal words — the language of the court itself — turned against the court."</p>
      </div>
      <div style="flex:1;background:#C4A07008;border-left:3pt solid #C4A070;border-radius:0 3pt 3pt 0;padding:5pt 7pt;">
        <p style="margin:0 0 2pt;font-size:18pt;font-family:Arial;font-weight:bold;color:#8B6030;">Daniel Rosen</p>
        <p style="margin:0 0 4pt;font-size:13pt;font-family:Arial;color:#7A6E62;">Marxist Historian</p>
        <p style="margin:0;font-size:14pt;font-family:Georgia;font-style:italic;color:#2D2926;">"The darkness in that scene is the shadow of an institution, not just a weather event. Chancery casts its darkness across every threshold in this novel."</p>
      </div>
    </div>
    <p style="margin:4pt 0;font-size:14pt;font-family:Georgia;color:#7A6E62;">
      Each persona defines a distinct <strong>demand vector</strong> — a formal encoding of what that expert will seek in any passage. The system supports all 3<sup>3</sup> = 27 panel combinations; 9 are produced across the 180 conditions in this study.
    </p>
  `)}

  ${sectionBox(`
    ${sectionHead('Designed Cordiality')}
    <p style="margin:4pt 0;font-size:15pt;font-family:Georgia;font-style:italic;color:#7A6E62;">
      The prompt instructs experts to be agreeable. The result is a recognisable formula: deferential opener, immediate contradiction.
    </p>
    <div style="background:#f0f0f0;border-left:4pt solid #888;padding:5pt 8pt;margin:5pt 0;border-radius:0 3pt 3pt 0;">
      <p style="margin:0 0 3pt;font-size:13pt;font-family:Arial;font-style:italic;color:#666;">From the script prompt:</p>
      <p style="margin:0;font-size:14pt;font-family:Courier New;color:#333;">Experts react to each other: <strong>agree</strong>, <strong>push back gently</strong>, riff on each other's ideas.</p>
    </div>
    <p style="margin:5pt 0 3pt;font-size:14pt;font-family:Georgia;color:#2D2926;">The resulting formula, across all 15 novels and all panels:</p>
    ${dialogueTurn('#8B7355', 'Edmund Leigh (arc_v21, Bleak House):',
      '"<strong>I don\'t dispute any of that</strong> — and James\'s contextual detail is, as always, illuminating. <strong>But</strong> I\'d want to resist the temptation to read Bleak House primarily as a pamphlet dressed in fiction\'s clothing."')}
    ${dialogueTurn('#722F37', 'Eleanor Hartley (ext_v01, Bleak House):',
      '"<strong>I wouldn\'t dispute any of that</strong> — <strong>but</strong> I\'d add a layer, because \'deserted infant\' is not merely a figure of speech."')}
    ${dialogueTurn('#2D6B5E', 'Caroline Woodcourt (cran_nop, Cranford):',
      '"<strong>I wouldn\'t dispute that</strong> reading of the prose. <strong>But</strong>…"')}
    <p style="margin:5pt 0 0;font-size:14pt;font-family:Georgia;color:#2D2926;">
      The opener is disingenuous: the speaker always does dispute it. The formula is prompt-compliance made visible — <em>push back gently</em> produces stylised deference that is recognisable as designed, not conversational.
    </p>
  `)}

  ${sectionBox(`
    ${sectionHead('Key Findings')}
    <div style="background:#72003710;border-left:4pt solid #722F37;border-radius:0 3pt 3pt 0;padding:6pt 8pt;margin:5pt 0;">
      <p style="margin:0 0 2pt;font-size:16pt;font-family:Arial;font-weight:bold;color:#722F37;">1. Framework dominates strategy.</p>
      <p style="margin:0;font-size:15pt;font-family:Georgia;color:#2D2926;">Two reading algorithms select &lt;6% overlapping passages yet produce discussions with identical expert airtime (±2%). This convergence follows from a pipeline that reinforces expert identity at every stage — suggestive of Fish's thesis, but the engineering is the mechanism.</p>
    </div>
    <div style="background:#2D6B5E10;border-left:4pt solid #2D6B5E;border-radius:0 3pt 3pt 0;padding:6pt 8pt;margin:5pt 0;">
      <p style="margin:0 0 2pt;font-size:16pt;font-family:Arial;font-weight:bold;color:#2D6B5E;">2. Pastiche, not hallucination.</p>
      <p style="margin:0;font-size:15pt;font-family:Georgia;color:#2D2926;">Ungrounded LLMs write <em>in the style of</em> a novel, not <em>from</em> it. Fidelity tracks training-data exposure: a measurable knowledge gradient from <em>Middlemarch</em> (57%) to <em>Hester</em> (0%).</p>
    </div>
    <div style="background:#B8860B10;border-left:4pt solid #B8860B;border-radius:0 3pt 3pt 0;padding:6pt 8pt;margin:5pt 0;">
      <p style="margin:0 0 2pt;font-size:16pt;font-family:Arial;font-weight:bold;color:#B8860B;">3. Scaffolding is content-independent.</p>
      <p style="margin:0;font-size:15pt;font-family:Georgia;color:#2D2926;">Host preparation raises questions from ~1 to ~11 per segment, uniformly across all 15 novels (5.3× to 14.1×). Dynamics are designed, not emergent.</p>
    </div>
    <div style="background:#8B603010;border-left:4pt solid #8B6030;border-radius:0 3pt 3pt 0;padding:6pt 8pt;margin:5pt 0;">
      <p style="margin:0 0 2pt;font-size:16pt;font-family:Arial;font-weight:bold;color:#8B6030;">4. Cordiality is designed, not conversational.</p>
      <p style="margin:0;font-size:15pt;font-family:Georgia;color:#2D2926;">The prompt instruction <em>push back gently</em> produces a recognisable formula across all panels and all 15 novels: deferential opener ("I wouldn't dispute that…") followed immediately by contradiction. The deference is disingenuous and measurably prompt-driven.</p>
    </div>
    <div style="background:#72003710;border:1pt solid #72003730;border-radius:4pt;padding:8pt;margin:8pt 0 0;">
      <p style="margin:0 0 3pt;font-size:18pt;font-family:Arial;font-weight:bold;color:#722F37;">Framework &gt; Grounding &gt; Strategy</p>
      <p style="margin:0;font-size:15pt;font-family:Georgia;color:#2D2926;">The decomposition has a clear hierarchy. Framework determines character, grounding gates accuracy, strategy is surprisingly irrelevant.</p>
    </div>
  `)}
  `;

  // ── Full HTML ─────────────────────────────────────────────────────────────
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
html { background: #F5F0E6; }
* { box-sizing: border-box; }
body {
  width: 2880pt; height: 2160pt; margin: 0; padding: 0;
  background: #F5F0E6; font-family: Georgia, serif;
  display: flex; flex-direction: column;
}
.header {
  background: #4E1F26;
  padding: 16pt 22pt 14pt;
  border-radius: 4pt;
  margin: 14pt 14pt 6pt;
  display: flex; align-items: center; gap: 20pt;
}
.header-left { flex: 1; }
.header-right { text-align: right; flex: 0 0 370pt; }
.epigraph {
  border-left: 4pt solid #B8860B;
  background: #EDE5D8;
  padding: 8pt 14pt;
  margin: 0 14pt 8pt;
  border-radius: 0 4pt 4pt 0;
}
.columns {
  display: flex; gap: 10pt; flex: 1;
  padding: 0 14pt 14pt;
  align-items: flex-start;
}
.col { flex: 1; min-width: 0; }
.col2 { flex: 1.27; }
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
  <div class="header-left">
    <p style="margin:0;font-size:54pt;font-family:Arial;font-weight:bold;font-style:italic;color:#F5F0E6;">Not In Our Time: Transport-Based Content Selection</p>
    <p style="margin:4pt 0 0;font-size:20pt;font-family:Arial;color:#D4A843;">An Inspectable, Manipulable Alternative to RAG — Demonstrated on Literary Discussion Podcasts for 15 Victorian Novels</p>
  </div>
  <div class="header-right">
    <p style="margin:0;font-size:22pt;font-family:Arial;font-weight:bold;color:#F5F0E6;">Chris Brew</p>
    <p style="margin:3pt 0 0;font-size:18pt;font-family:Arial;color:#F0E2C0;">The Ohio State University<br>LexisNexis Legal &amp; Professional</p>
    <div style="margin-top:8pt;border:1pt solid #D4A843;padding:4pt 10pt;border-radius:2pt;display:inline-block;">
      <p style="margin:0;font-size:13pt;font-family:Arial;color:#D4A843;">MIDWEST SPEECH &amp; LANGUAGE DAY 2026</p>
    </div>
  </div>
</div>

<!-- EPIGRAPH -->
<div class="epigraph">
  <p style="margin:0;font-size:17pt;font-family:Georgia;font-style:italic;color:#2D2926;">
    "Fog everywhere. Fog up the river, where it flows among green aits and meadows; fog down the river, where it rolls defiled among the tiers of shipping and the waterside pollutions of a great (and dirty) city. Fog on the Essex marshes, fog on the Kentish heights."
    <span style="font-style:normal;color:#7A6E62;font-size:15pt;"> — Charles Dickens, Bleak House (1853), Chapter 1</span>
  </p>
</div>

<!-- THREE COLUMNS -->
<div class="columns">
  <div class="col">${col1}</div>
  <div class="col col2">${col2}</div>
  <div class="col">${col3}</div>
</div>

</body>
</html>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// 3. BUILD PPTX
// ─────────────────────────────────────────────────────────────────────────────

async function buildPPTX(htmlPath) {
  const pptx = new pptxgen();

  // 40×30 inch custom layout
  pptx.defineLayout({ name: 'POSTER_40x30', width: 40, height: 30 });
  pptx.layout = 'POSTER_40x30';

  // html2pptx takes (htmlFile, presObject, options) — pptx is the presentation object
  // It creates the slide internally via pres.addSlide()
  await html2pptx(htmlPath, pptx);

  const outPath = path.join(POSTER_DIR, 'poster.pptx');
  await pptx.writeFile({ fileName: outPath });
  console.log(`  ✓ poster.pptx → ${outPath}`);
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN
// ─────────────────────────────────────────────────────────────────────────────

async function main() {
  console.log('Building BleakHouse MSLD 2026 poster…');

  // 1. Flow diagram PNG
  console.log('Step 1: Creating flow diagram…');
  const diagramPng = await createFlowDiagramPNG();

  // 2. Poster HTML
  console.log('Step 2: Writing poster.html…');
  const landingPng = path.join(SCREENSHOTS, 'landing_page.png');
  const playerPng  = path.join(SCREENSHOTS, 'audio_player.png');
  const htmlContent = createPosterHTML(diagramPng, landingPng, playerPng);
  const htmlPath = path.join(WORKSPACE, 'poster.html');
  fs.writeFileSync(htmlPath, htmlContent, 'utf8');
  console.log('  ✓ poster.html');

  // 3. Build PPTX
  console.log('Step 3: Converting to PowerPoint…');
  await buildPPTX(htmlPath);

  console.log('\nDone! Output: poster/poster.pptx');
}

main().catch(err => { console.error(err); process.exit(1); });
