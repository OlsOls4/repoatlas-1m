(function () {
  "use strict";

  const state = { bugs: [], library: "all", badge: "real", chartBuilt: false };

  function $(id) {
    return document.getElementById(id);
  }

  function fetchJson(name) {
    return fetch("data/" + name + ".json").then(function (response) {
      if (!response.ok) {
        throw new Error("Failed to load " + name);
      }
      return response.json();
    });
  }

  function formatNumber(value) {
    return Number(value).toLocaleString("en-US");
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function mdInline(s) {
    if (!s) {
      return "";
    }
    return escapeHtml(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }

  function md(s) {
    if (!s) {
      return "";
    }
    const lines = String(s).split(/\n/);
    let out = "";
    let inL = false;
    for (let i = 0; i < lines.length; i += 1) {
      const t = mdInline(lines[i]);
      if (/^\s*- /.test(t) || /^\s*- /.test(lines[i])) {
        if (!inL) {
          out += "<ul>";
          inL = true;
        }
        out += "<li>" + t.replace(/^\s*- /, "") + "</li>";
      } else {
        if (inL) {
          out += "</ul>";
          inL = false;
        }
        if (t.trim()) {
          out += "<p>" + t + "</p>";
        }
      }
    }
    return out + (inL ? "</ul>" : "");
  }

  function formatDate(iso) {
    try {
      return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
    } catch (err) {
      return iso;
    }
  }

  function renderHero(hero, copy, replay) {
    if (!$("headline").querySelector(".lead-full") || !$("headline").querySelector(".lead-full").textContent.trim()) {
      $("headline").innerHTML =
        "<p class='lead-full'>" + escapeHtml(hero.lead || hero.headline || "") + "</p>" +
        "<p class='lead-short'>" + escapeHtml(hero.lead_short || "") + "</p>";
    }
    if (!$("tiles").children.length && hero.tiles) {
      $("tiles").innerHTML = hero.tiles
        .map(function (tile) {
          return "<div class='tile'><strong>" + tile[0] + "</strong><span>" + tile[1] + "</span></div>";
        })
        .join("");
    }
    $("hero-note").textContent = hero.label_note || "";
    const links = (copy && copy.links) || {};
    const linkHtml =
      (links.code ? '<a href="' + links.code + '">Code</a> · ' : "") +
      (links.dataset ? '<a href="' + links.dataset + '">Dataset</a> · ' : "") +
      (links.thread ? '<a href="' + links.thread + '">Thread</a>' : "");
    if (!$("hero-links").querySelector("a")) {
      $("hero-links").innerHTML = linkHtml;
    }
    $("run-links").innerHTML = linkHtml;
    renderDrift(replay);
    if (copy && copy.video) {
      $("demo-video-el").src = copy.video;
      $("demo-video").hidden = false;
    }
    const sample = $("sample-output");
    if (sample && copy && copy.sample_output) {
      $("sample-pre").textContent = copy.sample_output;
      sample.hidden = false;
    }
  }

  function renderDrift(replay) {
    const card = (replay && replay.drift_card) || {};
    $("drift-doc").innerHTML = mdInline(card.doc_quote || "");
    $("drift-code").innerHTML = mdInline(card.code_quote || "");
    $("drift-err").textContent = card.error || "";
    const pr = card.pr_url
      ? '<a href="' + card.pr_url + '">' + (card.pr_label || "PR #3746") + "</a>"
      : "";
    $("drift-foot").innerHTML =
      "→ " +
      escapeHtml(card.found_by || "Found by Beam's whole-repo pass (also flagged by the symbol check)") +
      (pr ? " · " + pr : "");
    $("drift-honest").textContent =
      card.hand_written_note ||
      "Repro script for this one was written by hand from Beam's verdict; the other repros were written by Beam.";
  }

  function renderHowBeam(copy) {
    $("how-beam").innerHTML = (copy.how_beam || [])
      .map(function (item) {
        return "<li>" + md(item) + "</li>";
      })
      .join("");
    $("criteria-box").innerHTML = (copy.criteria || [])
      .map(function (row) {
        return "<article><h3>" + row.title + "</h3>" + md(row.body) + "</article>";
      })
      .join("");
  }

  function renderWhy(ablation, copy) {
    const caption =
      (copy && copy.why_caption) ||
      "Long context didn't change verdicts here. It changed whether Beam could point to the proof in another file.";
    $("why-caption").textContent = caption;
    if (!ablation || !ablation.available) {
      return;
    }
    const pairs = [];
    if (ablation.outside_cite_whole && ablation.outside_cite_local) {
      pairs.push(["Off-file evidence cited", ablation.outside_cite_whole, ablation.outside_cite_local]);
    }
    if (ablation.cross_file_cite_whole && ablation.cross_file_cite_local) {
      pairs.push(["Cross-file citations", ablation.cross_file_cite_whole, ablation.cross_file_cite_local]);
    }
    if (ablation.accuracy_whole && ablation.accuracy_local) {
      pairs.push(["Verdict accuracy", ablation.accuracy_whole, ablation.accuracy_local]);
    }
    if (!pairs.length) {
      return;
    }
    const width = 640;
    const rowH = 56;
    const height = 24 + pairs.length * rowH;
    let bars = "";
    pairs.forEach(function (pair, index) {
      const y = 20 + index * rowH;
      const whole = frac(pair[1]);
      const local = frac(pair[2]);
      bars +=
        '<text class="bar-label" x="0" y="' +
        y +
        '">' +
        pair[0] +
        "</text>" +
        '<rect class="bar-whole" x="0" y="' +
        (y + 6) +
        '" width="' +
        Math.max(8, whole * 420) +
        '" height="10" rx="2"></rect>' +
        '<text class="bar-label" x="' +
        (Math.max(8, whole * 420) + 8) +
        '" y="' +
        (y + 15) +
        '">whole ' +
        pair[1] +
        "</text>" +
        '<rect class="bar-local" x="0" y="' +
        (y + 20) +
        '" width="' +
        Math.max(4, local * 420) +
        '" height="10" rx="2"></rect>' +
        '<text class="bar-label" x="' +
        (Math.max(4, local * 420) + 8) +
        '" y="' +
        (y + 29) +
        '">local ' +
        pair[2] +
        "</text>";
    });
    $("why-chart").innerHTML =
      '<svg viewBox="0 0 ' + width + " " + height + '" role="img" aria-label="' + caption + '">' + bars + "</svg>";
    const subset = $("why-subset");
    if (subset) {
      subset.textContent = (copy && copy.why_subset_note) || (ablation && ablation.subset_note) || "";
    }
    $("why-placeholder").textContent =
      copy.why_matched_cost_note || "Matched-cost local bar: not run yet.";
  }

  function frac(text) {
    const match = String(text).match(/(\d+(?:\.\d+)?)(?:\s*\/\s*(\d+))?/);
    if (!match) {
      return 0;
    }
    if (match[2]) {
      return Number(match[1]) / Number(match[2]);
    }
    const value = Number(match[1]);
    return value > 1 ? value / 100 : value;
  }

  function uniqueLibraries(bugs) {
    const names = {};
    bugs.forEach(function (bug) {
      names[bug.library] = true;
    });
    return Object.keys(names).sort();
  }

  function badgeCounts(bugs) {
    const counts = { reproduced: 0, checked: 0, false: 0, true: 0 };
    bugs.forEach(function (bug) {
      if (counts[bug.badge] !== undefined) {
        counts[bug.badge] += 1;
      }
      if (bug.verdict === "true") {
        counts.true += 1;
      }
    });
    return counts;
  }

  function renderChips(bugs) {
    const libraries = uniqueLibraries(bugs);
    $("library-chips").innerHTML =
      chip("all", "All libraries", state.library === "all") +
      libraries
        .map(function (name) {
          return chip(name, name, state.library === name);
        })
        .join("");
    const counts = badgeCounts(bugs);
    $("badge-chips").innerHTML =
      chip("real", "Real " + counts.true, state.badge === "real") +
      chip("reproduced", "Reproduced " + counts.reproduced, state.badge === "reproduced") +
      chip("checked", "Checked " + counts.checked, state.badge === "checked") +
      chip("false", "False / unclear " + counts.false, state.badge === "false") +
      chip("all", "All " + bugs.length, state.badge === "all");
    $("library-chips").querySelectorAll(".chip").forEach(function (button) {
      button.addEventListener("click", function () {
        state.library = button.getAttribute("data-value");
        renderChips(bugs);
        renderBugs();
      });
    });
    $("badge-chips").querySelectorAll(".chip").forEach(function (button) {
      button.addEventListener("click", function () {
        state.badge = button.getAttribute("data-value");
        renderChips(bugs);
        renderBugs();
      });
    });
  }

  function chip(value, label, pressed) {
    return (
      '<button type="button" class="chip" data-value="' +
      value +
      '" aria-pressed="' +
      (pressed ? "true" : "false") +
      '">' +
      label +
      "</button>"
    );
  }

  function matchesFilter(bug, library, badge) {
    if (library !== "all" && bug.library !== library) {
      return false;
    }
    if (badge === "all") {
      return true;
    }
    if (badge === "real") {
      return bug.verdict === "true";
    }
    return bug.badge === badge;
  }

  function duplicateSummary(bug) {
    const title = String(bug.title || "");
    const summary = String(bug.summary || "");
    if (!summary) {
      return true;
    }
    const stripped = title.replace(/^[A-Za-z0-9._-]+:\s*/, "");
    return summary === title || summary === stripped;
  }

  function renderBugs() {
    const matched = state.bugs.filter(function (bug) {
      return matchesFilter(bug, state.library, state.badge);
    });
    $("bug-count").textContent = "Showing " + matched.length + " of " + state.bugs.length;
    $("bug-grid").innerHTML =
      matched
        .map(function (bug) {
          const display = bug.display_id || bug.id;
          const docBlock = bug.doc_quote
            ? "<p class='lbl'>Docs say</p><pre class='mini doc'>" + mdInline(bug.doc_quote) + "</pre>"
            : "";
          let codeBlock = "";
          if (bug.code_quote) {
            codeBlock = "<p class='lbl'>Code says</p><pre class='mini code'>" + mdInline(bug.code_quote) + "</pre>";
          } else if (!bug.code_url && !bug.code_path && bug.verdict === "true") {
            codeBlock =
              "<p class='lbl'>Code says</p><pre class='mini code'>Not found at the documented path in " +
              escapeHtml(bug.library) +
              (bug.ref ? " @" + escapeHtml(bug.ref) : "") +
              ". See the repro below.</pre>";
          }
          const runBlock = bug.badge_note
            ? "<p class='lbl'>Running it gives</p><pre class='mini err'>" + escapeHtml(bug.badge_note) + "</pre>"
            : "";
          const docLink = bug.doc_url
            ? "<a href='" + bug.doc_url + "'>" + bug.doc_path + (bug.doc_line ? ":" + bug.doc_line : "") + "</a>"
            : bug.doc_path
              ? bug.doc_path + (bug.doc_line ? ":" + bug.doc_line : "")
              : "";
          const codeLink = bug.code_url
            ? "<a href='" + bug.code_url + "'>" + bug.code_path + (bug.code_line ? ":" + bug.code_line : "") + "</a>"
            : "";
          const upstream = bug.upstream
            ? "<span class='pill pill-open'>" +
              (bug.upstream.url ? "<a href='" + bug.upstream.url + "'>" + bug.upstream.label + "</a>" : bug.upstream.label) +
              "</span>"
            : "";
          const title = bug.short_title || String(bug.title || "").replace(/^[A-Za-z0-9._-]+:\s*/, "");
          const summary = duplicateSummary(bug) ? "" : "<p>" + md(bug.summary) + "</p>";
          return (
            "<article class='card' title='" +
            escapeHtml(bug.id) +
            "'>" +
            "<span class='disp-id'>" +
            display +
            "</span>" +
            "<span class='pill'>" +
            bug.library +
            "</span>" +
            "<span class='pill pill-" +
            bug.badge +
            "'>" +
            bug.badge +
            "</span>" +
            (bug.cross_file
              ? "<span class='pill' title='The doc and the code it describes are in different files.' aria-describedby='cross-file-def'>cross-file</span>"
              : "") +
            upstream +
            "<h3>" +
            mdInline(title) +
            "</h3>" +
            summary +
            docBlock +
            codeBlock +
            runBlock +
            "<p class='meta'>" +
            (docLink ? "<b>Doc</b> " + docLink : "") +
            (codeLink ? "<br><b>Code</b> " + codeLink : "") +
            (bug.ref ? "<br><b>Commit</b> " + bug.ref : "") +
            "</p></article>"
          );
        })
        .join("") || "<p>No cards match this filter.</p>";
  }

  function tableHtml(headers, rows, extraFrom) {
    return (
      "<thead><tr>" +
      headers
        .map(function (header, index) {
          return "<th" + extraClass(index, extraFrom) + ">" + header + "</th>";
        })
        .join("") +
      "</tr></thead><tbody>" +
      rows
        .map(function (row) {
          return (
            "<tr>" +
            row
              .map(function (cell, index) {
                return (
                  "<td data-label='" +
                  escapeHtml(headers[index] || "") +
                  "'" +
                  extraClass(index, extraFrom) +
                  ">" +
                  mdCell(cell) +
                  "</td>"
                );
              })
              .join("") +
            "</tr>"
          );
        })
        .join("") +
      "</tbody>"
    );
  }

  function extraClass(index, extraFrom) {
    if (extraFrom && extraFrom.indexOf(index) !== -1) {
      return " class='extra-col'";
    }
    return "";
  }

  function mdCell(cell) {
    if (cell && typeof cell === "object" && cell.text !== undefined) {
      const title = cell.title ? " title='" + escapeHtml(cell.title) + "'" : "";
      return "<span" + title + ">" + mdInline(String(cell.text)) + "</span>";
    }
    return mdInline(String(cell));
  }

  function renderBenchmark(benchmark, hero, copy) {
    const caption = $("bench-caption");
    if (caption) {
      caption.textContent = (copy && copy.bench_caption) || "";
    }
    $("bench-headlines").innerHTML =
      tile(hero.hybrid_true + " of " + hero.universe_size, "found") +
      tile(hero.hybrid_true_findings + " of " + hero.hybrid_findings, "flagged were real") +
      tile(hero.repro_true + " of " + hero.hybrid_true, "reproduce");
    $("token-footnote").innerHTML = md(benchmark.token_footnote || "");
    $("compare-table").innerHTML = tableHtml(benchmark.headers, benchmark.rows);
    $("funnel").innerHTML = benchmark.funnel
      .map(function (step) {
        return "<li><b>" + step.step + ":</b> " + step.true + " true. " + md(step.detail) + "</li>";
      })
      .join("");
    const ablation = benchmark.ablation || {};
    if (ablation.available) {
      $("ablation-claim").innerHTML = md(ablation.claim);
      $("ablation-table").innerHTML = tableHtml(ablation.headers, ablation.rows);
      const subsetLine = $("ablation-subset");
      if (subsetLine) {
        subsetLine.textContent = ablation.subset_note || (copy && copy.why_subset_note) || "";
      }
      $("ablation-caveats").innerHTML = (ablation.caveats || [])
        .map(function (item) {
          return "<li>" + md(item) + "</li>";
        })
        .join("");
    }
    const beamv3 = benchmark.beamv3 || {};
    if (beamv3.available) {
      $("beamv3-title").textContent = beamv3.title || "Catching what one whole-repo call misses";
      $("beamv3-claim").innerHTML = md(beamv3.claim);
      $("beamv3-recipe").innerHTML = md(beamv3.recipe);
      const extra = [1, 3, 4, 5, 7, 9, 10, 12, 13];
      $("beamv3-table").innerHTML = tableHtml(beamv3.headers, beamv3.rows, extra);
    }
    const toggle = $("beamv3-cols");
    if (toggle) {
      toggle.addEventListener("toggle", function () {
        $("beamv3-table").classList.toggle("show-all", toggle.open);
      });
    }
    if (beamv3.available) {
      $("beamv3-caveats").innerHTML = (beamv3.caveats || [])
        .map(function (item) {
          return "<li>" + md(item) + "</li>";
        })
        .join("");
    }
    const recall = benchmark.recall || {};
    $("recall-note").innerHTML = md(
      "Separate planted-drift distance probe, not a triage-accuracy result. Beam accepted prompts up to " +
        formatNumber(recall.max_probe_tokens) +
        " tokens. Focused whole-context passes hit " +
        (recall.far_hits ? recall.far_hits[0] + "/" + recall.far_hits[1] : "") +
        " planted drifts 700k+ tokens apart vs " +
        (recall.chunk_far ? recall.chunk_far[0] + "/" + recall.chunk_far[1] : "") +
        " for chunked 128k, seed 1 only, n=6."
    );
    drawRecall(recall);
    if (benchmark.chart_present) {
      const image = $("recall-chart");
      const details = $("recall-all");
      image.setAttribute("data-src", benchmark.recall.chart);
      if (details) {
        details.addEventListener("toggle", function () {
          if (details.open && !image.getAttribute("src")) {
            image.src = image.getAttribute("data-src");
            image.hidden = false;
          }
        });
      }
    }
    $("benchmark-notes").innerHTML = md(benchmark.notes_markdown || "");
    const pack = benchmark.pack_coverage;
    if (pack && pack.available) {
      $("pack-note").innerHTML = md(pack.note || "");
      $("pack-table").innerHTML = tableHtml(pack.headers, pack.rows);
    }
  }

  function tile(value, label) {
    return "<div class='tile'><strong>" + value + "</strong><span>" + label + "</span></div>";
  }

  function drawRecall(recall) {
    const series = recall.default_series;
    if (!series || !series.length) {
      return;
    }
    const buckets = recall.buckets || ["~1k", "~10k", "~50k", "~100k", "~200k", "~400k", "700k+"];
    const width = 720;
    const height = 220;
    const left = 36;
    const bottom = 36;
    const plotW = width - left - 120;
    const plotH = height - bottom - 20;
    let paths = "";
    const colors = ["#a84a1c", "#2f6d4f", "#5c574e"];
    const den = recall.far_hits ? recall.far_hits[1] : 0;
    let grid = "";
    [0, 0.5, 1].forEach(function (tick) {
      const y = 20 + plotH * (1 - tick);
      grid +=
        '<line class="grid" x1="' +
        left +
        '" y1="' +
        y +
        '" x2="' +
        (left + plotW) +
        '" y2="' +
        y +
        '"></line>' +
        '<text x="' +
        (left - 6) +
        '" y="' +
        (y + 4) +
        '" font-size="11" text-anchor="end">' +
        tick +
        "</text>";
    });
    series.forEach(function (line, s) {
      const pts = (line.points || []).map(function (value, i) {
        const x = left + (i / Math.max(1, buckets.length - 1)) * plotW;
        const y = 20 + plotH * (1 - value);
        return x + "," + y;
      });
      const last = pts[pts.length - 1] ? pts[pts.length - 1].split(",") : ["0", "0"];
      const lastVal = (line.points || [])[(line.points || []).length - 1] || 0;
      const short =
        line.id === "focused_seed1" ? "focused" : line.id === "chunk128k_seed1" ? "chunked" : "whole-repo";
      const endLabel = den ? short + " " + Math.round(lastVal * den) + "/" + den : line.label;
      paths +=
        '<polyline fill="none" stroke="' +
        colors[s % colors.length] +
        '" stroke-width="2" points="' +
        pts.join(" ") +
        '"></polyline>' +
        '<text class="endlabel" x="' +
        (Number(last[0]) + 8) +
        '" y="' +
        (Number(last[1]) + 4) +
        '">' +
        escapeHtml(endLabel) +
        "</text>";
    });
    const axis = buckets
      .map(function (name, i) {
        const x = left + (i / Math.max(1, buckets.length - 1)) * plotW;
        return '<text x="' + x + '" y="' + (height - 8) + '" font-size="11" text-anchor="middle">' + name + "</text>";
      })
      .join("");
    paths = grid + paths;
    $("recall-svg").innerHTML =
      '<svg viewBox="0 0 ' +
      width +
      " " +
      height +
      '" role="img" aria-label="Planted-drift strict recall by distance, three methods">' +
      paths +
      axis +
      "</svg>";
  }

  function renderRepros(repros) {
    const headers = ["Id", "Library", "Verdict", "Status", "Strict", "Error"];
    const rows = repros.map(function (row) {
      return [
        { text: row.display_id || row.id, title: row.id },
        row.library,
        row.verdict,
        row.status,
        row.strict_confirmed ? "yes" : "no",
        row.error_excerpt || row.exception_type || "",
      ];
    });
    $("repro-table").innerHTML = tableHtml(headers, rows);
  }

  function renderReplay(replay) {
    const seconds = replay.latency_seconds ? Math.round(replay.latency_seconds) + " s" : "";
    $("replay-banner").innerHTML =
      "<b>Recorded run</b> · starlette @" +
      (replay.ref || "8aa828c") +
      " · " +
      formatDate(replay.recorded_at) +
      " · " +
      formatNumber(replay.prompt_tokens) +
      " tokens in one Beam call" +
      (seconds ? " · " + seconds : "") +
      " · " +
      replay.candidate_count +
      " candidates → " +
      replay.kept +
      " real, " +
      replay.rejected +
      " rejected.";
    $("replay-banner").title = replay.trace_path || "";
    $("player-summary").textContent =
      "Watch the recorded starlette run (" +
      replay.candidate_count +
      " candidates → " +
      replay.kept +
      " kept)";
    $("player-candidates").innerHTML = (replay.candidates || [])
      .map(function (item) {
        return (
          "<li><b>" +
          item.id +
          " · " +
          item.source +
          "</b> " +
          item.doc_path +
          ":" +
          item.doc_line +
          " — " +
          md(item.claim) +
          "</li>"
        );
      })
      .join("");
    $("player-verdicts").innerHTML = (replay.candidates || [])
      .map(function (item) {
        const site = item.code_path ? item.code_path + (item.code_line ? ":" + item.code_line : "") : "no code cite";
        return "<li><b>" + item.id + " → " + item.verdict + "</b> " + site + ". " + md(item.reason) + "</li>";
      })
      .join("");
    $("player-repro-note").innerHTML = md(replay.repro_note || "");
    $("player-tracebacks").innerHTML = (replay.tracebacks || [])
      .map(function (row) {
        return (
          "<pre><code>attempt " +
          row.attempt +
          " · " +
          row.status +
          " · " +
          row.exception_type +
          "\n" +
          (row.excerpt || "") +
          "</code></pre>"
        );
      })
      .join("");
    const pr = replay.pr || {};
    $("player-pr").innerHTML = pr.url ? '<a href="' + pr.url + '">' + pr.label + "</a> — " + (pr.note || "") : "";
  }

  function renderCopy(copy) {
    $("ollama-key").innerHTML = md(copy.ollama_key);
    $("cli-cmd").textContent = copy.cli;
    $("limits-list").innerHTML = copy.limits
      .map(function (item) {
        return "<li>" + md(item) + "</li>";
      })
      .join("");
    $("exclusions-list").innerHTML = (copy.exclusions || [])
      .map(function (item) {
        return "<li>" + md(item) + "</li>";
      })
      .join("");
    $("glossary-list").innerHTML = (copy.glossary || [])
      .map(function (item) {
        return "<li>" + md(item) + "</li>";
      })
      .join("");
    $("sources").textContent = copy.sources_public || "";
    const cross = $("cross-file-def");
    if (cross) {
      cross.textContent = copy.cross_file_note || "";
    }
  }

  function activateTab(name, setHash, shouldFocus) {
    const buttons = document.querySelectorAll(".tab");
    const panels = document.querySelectorAll(".panel");
    buttons.forEach(function (button, index) {
      const selected = button.getAttribute("data-tab") === name;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-selected", selected ? "true" : "false");
      button.tabIndex = selected ? 0 : -1;
      if (selected && shouldFocus) {
        button.focus({ preventScroll: true });
      }
      button.setAttribute("data-index", String(index));
    });
    panels.forEach(function (panel) {
      const selected = panel.id === name;
      panel.classList.toggle("is-active", selected);
      panel.hidden = !selected;
    });
    if (setHash !== false) {
      history.replaceState(null, "", "#" + name);
    }
    if (name === "benchmark" && !state.chartBuilt) {
      state.chartBuilt = true;
    }
  }

  function bindTabs() {
    const buttons = Array.prototype.slice.call(document.querySelectorAll(".tab"));
    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        activateTab(button.getAttribute("data-tab"), true, true);
      });
    });
    document.querySelector(".tabs").addEventListener("keydown", function (event) {
      const keys = { ArrowRight: 1, ArrowLeft: -1, Home: "home", End: "end" };
      if (!(event.key in keys)) {
        return;
      }
      event.preventDefault();
      const current = buttons.findIndex(function (button) {
        return button.getAttribute("aria-selected") === "true";
      });
      let next = current;
      if (event.key === "Home") {
        next = 0;
      } else if (event.key === "End") {
        next = buttons.length - 1;
      } else {
        next = (current + keys[event.key] + buttons.length) % buttons.length;
      }
      activateTab(buttons[next].getAttribute("data-tab"), true, true);
    });
    const hash = (location.hash || "#story").replace("#", "");
    const known = buttons.some(function (button) {
      return button.getAttribute("data-tab") === hash;
    });
    activateTab(known ? hash : "story", false);
    window.addEventListener("hashchange", function () {
      const name = location.hash.replace("#", "");
      if (buttons.some(function (button) {
        return button.getAttribute("data-tab") === name;
      })) {
        activateTab(name, false);
      }
    });
  }

  bindTabs();
  Promise.all([
    fetchJson("hero"),
    fetchJson("bugs"),
    fetchJson("benchmark"),
    fetchJson("repros"),
    fetchJson("replay"),
    fetchJson("copy"),
  ])
    .then(function (documents) {
      const hero = documents[0];
      const bugs = documents[1];
      const benchmark = documents[2];
      const repros = documents[3];
      const replay = documents[4];
      const copy = documents[5];
      state.bugs = bugs;
      renderHero(hero, copy, replay);
      renderHowBeam(copy);
      renderWhy(benchmark.ablation, copy);
      renderChips(bugs);
      renderBugs();
      renderBenchmark(benchmark, hero, copy);
      renderRepros(repros);
      renderReplay(replay);
      renderCopy(copy);
    })
    .catch(function (error) {
      $("headline").textContent = "Could not load recorded results: " + error.message;
    });
})();
