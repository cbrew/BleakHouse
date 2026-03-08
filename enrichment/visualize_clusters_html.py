"""Generate interactive HTML visualizations of literary and character clusters.

Produces two standalone HTML files with Plotly scatter plots, click-to-inspect
sidebars, and cluster profile summary tables:

  reports/clusters_literary_<tag>.html
  reports/clusters_characters_<tag>.html

Usage:
    uv run python -m enrichment.visualize_clusters_html
"""

import html
import json
import logging
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import umap  # pyright: ignore[reportMissingImports]
from dotenv import load_dotenv
from scipy.sparse import csr_matrix
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")
PASSAGES_PATH = DATA_DIR / "passages_enriched.json"
LITERARY_CLUSTERS_PATH = DATA_DIR / "clusters_literary.json"
CHAR_CLUSTERS_PATH = DATA_DIR / "clusters_characters.json"
ARCS_PATH = DATA_DIR / "character_arcs.json"

# Literary feature constants (must match cluster_literary.py)
PLOT_FUNCTIONS = [
    "action",
    "dialogue",
    "description",
    "exposition",
    "transition",
    "digression",
    "climax",
    "revelation",
]
EMOTIONAL_REGISTERS = [
    "comic",
    "tragic",
    "suspenseful",
    "satirical",
    "tender",
    "gothic",
    "polemical",
    "pastoral",
    "neutral",
]
PROV_FIELDS = [
    "prov_character_development",
    "prov_plot_advancement",
    "prov_thematic_depth",
    "prov_social_critique",
    "prov_humor_entertainment",
    "prov_atmosphere_setting",
    "prov_narrative_technique",
]
ORDINAL_MAP = {"none": 0, "weak": 1, "strong": 2}

# UMAP parameters (must match clustering scripts)
UMAP_N_NEIGHBORS = 15
UMAP_MIN_DIST = 0.1
UMAP_RANDOM_STATE = 42


def git_short_hash() -> str:
    """Return the short git hash of HEAD, or 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def make_tag() -> str:
    """Return a timestamp_githash tag for output file naming."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{git_short_hash()}"


def build_literary_feature_matrix(
    passages: list[dict],
) -> tuple[np.ndarray, list[str]]:
    """Build a (N, 24) feature matrix from enrichment fields.

    Returns the matrix and the list of passage_ids in the same order.
    """
    n = len(passages)
    n_plot = len(PLOT_FUNCTIONS)
    n_emo = len(EMOTIONAL_REGISTERS)
    n_prov = len(PROV_FIELDS)
    total_cols = n_plot + n_emo + n_prov  # 8 + 9 + 7 = 24

    matrix = np.zeros((n, total_cols), dtype=np.float64)
    passage_ids: list[str] = []

    plot_idx = {pf: i for i, pf in enumerate(PLOT_FUNCTIONS)}
    emo_idx = {er: i + n_plot for i, er in enumerate(EMOTIONAL_REGISTERS)}

    for row, p in enumerate(passages):
        passage_ids.append(p["passage_id"])
        enr = p.get("enrichment") or {}

        pf = enr.get("plot_function", "")
        if pf in plot_idx:
            matrix[row, plot_idx[pf]] = 1.0

        for er in enr.get("emotional_register", []):
            if er in emo_idx:
                matrix[row, emo_idx[er]] = 1.0

        for j, field in enumerate(PROV_FIELDS):
            val = enr.get(field, "none")
            matrix[row, n_plot + n_emo + j] = float(ORDINAL_MAP.get(val, 0))

    return matrix, passage_ids


def build_character_matrix(
    passages: list[dict],
) -> tuple[csr_matrix, list[str], list[str]]:
    """Build a sparse binary (passages x characters) matrix.

    Returns the matrix, passage_ids, and sorted character names.
    """
    all_characters: set[str] = set()
    for p in passages:
        chars = p.get("enrichment", {}).get("characters_present", [])
        all_characters.update(chars)

    characters = sorted(all_characters)
    char_to_idx = {c: i for i, c in enumerate(characters)}

    rows: list[int] = []
    cols: list[int] = []
    passage_ids: list[str] = []

    for row_idx, p in enumerate(passages):
        passage_ids.append(p["passage_id"])
        chars = p.get("enrichment", {}).get("characters_present", [])
        for c in chars:
            rows.append(row_idx)
            cols.append(char_to_idx[c])

    data = np.ones(len(rows), dtype=np.float64)
    matrix = csr_matrix(
        (data, (rows, cols)),
        shape=(len(passages), len(characters)),
    )
    return matrix, passage_ids, characters


