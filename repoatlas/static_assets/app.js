(function () {
  "use strict";

  const state = { bugs: [] };

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

  function percent(value) {
    const pct = value <= 1 ? value * 100 : value;
    return Math.abs(pct - Math.round(pct)) < 0.05 ? Math.round(pct) + "%" : pct.toFixed(1) + "%";
  }

  function renderHero(hero) {
    $("headline").textContent = hero.headline + ".";
    $("hero-note").textContent = hero.label_note;
    const tiles = [
      [hero.hybrid_true, "Real docs bugs, checked against the source by an AI reviewer"],
      [percent(hero.hybrid_precision), "of flagged findings were real (" + hero.hybrid_true_findings + " / " + hero.hybrid_findings + ")"],
      [hero.repro_true, "Reproduce an API error when you run the docs"],
      [hero.rejected_true + " of " + hero.true_candidates_judged, "Real bugs Beam's triage threw away"],
    ];
    $("tiles").innerHTML = tiles
      .map(function (tile) {
        return "<div class='tile'><strong>" + tile[0] + "</strong><span>" + tile[1] + "</span></div>";
      })
      .join("");
  }

  function renderHowBeam(copy) {
    $("how-beam").innerHTML = copy.how_beam.map(function (item) {
      return "<li>" + item + "</li>";
    }).join("");
  }

  function uniqueLibraries(bugs) {
    const names = {};
    bugs.forEach(function (bug) {
      names[bug.library] = true;
    });
    return Object.keys(names).sort();
  }

  function renderLibraryFilter(bugs) {
    const select = $("library-filter");
    select.innerHTML = "<option value='all'>All libraries</option>" + uniqueLibraries(bugs)
      .map(function (name) {
        return "<option value='" + name + "'>" + name + "</option>";
      })
      .join("");
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

  function renderBugs() {
    const library = $("library-filter").value;
    const badge = $("badge-filter").value;
    const html = state.bugs
      .filter(function (bug) {
        return matchesFilter(bug, library, badge);
      })
      .map(function (bug) {
        const doc = bug.doc_path
          ? (bug.doc_url
            ? "<a href='" + bug.doc_url + "'>" + bug.doc_path + (bug.doc_line ? ":" + bug.doc_line : "") + "</a>"
            : bug.doc_path + (bug.doc_line ? ":" + bug.doc_line : ""))
          : "not recorded";
        const code = bug.code_path
          ? (bug.code_url
            ? "<a href='" + bug.code_url + "'>" + bug.code_path + (bug.code_line ? ":" + bug.code_line : "") + "</a>"
            : bug.code_path + (bug.code_line ? ":" + bug.code_line : ""))
          : "not recorded";
        const upstream = bug.upstream
          ? "<span class='pill pill-open'>" +
            (bug.upstream.url ? "<a href='" + bug.upstream.url + "'>" + bug.upstream.label + "</a>" : bug.upstream.label) +
            "</span>"
          : "";
        return (
          "<article class='card'>" +
          "<span class='pill pill-" + bug.badge + "'>" + bug.badge + "</span>" +
          (bug.finder ? "<span class='pill'>" + bug.finder + "</span>" : "") +
          upstream +
          "<h3>" + bug.title + "</h3>" +
          "<p>" + bug.summary + "</p>" +
          "<p class='meta'><b>Doc</b> " + doc + "<br><b>Code</b> " + code +
          (bug.ref ? "<br><b>Commit</b> " + bug.ref : "") +
          (bug.badge_note ? "<br>" + bug.badge_note : "") +
          (bug.upstream && bug.upstream.note ? "<br>" + bug.upstream.note : "") +
          "</p></article>"
        );
      })
      .join("");
    $("bug-grid").innerHTML = html || "<p>No cards match this filter.</p>";
  }

  function renderBenchmark(benchmark) {
    const table = $("compare-table");
    table.innerHTML =
      "<thead><tr>" +
      benchmark.headers.map(function (header) {
        return "<th>" + header + "</th>";
      }).join("") +
      "</tr></thead><tbody>" +
      benchmark.rows
        .map(function (row) {
          return (
            "<tr>" +
            row
              .map(function (cell) {
                return "<td>" + cell + "</td>";
              })
              .join("") +
            "</tr>"
          );
        })
        .join("") +
      "</tbody>";
    $("funnel").innerHTML = benchmark.funnel
      .map(function (step) {
        return "<li><b>" + step.step + ":</b> " + step.true + " true. " + step.detail + "</li>";
      })
        .join("");
    const ablation = benchmark.ablation || {};
    if (ablation.available) {
      $("ablation-claim").textContent = ablation.claim;
      $("ablation-table").innerHTML =
        "<thead><tr>" +
        ablation.headers.map(function (header) {
          return "<th>" + header + "</th>";
        }).join("") +
        "</tr></thead><tbody>" +
        ablation.rows
          .map(function (row) {
            return (
              "<tr>" +
              row
                .map(function (cell) {
                  return "<td>" + cell + "</td>";
                })
                .join("") +
              "</tr>"
            );
          })
          .join("") +
        "</tbody>";
      $("ablation-caveats").innerHTML = (ablation.caveats || [])
        .map(function (item) {
          return "<li>" + item + "</li>";
        })
        .join("");
    }
    const recall = benchmark.recall;
    $("recall-note").textContent =
      "Separate planted-drift distance probe, not a triage-accuracy result. Beam accepted prompts up to " +
      formatNumber(recall.max_probe_tokens) +
      " tokens. Focused whole-context passes hit " +
      recall.far_hits[0] +
      "/" +
      recall.far_hits[1] +
      " planted drifts 700k+ tokens apart vs " +
      recall.chunk_far[0] +
      "/" +
      recall.chunk_far[1] +
      " for chunked 128k, seed 1 only, at ~" +
      recall.focused_multiplier +
      "× tokens (" +
      formatNumber(recall.focused_tokens) +
      " vs ~" +
      (recall.chunk_baseline_tokens / 1000000).toFixed(1) +
      "M). " +
      recall.docstring_pooled +
      ".";
    if (benchmark.chart_present) {
      const image = $("recall-chart");
      image.src = benchmark.recall.chart;
      image.hidden = false;
    }
    $("benchmark-notes").textContent = benchmark.notes_markdown;
  }

  function renderRepros(repros) {
    $("repro-table").innerHTML =
      "<thead><tr><th>Id</th><th>Library</th><th>Verdict</th><th>Status</th><th>Strict</th><th>Error</th></tr></thead><tbody>" +
      repros
        .map(function (row) {
          return (
            "<tr><td>" +
            row.id +
            "</td><td>" +
            row.library +
            "</td><td>" +
            row.verdict +
            "</td><td>" +
            row.status +
            "</td><td>" +
            (row.strict_confirmed ? "yes" : "no") +
            "</td><td>" +
            (row.error_excerpt || row.exception_type || "") +
            "</td></tr>"
          );
        })
        .join("") +
      "</tbody>";
  }

  function renderReplay(replay) {
    $("replay-banner").innerHTML =
      "<b>Recording</b> of the real starlette pack. " +
      formatNumber(replay.prompt_tokens) +
      " prompt tokens, " +
      formatNumber(replay.completion_tokens) +
      " completion tokens, packed " +
      replay.recorded_at +
      ". " +
      replay.candidate_count +
      " candidates (" +
      replay.symbol_candidates +
      " symbol check + " +
      replay.whole_candidates +
      " whole-repo pass). Kept " +
      replay.kept +
      ", rejected " +
      replay.rejected +
      ". Source " +
      replay.trace_path +
      ".";
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
          item.claim +
          "</li>"
        );
      })
      .join("");
    $("player-verdicts").innerHTML = (replay.candidates || [])
      .map(function (item) {
        const site = item.code_path
          ? item.code_path + (item.code_line ? ":" + item.code_line : "")
          : "no code cite";
        return (
          "<li><b>" +
          item.id +
          " → " +
          item.verdict +
          "</b> " +
          site +
          ". " +
          item.reason +
          "</li>"
        );
      })
      .join("");
    $("player-repro-note").textContent = replay.repro_note || "";
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
    $("player-pr").innerHTML = pr.url
      ? '<a href="' + pr.url + '">' + pr.label + "</a> — " + (pr.note || "")
      : "";
  }

  function renderCopy(copy) {
    $("ollama-key").textContent = copy.ollama_key;
    $("local-cmd").textContent = copy.local;
    $("cli-cmd").textContent = copy.cli;
    if ($("sweep-cmd")) {
      $("sweep-cmd").textContent = copy.cli_sweep || "";
    }
    $("limits-list").innerHTML = copy.limits
      .map(function (item) {
        return "<li>" + item + "</li>";
      })
      .join("");
    $("exclusions-list").innerHTML = (copy.exclusions || [])
      .map(function (item) {
        return "<li>" + item + "</li>";
      })
      .join("");
    $("glossary-list").innerHTML = (copy.glossary || [])
      .map(function (item) {
        return "<li>" + item + "</li>";
      })
      .join("");
    $("sources").textContent = "Sources: " + copy.sources.join("; ");
  }

  function bindTabs() {
    const buttons = document.querySelectorAll(".tab");
    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        const name = button.getAttribute("data-tab");
        buttons.forEach(function (other) {
          other.classList.toggle("is-active", other === button);
        });
        document.querySelectorAll(".panel").forEach(function (panel) {
          panel.classList.toggle("is-active", panel.id === name);
        });
      });
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
      renderHero(hero);
      renderHowBeam(copy);
      renderLibraryFilter(bugs);
      renderBugs();
      renderBenchmark(benchmark);
      renderRepros(repros);
      renderReplay(replay);
      renderCopy(copy);
      $("library-filter").addEventListener("change", renderBugs);
      $("badge-filter").addEventListener("change", renderBugs);
    })
    .catch(function (error) {
      $("headline").textContent = "Could not load recorded results: " + error.message;
    });
})();