def compute_literary_cluster_profile(
    passages: list[dict],
    indices: list[int],
) -> dict:
    """Compute profile for a literary cluster."""
    pf_counter: Counter[str] = Counter()
    er_counter: Counter[str] = Counter()
    prov_sums = {f: 0.0 for f in PROV_FIELDS}

    for idx in indices:
        enr = passages[idx].get("enrichment") or {}
        pf_counter[enr.get("plot_function", "unknown")] += 1
        for er in enr.get("emotional_register", []):
            er_counter[er] += 1
        for f in PROV_FIELDS:
            prov_sums[f] += ORDINAL_MAP.get(enr.get(f, "none"), 0)

    n = len(indices)
    prov_means = {f: round(v / n, 2) if n > 0 else 0.0 for f, v in prov_sums.items()}

    return {
        "size": n,
        "dominant_plot_function": pf_counter.most_common(1)[0][0] if pf_counter else "?",
        "top_emotional_registers": [er for er, _ in er_counter.most_common(3)],
        "prov_means": prov_means,
    }


def compute_character_cluster_profile(
    passages: list[dict],
    indices: list[int],
    characters: list[str],
    char_matrix: np.ndarray,
    arcs: dict[str, list[str]] | None = None,
) -> dict:
    """Compute profile for a character cluster."""
    cluster_vectors = char_matrix[indices]
    char_sums = cluster_vectors.sum(axis=0)
    if hasattr(char_sums, 'A1'):
        char_sums = char_sums.A1  # Convert from matrix to array
    top_char_indices = np.argsort(char_sums)[::-1][:8]
    top_chars = [
        characters[i] for i in top_char_indices if char_sums[i] > 0
    ]

    # Annotate top characters with arc span if available
    top_chars_annotated: list[str] = []
    for name in top_chars:
        if arcs and name in arcs:
            arc_chapters = arcs[name]
            top_chars_annotated.append(f"{name} ({len(arc_chapters)}ch)")
        else:
            top_chars_annotated.append(name)

    # Chapter span
    chapter_ids: set[str] = set()
    for idx in indices:
        chapter_ids.add(passages[idx]["chapter_id"])
    sorted_chapters = sorted(chapter_ids)
    span = f"{sorted_chapters[0]}..{sorted_chapters[-1]}" if sorted_chapters else "none"

    return {
        "size": len(indices),
        "top_characters": top_chars_annotated,
        "chapter_span": span,
        "n_chapters": len(sorted_chapters),
    }


def _escape(text: str) -> str:
    """Escape text for safe embedding in HTML/JS."""
    return html.escape(text, quote=True)


def _build_passage_data(passages: list[dict]) -> list[dict]:
    """Build compact passage records for embedding in HTML."""
    records = []
    for p in passages:
        enr = p.get("enrichment") or {}
        records.append({
            "passage_id": p["passage_id"],
            "chapter_id": p["chapter_id"],
            "narrator": enr.get("narrator", p.get("narrator", "unknown")),
            "text": p.get("text", ""),
            "summary": enr.get("summary", ""),
            "characters_present": enr.get("characters_present", []),
            "plot_function": enr.get("plot_function", ""),
            "emotional_register": enr.get("emotional_register", []),
            "themes": enr.get("themes", []),
            "interest_score": enr.get("interest_score", p.get("interest_score", 0)),
            "prov_character_development": enr.get("prov_character_development", "none"),
            "prov_plot_advancement": enr.get("prov_plot_advancement", "none"),
            "prov_thematic_depth": enr.get("prov_thematic_depth", "none"),
            "prov_social_critique": enr.get("prov_social_critique", "none"),
            "prov_humor_entertainment": enr.get("prov_humor_entertainment", "none"),
            "prov_atmosphere_setting": enr.get("prov_atmosphere_setting", "none"),
            "prov_narrative_technique": enr.get("prov_narrative_technique", "none"),
        })
    return records


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #1a1a2e; color: #e0e0e0; }}
  #container {{ display: flex; height: 100vh; }}
  #main {{ flex: 1; display: flex; flex-direction: column; overflow: hidden; }}
  #plot {{ flex: 1; min-height: 400px; }}
  #table-container {{ max-height: 35vh; overflow-y: auto; padding: 12px;
                      background: #16213e; border-top: 1px solid #334; }}
  #table-container h3 {{ margin-bottom: 8px; color: #c8d6e5; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ padding: 4px 8px; text-align: left; border-bottom: 1px solid #334; }}
  th {{ background: #0f3460; color: #e0e0e0; position: sticky; top: 0; }}
  td {{ color: #bbb; }}
  tr:hover td {{ background: #1a3a5c; }}
  #sidebar {{ width: 0; overflow-y: auto; background: #16213e;
              border-left: 1px solid #334; transition: width 0.2s;
              padding: 0; flex-shrink: 0; }}
  #sidebar.open {{ width: 420px; padding: 16px; }}
  #sidebar h3 {{ color: #e0c97f; margin-bottom: 8px; }}
  #sidebar .close-btn {{ float: right; cursor: pointer; font-size: 20px;
                         color: #e74c3c; background: none; border: none; }}
  #sidebar .field-label {{ color: #7f8c8d; font-size: 12px; text-transform: uppercase;
                           margin-top: 12px; }}
  #sidebar .field-value {{ color: #e0e0e0; margin-top: 2px; line-height: 1.5; }}
  #sidebar .text-block {{ background: #0f3460; padding: 10px; border-radius: 4px;
                          margin-top: 4px; font-size: 13px; line-height: 1.6;
                          max-height: 300px; overflow-y: auto; white-space: pre-wrap; }}
  #sidebar .cluster-profile {{ background: #1a3a5c; padding: 8px; border-radius: 4px;
                               margin-top: 8px; font-size: 13px; }}
  .prov-bar {{ display: inline-block; height: 10px; background: #e0c97f;
               border-radius: 2px; margin-right: 4px; }}
</style>
</head>
<body>
<div id="container">
  <div id="main">
    <div id="plot"></div>
    <div id="table-container">
      <h3>Cluster Profiles</h3>
      {cluster_table}
    </div>
  </div>
  <div id="sidebar">
    <button class="close-btn" onclick="closeSidebar()">&times;</button>
    <div id="sidebar-content"></div>
  </div>
</div>
<script>
var passages = {passages_json};
var clusterProfiles = {profiles_json};
var pidToIdx = {{}};
passages.forEach(function(p, i) {{ pidToIdx[p.passage_id] = i; }});

var traceData = {traces_json};
var layout = {{
  paper_bgcolor: '#1a1a2e',
  plot_bgcolor: '#1a1a2e',
  font: {{ color: '#e0e0e0' }},
  title: {{ text: '{plot_title}', font: {{ size: 16 }} }},
  xaxis: {{ title: 'UMAP 1', gridcolor: '#334', zerolinecolor: '#334' }},
  yaxis: {{ title: 'UMAP 2', gridcolor: '#334', zerolinecolor: '#334' }},
  legend: {{ font: {{ size: 11 }}, bgcolor: 'rgba(22,33,62,0.8)' }},
  margin: {{ l: 50, r: 20, t: 40, b: 40 }},
  hovermode: 'closest'
}};

Plotly.newPlot('plot', traceData, layout, {{ responsive: true }});

document.getElementById('plot').on('plotly_click', function(data) {{
  if (!data.points.length) return;
  var pt = data.points[0];
  var pid = pt.customdata;
  if (!pid) return;
  var idx = pidToIdx[pid];
  if (idx === undefined) return;
  showSidebar(passages[idx], pt.data.name);
}});

function showSidebar(p, traceName) {{
  var sb = document.getElementById('sidebar');
  sb.classList.add('open');
  var cluster = traceName || 'unknown';
  // Extract cluster label number from trace name like "Cluster 3 (42)"
  var clMatch = cluster.match(/Cluster\\s+(\\d+)/i) || cluster.match(/Noise/i);
  var clLabel = clMatch ? (cluster.match(/Noise/i) ? '-1' : clMatch[1]) : '?';
  var profile = clusterProfiles[clLabel] || null;

  var h = '<h3>' + esc(p.passage_id) + '</h3>';
  h += '<div class="field-label">Chapter</div><div class="field-value">' + esc(p.chapter_id) + '</div>';
  h += '<div class="field-label">Narrator</div><div class="field-value">' + esc(p.narrator) + '</div>';
  h += '<div class="field-label">Cluster</div><div class="field-value">' + esc(cluster) + '</div>';
  h += '<div class="field-label">Summary</div><div class="field-value">' + esc(p.summary) + '</div>';
  h += '<div class="field-label">Full Text</div><div class="text-block">' + esc(p.text) + '</div>';
  h += '<div class="field-label">Characters Present</div><div class="field-value">' + esc((p.characters_present || []).join(', ')) + '</div>';
  h += '<div class="field-label">Plot Function</div><div class="field-value">' + esc(p.plot_function) + '</div>';
  h += '<div class="field-label">Emotional Registers</div><div class="field-value">' + esc((p.emotional_register || []).join(', ')) + '</div>';
  h += '<div class="field-label">Themes</div><div class="field-value">' + esc((p.themes || []).join(', ')) + '</div>';
  h += '<div class="field-label">Interest Score</div><div class="field-value">' + p.interest_score + '</div>';

  // Provenance fields
  var provFields = ['prov_character_development', 'prov_plot_advancement', 'prov_thematic_depth',
                    'prov_social_critique', 'prov_humor_entertainment', 'prov_atmosphere_setting',
                    'prov_narrative_technique'];
  h += '<div class="field-label">Provenance Fields</div>';
  provFields.forEach(function(f) {{
    var val = p[f] || 'none';
    var w = val === 'strong' ? 60 : (val === 'weak' ? 30 : 5);
    var label = f.replace('prov_', '').replace(/_/g, ' ');
    h += '<div class="field-value" style="font-size:12px">';
    h += '<span class="prov-bar" style="width:' + w + 'px"></span> ';
    h += label + ': ' + val + '</div>';
  }});

  if (profile) {{
    h += '<div class="field-label">Cluster Profile</div>';
    h += '<div class="cluster-profile">' + profile + '</div>';
  }}

  document.getElementById('sidebar-content').innerHTML = h;
}}

function closeSidebar() {{
  document.getElementById('sidebar').classList.remove('open');
}}

function esc(s) {{
  if (!s) return '';
  var d = document.createElement('div');
  d.appendChild(document.createTextNode(s));
  return d.innerHTML;
}}
</script>
</body>
</html>
"""


def _build_traces(
    coords: np.ndarray,
    labels: dict[str, int],
    passage_ids: list[str],
    passages: list[dict],
) -> list[dict]:
    """Build Plotly trace dicts for scatter plot."""
    # Map passage_id -> index for quick lookup
    pid_to_row = {pid: i for i, pid in enumerate(passage_ids)}

    # Group by label
    label_to_rows: dict[int, list[int]] = {}
    for pid, lbl in labels.items():
        if pid in pid_to_row:
            label_to_rows.setdefault(lbl, []).append(pid_to_row[pid])

    # Build passage_id -> passage for hover text
    pid_to_passage: dict[str, dict] = {}
    for p in passages:
        pid_to_passage[p["passage_id"]] = p

    traces = []

    # Noise first
    if -1 in label_to_rows:
        rows = label_to_rows[-1]
        hover_texts = []
        custom_data = []
        for r in rows:
            pid = passage_ids[r]
            p = pid_to_passage.get(pid, {})
            enr = p.get("enrichment") or {}
            text_preview = p.get("text", "")[:150].replace("\n", " ")
            narrator = enr.get("narrator", p.get("narrator", "?"))
            hover_texts.append(
                f"{pid}<br>Ch: {p.get('chapter_id', '?')}<br>"
                f"Narrator: {narrator}<br>{text_preview}"
            )
            custom_data.append(pid)
        traces.append({
            "x": [float(coords[r, 0]) for r in rows],
            "y": [float(coords[r, 1]) for r in rows],
            "mode": "markers",
            "marker": {"color": "#666666", "size": 4, "opacity": 0.4},
            "text": hover_texts,
            "customdata": custom_data,
            "hoverinfo": "text",
            "name": f"Noise ({len(rows)})",
            "type": "scatter",
        })

    # Each cluster
    sorted_labels = sorted(lb for lb in label_to_rows if lb >= 0)
    # Use a set of distinct colors
    colors = [
        "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
        "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
        "#469990", "#dcbeff", "#9A6324", "#fffac8", "#800000",
        "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
    ]

    for lb in sorted_labels:
        rows = label_to_rows[lb]
        color = colors[lb % len(colors)]
        hover_texts = []
        custom_data = []
        for r in rows:
            pid = passage_ids[r]
            p = pid_to_passage.get(pid, {})
            enr = p.get("enrichment") or {}
            text_preview = p.get("text", "")[:150].replace("\n", " ")
            narrator = enr.get("narrator", p.get("narrator", "?"))
            hover_texts.append(
                f"{pid}<br>Ch: {p.get('chapter_id', '?')}<br>"
                f"Narrator: {narrator}<br>{text_preview}"
            )
            custom_data.append(pid)
        traces.append({
            "x": [float(coords[r, 0]) for r in rows],
            "y": [float(coords[r, 1]) for r in rows],
            "mode": "markers",
            "marker": {"color": color, "size": 5, "opacity": 0.7},
            "text": hover_texts,
            "customdata": custom_data,
            "hoverinfo": "text",
            "name": f"Cluster {lb} ({len(rows)})",
            "type": "scatter",
        })

    return traces


def generate_literary_html(
    passages: list[dict],
    literary_clusters: dict[str, int],
    tag: str,
) -> None:
    """Generate the literary feature clusters HTML visualization."""
    logger.info("Building literary feature matrix...")
    matrix, passage_ids = build_literary_feature_matrix(passages)

    scaler = StandardScaler()
    X = scaler.fit_transform(matrix)

    logger.info("Running UMAP on literary feature matrix...")
    reducer = umap.UMAP(
        n_neighbors=UMAP_N_NEIGHBORS,
        min_dist=UMAP_MIN_DIST,
        metric="euclidean",
        random_state=UMAP_RANDOM_STATE,
        n_components=2,
    )
    coords: np.ndarray = reducer.fit_transform(X)  # type: ignore[assignment]

    # Compute cluster profiles
    pid_to_row = {pid: i for i, pid in enumerate(passage_ids)}
    label_to_indices: dict[int, list[int]] = {}
    for pid, lbl in literary_clusters.items():
        if pid in pid_to_row:
            label_to_indices.setdefault(lbl, []).append(pid_to_row[pid])

    profiles: dict[str, str] = {}
    cluster_table_rows: list[str] = []
    for lbl in sorted(label_to_indices):
        if lbl == -1:
            continue
        indices = label_to_indices[lbl]
        profile = compute_literary_cluster_profile(passages, indices)
        prov_str = ", ".join(
            f"{f.replace('prov_', '')}: {v}"
            for f, v in profile["prov_means"].items()
        )
        profile_text = (
            f"Size: {profile['size']} | "
            f"Dominant: {profile['dominant_plot_function']} | "
            f"Emotions: {', '.join(profile['top_emotional_registers'])} | "
            f"Prov: {prov_str}"
        )
        profiles[str(lbl)] = profile_text

        cluster_table_rows.append(
            f"<tr><td>{lbl}</td><td>{profile['size']}</td>"
            f"<td>{_escape(profile['dominant_plot_function'])}</td>"
            f"<td>{_escape(', '.join(profile['top_emotional_registers']))}</td>"
            f"<td>{_escape(prov_str)}</td></tr>"
        )

    cluster_table = (
        "<table><thead><tr><th>Cluster</th><th>Size</th>"
        "<th>Dominant Plot Fn</th><th>Top Emotions</th>"
        "<th>Prov Means</th></tr></thead><tbody>"
        + "\n".join(cluster_table_rows)
        + "</tbody></table>"
    )

    traces = _build_traces(coords, literary_clusters, passage_ids, passages)
    passage_data = _build_passage_data(passages)

    n_clusters = len([lb for lb in set(literary_clusters.values()) if lb >= 0])
    html_content = _HTML_TEMPLATE.format(
        title="Literary Feature Clusters - Bleak House",
        cluster_table=cluster_table,
        passages_json=json.dumps(passage_data),
        profiles_json=json.dumps(profiles),
        traces_json=json.dumps(traces),
        plot_title=f"Literary Feature Clusters ({n_clusters} clusters, UMAP)",
    )

    output_path = REPORTS_DIR / f"clusters_literary_{tag}.html"
    output_path.write_text(html_content)
    logger.info("Saved literary clusters HTML to %s", output_path)


def generate_characters_html(
    passages: list[dict],
    char_clusters: dict[str, int],
    arcs: dict[str, list[str]],
    tag: str,
) -> None:
    """Generate the character co-occurrence clusters HTML visualization."""
    logger.info("Building character presence matrix...")
    matrix, passage_ids, characters = build_character_matrix(passages)

    logger.info("Running UMAP on character matrix (Jaccard metric)...")
    reducer = umap.UMAP(
        n_neighbors=UMAP_N_NEIGHBORS,
        min_dist=UMAP_MIN_DIST,
        metric="jaccard",
        random_state=UMAP_RANDOM_STATE,
        n_components=2,
    )
    coords: np.ndarray = reducer.fit_transform(matrix.toarray())  # type: ignore[assignment]

    # Compute cluster profiles
    pid_to_row = {pid: i for i, pid in enumerate(passage_ids)}
    label_to_indices: dict[int, list[int]] = {}
    for pid, lbl in char_clusters.items():
        if pid in pid_to_row:
            label_to_indices.setdefault(lbl, []).append(pid_to_row[pid])

    dense_matrix = matrix.toarray()
    profiles: dict[str, str] = {}
    cluster_table_rows: list[str] = []
    for lbl in sorted(label_to_indices):
        if lbl == -1:
            continue
        indices = label_to_indices[lbl]
        profile = compute_character_cluster_profile(
            passages, indices, characters, dense_matrix, arcs
        )
        top_chars_str = ", ".join(profile["top_characters"])
        profile_text = (
            f"Size: {profile['size']} | "
            f"Top chars: {top_chars_str} | "
            f"Chapters: {profile['n_chapters']} ({profile['chapter_span']})"
        )
        profiles[str(lbl)] = profile_text

        cluster_table_rows.append(
            f"<tr><td>{lbl}</td><td>{profile['size']}</td>"
            f"<td>{_escape(top_chars_str)}</td>"
            f"<td>{profile['n_chapters']}</td>"
            f"<td>{_escape(profile['chapter_span'])}</td></tr>"
        )

    cluster_table = (
        "<table><thead><tr><th>Cluster</th><th>Size</th>"
        "<th>Top Characters</th><th># Chapters</th>"
        "<th>Chapter Span</th></tr></thead><tbody>"
        + "\n".join(cluster_table_rows)
        + "</tbody></table>"
    )

    traces = _build_traces(coords, char_clusters, passage_ids, passages)
    passage_data = _build_passage_data(passages)

    n_clusters = len([lb for lb in set(char_clusters.values()) if lb >= 0])
    html_content = _HTML_TEMPLATE.format(
        title="Character Co-occurrence Clusters - Bleak House",
        cluster_table=cluster_table,
        passages_json=json.dumps(passage_data),
        profiles_json=json.dumps(profiles),
        traces_json=json.dumps(traces),
        plot_title=f"Character Co-occurrence Clusters ({n_clusters} clusters, UMAP/Jaccard)",
    )

    output_path = REPORTS_DIR / f"clusters_characters_{tag}.html"
    output_path.write_text(html_content)
    logger.info("Saved character clusters HTML to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    load_dotenv()

    REPORTS_DIR.mkdir(exist_ok=True)
    tag = make_tag()

    # Load passages (keep only those with enrichment)
    raw = json.loads(PASSAGES_PATH.read_text())
    passages = [p for p in raw if p.get("enrichment")]
    logger.info("Loaded %d passages with enrichment from %s", len(passages), PASSAGES_PATH)

    # Load cluster assignments
    literary_clusters: dict[str, int] = json.loads(LITERARY_CLUSTERS_PATH.read_text())
    logger.info("Loaded %d literary cluster assignments", len(literary_clusters))

    char_clusters: dict[str, int] = json.loads(CHAR_CLUSTERS_PATH.read_text())
    logger.info("Loaded %d character cluster assignments", len(char_clusters))

    arcs: dict[str, list[str]] = json.loads(ARCS_PATH.read_text())
    logger.info("Loaded %d character arcs", len(arcs))

    generate_literary_html(passages, literary_clusters, tag)
    generate_characters_html(passages, char_clusters, arcs, tag)

    logger.info("Done.")


if __name__ == "__main__":
    main()
