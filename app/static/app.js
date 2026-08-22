/**
 * TraceGraph AI — Frontend Client Application
 * Autonomous Web Crawler Control Center, Vis.js Knowledge Graph, and Blast Radius Reasoning.
 */

let network = null;
let currentReport = null;
let currentCrawlId = null;
let crawlEventSource = null;
let crawlTimerInterval = null;

function fitKnowledgeGraph(animated = true) {
  if (!network) return false;
  const container = document.getElementById("networkGraph");
  if (!container || container.clientWidth === 0 || container.clientHeight === 0) return false;

  // Vis.js measures a hidden tab as 0×0.  Resizing and redrawing before fit
  // makes the control reliable both after switching tabs and after a graph
  // reload.
  network.setSize("100%", "100%");
  network.redraw();
  requestAnimationFrame(() => {
    network.fit({ animation: animated ? { duration: 400, easingFunction: "easeInOutQuad" } : false });
  });
  return true;
}
let crawlStartTime = null;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  }[char]));
}

function safeExternalUrl(value) {
  try {
    const url = new URL(value);
    return (url.protocol === "https:" || url.protocol === "http:") ? url.href : "#";
  } catch (_) {
    return "#";
  }
}

function safeIdentifier(value) {
  return /^[A-Za-z0-9_.-]+$/.test(String(value)) ? String(value) : "";
}

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initPipelineSteps();
  initCrawlControls();
  initSpecIngestControls();
  initPRControls();
  loadInitialData();
  loadIngestedRequirements();
  loadDocumentSourcePolicy();
  setAnalysisUnavailable("No provenance-verified report has been loaded.");
});

// ─────────────────────────────────────────────────────────────
// 1. Tab & Pipeline Step Navigation
// ─────────────────────────────────────────────────────────────
function initTabs() {
  const tabs = document.querySelectorAll(".tab-item");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");

      const targetId = tab.getAttribute("data-tab");
      document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
      const panel = document.getElementById(targetId);
      if (panel) panel.classList.add("active");

      // Sync pipeline flow bar
      document.querySelectorAll(".pipeline-step").forEach(s => {
        if (s.getAttribute("data-tab") === targetId) {
          s.classList.add("active");
        } else {
          s.classList.remove("active");
        }
      });

      if (targetId === "graphView" && network) {
        setTimeout(() => fitKnowledgeGraph(false), 50);
      }
      if (targetId === "sessionsView") {
        loadCrawlSessions();
      }
      if (targetId === "ingestView") {
        loadIngestedRequirements();
      }
    });
  });
}

function initPipelineSteps() {
  const steps = document.querySelectorAll(".pipeline-step");
  steps.forEach(step => {
    step.addEventListener("click", () => {
      const targetTab = step.getAttribute("data-tab");
      const matchingTabBtn = document.querySelector(`.tab-item[data-tab="${targetTab}"]`);
      if (matchingTabBtn) matchingTabBtn.click();
    });
  });
}

// ─────────────────────────────────────────────────────────────
// 2. Autonomous Crawler Control Center
// ─────────────────────────────────────────────────────────────
function initCrawlControls() {
  // Sliders
  const depthSlider = document.getElementById("crawlMaxDepth");
  const actionsSlider = document.getElementById("crawlMaxActions");
  const statesSlider = document.getElementById("crawlMaxStates");

  if (depthSlider) {
    depthSlider.addEventListener("input", (e) => {
      document.getElementById("valMaxDepth").innerText = e.target.value;
    });
  }
  if (actionsSlider) {
    actionsSlider.addEventListener("input", (e) => {
      document.getElementById("valMaxActions").innerText = e.target.value;
    });
  }
  if (statesSlider) {
    statesSlider.addEventListener("input", (e) => {
      document.getElementById("valMaxStates").innerText = e.target.value;
    });
  }
  // Presets
  // Validate URL button
  const btnValidate = document.getElementById("btnValidateUrl");
  if (btnValidate) {
    btnValidate.addEventListener("click", () => {
      const url = document.getElementById("inputCrawlUrl").value.trim();
      validateUrl(url);
    });
  }

  // Start Crawl (Live Browser)
  const btnStart = document.getElementById("btnStartCrawl");
  if (btnStart) {
    btnStart.addEventListener("click", startAutonomousCrawl);
  }

  // Cancel Crawl
  const btnCancel = document.getElementById("btnCancelCrawl");
  if (btnCancel) {
    btnCancel.addEventListener("click", cancelCrawl);
  }

  // Post Crawl Toolbar buttons
  const btnViewScreens = document.getElementById("btnViewScreens");
  if (btnViewScreens) {
    btnViewScreens.addEventListener("click", () => viewDiscoveredScreens(currentCrawlId));
  }

  const btnViewTrans = document.getElementById("btnViewTransitions");
  if (btnViewTrans) {
    btnViewTrans.addEventListener("click", () => viewDiscoveredTransitions(currentCrawlId));
  }

  const btnApplyGraph = document.getElementById("btnApplyCrawlToGraph");
  if (btnApplyGraph) {
    btnApplyGraph.addEventListener("click", () => applyCrawlToGraph(currentCrawlId));
  }

  const btnRefreshSessions = document.getElementById("btnRefreshSessions");
  if (btnRefreshSessions) {
    btnRefreshSessions.addEventListener("click", loadCrawlSessions);
  }
}

// ─────────────────────────────────────────────────────────────
// 2.5 Specification Ingestion Controls (Step 2)
// ─────────────────────────────────────────────────────────────
function initSpecIngestControls() {
  const sourceModeInputs = document.querySelectorAll("input[name='specSourceMode']");
  sourceModeInputs.forEach(input => input.addEventListener("change", syncSpecSourceMode));
  syncSpecSourceMode();

  const btnIngest = document.getElementById("btnIngestSpec");
  if (btnIngest) {
    btnIngest.addEventListener("click", async () => {
      btnIngest.disabled = true;
      btnIngest.innerText = "Ingesting...";
      try {
        const sourceMode = document.querySelector("input[name='specSourceMode']:checked")?.value;
        const sourceUrl = sourceMode === "url" ? document.getElementById("inputSpecUrl").value.trim() : "";
        const sourceText = sourceMode === "text" ? document.getElementById("specTextInput").value.trim() : "";
        if (sourceMode === "url" && !sourceUrl) throw new Error("Paste a public GitHub README or documentation URL.");
        if (sourceMode === "text" && !sourceText) throw new Error("Paste the requirement text to extract requirements.");
        const res = await fetch("/api/ingest", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_urls: sourceUrl ? [sourceUrl] : [], source_text: sourceText })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Specification ingestion failed.");
        document.getElementById("specSourceBadge").innerText = "Public source ingested";
        document.getElementById("specSourceBadge").className = "badge badge-success";
        document.getElementById("ingestCountDisplay").innerText = `${data.requirements_ingested} requirements`;
        document.getElementById("specCategoriesDisplay").innerText = (data.categories || []).join(", ") || "—";
        await loadIngestedRequirements();
      } catch (err) {
        document.getElementById("specSourceBadge").innerText = `Ingestion failed: ${err.message}`;
        document.getElementById("specSourceBadge").className = "badge badge-danger";
      } finally {
        btnIngest.disabled = false;
        btnIngest.innerHTML = "<i data-lucide='sparkles'></i> <span>Ingest & Extract Requirements</span>";
        lucide.createIcons();
      }
    });
  }
}

function syncSpecSourceMode() {
  const sourceMode = document.querySelector("input[name='specSourceMode']:checked")?.value || "url";
  const urlGroup = document.getElementById("specUrlGroup");
  const textGroup = document.getElementById("specTextGroup");
  const urlInput = document.getElementById("inputSpecUrl");
  const textInput = document.getElementById("specTextInput");
  const useUrl = sourceMode === "url";
  urlGroup?.classList.toggle("hidden", !useUrl);
  textGroup?.classList.toggle("hidden", useUrl);
  if (urlInput) urlInput.disabled = !useUrl;
  if (textInput) textInput.disabled = useUrl;
}

async function loadDocumentSourcePolicy() {
  const target = document.getElementById("specUrlPolicy");
  if (!target) return;
  try {
    const response = await fetch("/api/config/document-sources");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Source policy is unavailable.");
    const hosts = (data.allowed_hosts || []).map(escapeHtml);
    target.innerText = hosts.length
      ? `Approved URL hosts: ${hosts.join(", ")}. Use Paste Markdown for another source.`
      : "URL sources are unavailable. Use Paste Markdown instead.";
  } catch (_) {
    target.innerText = "URL policy is unavailable. Paste the requirement text instead.";
  }
}

async function loadIngestedRequirements() {
  try {
    const res = await fetch("/api/requirements");
    const data = await res.json();
    const reqs = data.requirements || [];
    const tbody = document.querySelector("#tableIngestedReqs tbody");
    if (tbody) {
      tbody.innerHTML = "";
      if (reqs.length === 0) {
        tbody.innerHTML = "<tr><td colspan='5' class='text-muted'>No real specification has been ingested yet.</td></tr>";
        return;
      }
      const categories = [...new Set(reqs.map(r => r.category).filter(Boolean))].sort();
      const averageScore = reqs.reduce((total, r) => total + (Number(r.testability_score) || 0), 0) / reqs.length;
      const sourceKinds = new Set(reqs.map(r => r.source_url === "inline://operator-submitted" ? "Pasted specification" : "Public URL"));
      document.getElementById("ingestCountDisplay").innerText = `${reqs.length} requirements`;
      document.getElementById("specCategoriesDisplay").innerText = categories.join(", ") || "—";
      document.getElementById("ingestScoreDisplay").innerText = `${averageScore.toFixed(2)} / 1.0`;
      document.getElementById("specSourceBadge").innerText = [...sourceKinds].join(" + ");
      document.getElementById("specSourceBadge").className = "badge badge-success";
      reqs.forEach(r => {
        const row = document.createElement("tr");
        const statusBadge = r.coverage_status === "COVERED" 
          ? '<span class="badge badge-success">COVERED</span>' 
          : (r.coverage_status === "PARTIAL" ? '<span class="badge badge-warning">PARTIAL</span>'
            : (r.coverage_status === "ABSENT" ? '<span class="badge badge-danger">ABSENT</span>' : '<span class="badge badge-unverified">UNVERIFIED</span>'));
        const coverageHint = r.coverage_status === "UNVERIFIED"
          ? "<small class='text-muted'>Awaiting matching crawl + graph build</small>"
          : "";
        row.innerHTML = `
          <td><strong>${escapeHtml(r.id)}</strong></td>
          <td><code>${escapeHtml(r.category)}</code></td>
          <td>${escapeHtml(r.text)}</td>
          <td><code>${escapeHtml(r.testability_score)}</code></td>
          <td>${statusBadge}<br>${coverageHint}</td>
        `;
        tbody.appendChild(row);
      });
    }
  } catch (err) {
    const tbody = document.querySelector("#tableIngestedReqs tbody");
    if (tbody) tbody.innerHTML = "<tr><td colspan='5' class='text-muted'>No real specification has been ingested yet.</td></tr>";
  }
}

function customPublicHostEnabled() {
  return document.getElementById("allowCustomPublicHost")?.checked ?? false;
}

async function readApiError(response, fallbackMessage) {
  const responseText = await response.text();
  try {
    const payload = JSON.parse(responseText);
    if (payload && typeof payload.detail === "string") return payload.detail;
  } catch (_) {
    // A reverse proxy can return an HTML/plain-text error page. Do not expose
    // its contents or turn it into a misleading JSON parser error in the UI.
  }
  return `${fallbackMessage} (HTTP ${response.status}).`;
}

async function validateUrl(url) {
  const msgEl = document.getElementById("urlValidationMsg");
  if (!url) {
    msgEl.innerHTML = "<span class='url-invalid'>Please enter a valid URL</span>";
    return;
  }
  msgEl.innerHTML = "<span class='text-muted'>Checking security and SSRF boundaries...</span>";

  try {
    const res = await fetch("/api/crawl/validate-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, allow_custom_public_host: customPublicHostEnabled() }),
    });
    if (!res.ok) {
      throw new Error(await readApiError(res, "URL validation could not be completed"));
    }
    const data = await res.json();
    if (data.valid) {
      msgEl.innerHTML = `<span class='url-valid'>✓ Valid Target: ${escapeHtml(data.hostname || "URL Safe")} (${escapeHtml((data.resolved_ips || []).join(", ") || "Whitelisted")})</span>`;
    } else {
      msgEl.innerHTML = `<span class='url-invalid'>✕ Blocked: ${escapeHtml(data.reason)}</span>`;
    }
  } catch (err) {
    msgEl.innerHTML = `<span class='url-invalid'>Validation error: ${escapeHtml(err.message)}</span>`;
  }
}

async function startAutonomousCrawl() {
  const url = document.getElementById("inputCrawlUrl").value.trim();
  const maxDepth = parseInt(document.getElementById("crawlMaxDepth").value, 10) || 4;
  const maxActions = parseInt(document.getElementById("crawlMaxActions").value, 10) || 40;
  const maxStates = parseInt(document.getElementById("crawlMaxStates").value, 10) || 20;
  const captureScreenshots = document.getElementById("crawlCaptureScreenshots").checked;
  const captureDom = document.getElementById("crawlCaptureDom").checked;
  const autonomous = document.getElementById("crawlAutonomous").checked;
  const sameDomainOnly = true;

  const btnStart = document.getElementById("btnStartCrawl");
  const btnCancel = document.getElementById("btnCancelCrawl");
  const dot = document.getElementById("crawlStatusDot");
  const statusText = document.getElementById("crawlStatusText");
  const feed = document.getElementById("crawlEventFeed");
  const toolbar = document.getElementById("crawlPostToolbar");

  feed.innerHTML = "";
  toolbar.classList.add("hidden");
  btnStart.classList.add("hidden");
  btnCancel.classList.remove("hidden");

  dot.className = "status-dot running";
  statusText.innerText = "RUNNING ●";

  // Reset live stats
  document.getElementById("liveStatPages").innerText = "0";
  document.getElementById("liveStatStates").innerText = "0";
  document.getElementById("liveStatActions").innerText = "0";
  document.getElementById("liveStatTransitions").innerText = "0";
  document.getElementById("liveCurrentScreen").innerText = "Connecting...";
  document.getElementById("liveCurrentAction").innerText = "Initializing browser session...";

  // Start timer
  crawlStartTime = Date.now();
  if (crawlTimerInterval) clearInterval(crawlTimerInterval);
  crawlTimerInterval = setInterval(updateCrawlTimer, 1000);

  appendFeedLine("SYSTEM", `Initiating autonomous crawl against ${url}`);

  try {
    const res = await fetch("/api/crawl", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        allow_custom_public_host: customPublicHostEnabled(),
        max_depth: maxDepth,
        max_actions: maxActions,
        max_states: maxStates,
        max_runtime_seconds: 600,
        same_domain_only: sameDomainOnly,
        capture_dom: captureDom,
        capture_screenshots: captureScreenshots,
        autonomous: autonomous,
      }),
    });

    if (!res.ok) {
      const message = await readApiError(res, "The crawl could not be started");
      const error = new Error(message);
      if (res.status === 503 && message.includes("Vercel serverless runtime")) {
        error.code = "BROWSER_WORKER_REQUIRED";
      }
      throw error;
    }

    const data = await res.json();
    currentCrawlId = data.crawl_id;
    appendFeedLine("SYSTEM", `Crawl Session queued ID: ${currentCrawlId}`);

    // Connect to SSE stream
    subscribeToCrawlEvents(currentCrawlId);
  } catch (err) {
    appendFeedLine("ERROR", `Failed: ${err.message}`);
    if (err.code === "BROWSER_WORKER_REQUIRED") {
      document.getElementById("liveCurrentScreen").innerText = "Dedicated browser worker required";
      document.getElementById("liveCurrentAction").innerText = "Run the Docker deployment for evidence capture";
      stopCrawlUI("WORKER REQUIRED");
    } else {
      stopCrawlUI("FAILED");
    }
  }
}

function subscribeToCrawlEvents(crawlId) {
  if (crawlEventSource) {
    crawlEventSource.close();
  }

  crawlEventSource = new EventSource(`/api/crawl/${crawlId}/events`);

  crawlEventSource.onmessage = (event) => {
    try {
      const evt = JSON.parse(event.data);
      handleCrawlEvent(evt);
    } catch (e) {
      console.error("SSE parse error", e);
    }
  };

  crawlEventSource.onerror = () => {
    // SSE stream ended or connection closed
    if (crawlEventSource) {
      crawlEventSource.close();
      crawlEventSource = null;
    }
  };
}

function handleCrawlEvent(evt) {
  const type = evt.type;
  const msg = evt.message || "";
  const data = evt.data || {};

  appendFeedLine(type, msg);

  if (type === "page_discovered") {
    const cnt = parseInt(document.getElementById("liveStatPages").innerText, 10) + 1;
    document.getElementById("liveStatPages").innerText = cnt;
    document.getElementById("liveStatStates").innerText = cnt;
    document.getElementById("liveCurrentScreen").innerText = data.title || data.url || "Discovered Screen";
  } else if (type === "action_selected") {
    const cnt = parseInt(document.getElementById("liveStatActions").innerText, 10) + 1;
    document.getElementById("liveStatActions").innerText = cnt;
    document.getElementById("liveCurrentAction").innerText = data.action_label || msg;
  } else if (type === "transition_created") {
    const cnt = parseInt(document.getElementById("liveStatTransitions").innerText, 10) + 1;
    document.getElementById("liveStatTransitions").innerText = cnt;
  } else if (type === "crawl_completed") {
    stopCrawlUI("COMPLETED ✓");
    document.getElementById("crawlPostToolbar").classList.remove("hidden");
    if (data.pages) document.getElementById("liveStatPages").innerText = data.pages;
    if (data.transitions) document.getElementById("liveStatTransitions").innerText = data.transitions;
  } else if (type === "crawl_failed" || type === "crawl_cancelled" || type === "crawl_timeout") {
    stopCrawlUI(type.replace("crawl_", "").toUpperCase());
  }
}

function updateCrawlTimer() {
  if (!crawlStartTime) return;
  const elapsedSec = Math.floor((Date.now() - crawlStartTime) / 1000);
  const mins = String(Math.floor(elapsedSec / 60)).padStart(2, "0");
  const secs = String(elapsedSec % 60).padStart(2, "0");
  document.getElementById("crawlTimer").innerText = `${mins}:${secs}`;
}

function stopCrawlUI(status) {
  if (crawlTimerInterval) {
    clearInterval(crawlTimerInterval);
    crawlTimerInterval = null;
  }
  if (crawlEventSource) {
    crawlEventSource.close();
    crawlEventSource = null;
  }

  const dot = document.getElementById("crawlStatusDot");
  const statusText = document.getElementById("crawlStatusText");
  const btnStart = document.getElementById("btnStartCrawl");
  const btnCancel = document.getElementById("btnCancelCrawl");

  dot.className = status.includes("COMPLETED") ? "status-dot completed" : "status-dot";
  statusText.innerText = status;
  btnStart.classList.remove("hidden");
  btnCancel.classList.add("hidden");
}

async function cancelCrawl() {
  if (!currentCrawlId) return;
  try {
    await fetch(`/api/crawl/${currentCrawlId}/cancel`, { method: "POST" });
    appendFeedLine("SYSTEM", "User requested crawl cancellation");
    stopCrawlUI("CANCELLED");
  } catch (err) {
    console.error("Cancel failed", err);
  }
}

function appendFeedLine(type, msg) {
  const feed = document.getElementById("crawlEventFeed");
  if (!feed) return;
  const now = new Date();
  const timeStr = now.toTimeString().split(" ")[0];

  const line = document.createElement("div");
  line.className = "term-line";

  let typeClass = "";
  if (type.includes("page")) typeClass = "term-evt-page";
  else if (type.includes("action")) typeClass = "term-evt-action";
  else if (type.includes("trans")) typeClass = "term-evt-trans";
  else if (type.includes("shot") || type.includes("dom")) typeClass = "term-evt-shot";

  line.innerHTML = `<span class="term-time">[${timeStr}]</span> <span class="${typeClass}">[${escapeHtml(type.toUpperCase())}]</span> ${escapeHtml(msg)}`;
  feed.appendChild(line);
  feed.scrollTop = feed.scrollHeight;
}

// ─────────────────────────────────────────────────────────────
// 3. Artifact Viewers & Sessions
// ─────────────────────────────────────────────────────────────
async function viewDiscoveredScreens(crawlId) {
  const crawlTabBtn = document.querySelector(".tab-item[data-tab='crawlView']");
  if (crawlTabBtn) crawlTabBtn.click();

  const sec = document.getElementById("discoveredArtifactsSection");
  const gallery = document.getElementById("screensGallery");
  const transWrap = document.getElementById("transitionsWrap");
  const title = document.getElementById("artifactsSectionTitle");

  sec.classList.remove("hidden");
  gallery.classList.remove("hidden");
  transWrap.classList.add("hidden");
  title.innerText = `Discovered Screens & Screenshots (${crawlId || "Active"})`;
  gallery.innerHTML = "<p class='text-muted'>Loading screen artifacts...</p>";

  try {
    const res = await fetch(crawlId ? `/api/crawl/${crawlId}/pages` : "/api/crawl/pages");
    const data = await res.json();
    gallery.innerHTML = "";

    if (!data.pages || data.pages.length === 0) {
      gallery.innerHTML = "<p class='text-muted'>No screens recorded for this crawl session yet.</p>";
      document.getElementById("crawlSessionBadge").innerText = "0 Screens Captured";
      return;
    }

    document.getElementById("crawlSessionBadge").innerText = `${data.pages.length} Screens Captured`;
    document.getElementById("crawlSessionBadge").className = "badge badge-success";

    (data.pages || []).forEach(p => {
      const card = document.createElement("div");
      card.className = "screen-card";
      const sessionId = safeIdentifier(crawlId);
      const pageId = safeIdentifier(p.id);
      if (!sessionId || !pageId) return;
      const shotUrl = `/api/crawl/${sessionId}/artifacts/screenshots/${pageId}.png`;
      const domUrl = `/api/crawl/${sessionId}/artifacts/dom/${pageId}.html`;
      const pageUrl = safeExternalUrl(p.url);

      card.innerHTML = `
        <a href="${shotUrl}" target="_blank" rel="noopener noreferrer" title="Click to view full screenshot">
          <img src="${shotUrl}" class="screen-thumb" alt="${escapeHtml(p.title)}">
        </a>
        <div class="screen-card-body">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <span class="screen-id">${escapeHtml(p.id)}</span>
            <span class="badge badge-subtle">Depth ${p.depth ?? 1}</span>
          </div>
          <div class="screen-title" style="margin-top: 4px; font-weight: 700; color: var(--text-primary);">${escapeHtml(p.title)}</div>
          <div class="screen-meta"><small><a href="${escapeHtml(pageUrl)}" target="_blank" rel="noopener noreferrer" style="color: #38bdf8; word-break: break-all;">${escapeHtml(p.url)}</a></small></div>
          <div class="screen-meta" style="margin-top: 10px; display: flex; gap: 6px;">
            <a href="${shotUrl}" target="_blank" rel="noopener noreferrer" class="btn btn-tool" style="font-size: 0.72rem; padding: 3px 8px;">View Screenshot</a>
            <a href="${domUrl}" target="_blank" rel="noopener noreferrer" class="btn btn-tool" style="font-size: 0.72rem; padding: 3px 8px;">Download DOM</a>
          </div>
        </div>
      `;
      gallery.appendChild(card);
    });
    setTimeout(() => sec.scrollIntoView({ behavior: "smooth" }), 100);
  } catch (err) {
    gallery.innerHTML = `<p class='text-rose'>Error loading screens: ${escapeHtml(err.message)}</p>`;
  }
}

async function viewDiscoveredTransitions(crawlId) {
  const crawlTabBtn = document.querySelector(".tab-item[data-tab='crawlView']");
  if (crawlTabBtn) crawlTabBtn.click();

  const sec = document.getElementById("discoveredArtifactsSection");
  const gallery = document.getElementById("screensGallery");
  const transWrap = document.getElementById("transitionsWrap");
  const tbody = document.querySelector("#tableDiscoveredTransitions tbody");
  const title = document.getElementById("artifactsSectionTitle");

  sec.classList.remove("hidden");
  gallery.classList.add("hidden");
  transWrap.classList.remove("hidden");
  title.innerText = `Discovered Concrete Screen Transitions (${crawlId || "Active"})`;
  tbody.innerHTML = "";

  try {
    const res = await fetch(crawlId ? `/api/crawl/${crawlId}/transitions` : "/api/crawl/transitions");
    const data = await res.json();

    if (!data.transitions || data.transitions.length === 0) {
      tbody.innerHTML = "<tr><td colspan='5' class='text-muted'>No transitions recorded for this session.</td></tr>";
      return;
    }

    (data.transitions || []).forEach(t => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td><code>${escapeHtml(t.id)}</code></td>
        <td><strong>${escapeHtml(t.from_page_id)}</strong></td>
        <td><span class="badge badge-partial">${escapeHtml(t.action_label)}</span></td>
        <td><strong>${escapeHtml(t.to_page_id)}</strong></td>
        <td><code>${escapeHtml(t.interaction_type)}</code></td>
      `;
      tbody.appendChild(row);
    });
    setTimeout(() => sec.scrollIntoView({ behavior: "smooth" }), 100);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-rose">Error loading transitions: ${escapeHtml(err.message)}</td></tr>`;
  }
}

async function applyCrawlToGraph(crawlId) {
  if (!crawlId) return;
  const repoInput = document.getElementById("inputRepo");
  const prInput = document.getElementById("inputPRNumber");
  const repo = repoInput.value.trim();
  const prNumber = Number.parseInt(prInput.value, 10);
  if (!repo || !Number.isInteger(prNumber)) {
    appendFeedLine("ERROR", "A GitHub repository and real PR number are required before building the three-layer graph.");
    repoInput.focus();
    showGraphSetupMessage("Enter the matching GitHub repository and PR in the left panel, then build the three-layer graph.");
    return;
  }

  const applyButton = document.getElementById("btnApplyCrawlToGraph");
  if (applyButton?.disabled) return;
  if (applyButton) {
    applyButton.disabled = true;
    applyButton.innerHTML = "<i data-lucide='loader-circle'></i><span>Building…</span>";
    lucide.createIcons();
  }
  try {
    appendFeedLine("SYSTEM", `Staging discovered artifacts from ${crawlId} for graph construction...`);
    const res = await fetch(`/api/crawl/${crawlId}/apply-to-graph`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not stage crawl evidence.");
    appendFeedLine("SYSTEM", data.message || "Crawl evidence staged.");

    appendFeedLine("SYSTEM", `Building Requirements → UI → Code graph for ${repo}#${prNumber}...`);
    const buildResponse = await fetch("/api/build-graph", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pr_number: prNumber, repo, crawl_id: crawlId }),
    });
    const buildData = await buildResponse.json();
    if (!buildResponse.ok) throw new Error(buildData.detail || "Three-layer graph build failed.");
    appendFeedLine("SYSTEM", `Three-layer graph built: ${JSON.stringify(buildData.node_counts || {})}`);

    // Switch only after a complete, provenance-backed graph exists.
    const graphTabBtn = document.querySelector(".tab-item[data-tab='graphView']");
    if (graphTabBtn) graphTabBtn.click();
    await loadKnowledgeGraph(repo, prNumber);
  } catch (err) {
    appendFeedLine("ERROR", `Failed to apply to graph: ${err.message}`);
  } finally {
    if (applyButton) {
      applyButton.disabled = false;
      applyButton.innerHTML = "<i data-lucide='database'></i><span>Build 3-Layer Graph</span>";
      lucide.createIcons();
    }
  }
}

function showGraphSetupMessage(message) {
  const container = document.getElementById("networkGraph");
  if (!container) return;
  container.innerHTML = `<div class="graph-empty-state text-muted">${escapeHtml(message)}</div>`;
}

async function loadCrawlSessions() {
  const tbody = document.querySelector("#tableCrawlSessions tbody");
  if (!tbody) return;
  tbody.innerHTML = "<tr><td colspan='7' class='text-muted'>Loading crawl sessions...</td></tr>";

  try {
    const res = await fetch("/api/crawl/sessions");
    const body = await res.text();
    let data;
    try {
      data = JSON.parse(body);
    } catch {
      throw new Error(`Crawl Sessions API returned HTTP ${res.status}.`);
    }
    if (!res.ok) throw new Error(data.detail || `Crawl Sessions API returned HTTP ${res.status}.`);
    tbody.innerHTML = "";

    const sessions = data.sessions || [];
    if (sessions.length === 0) {
      tbody.innerHTML = "<tr><td colspan='7' class='text-muted'>No crawl sessions recorded yet. Start a crawl above!</td></tr>";
      return;
    }

    sessions.forEach(s => {
      const row = document.createElement("tr");
      const sessionId = safeIdentifier(s.id);
      if (!sessionId) return;
      const status = escapeHtml(s.status);
      const statusBadge = s.status === "COMPLETED" 
        ? '<span class="badge badge-covered">COMPLETED</span>'
        : s.status === "RUNNING"
        ? '<span class="badge badge-partial">RUNNING</span>'
        : `<span class="badge badge-unverified">${status}</span>`;

      row.innerHTML = `
        <td><code>${escapeHtml(sessionId)}</code></td>
        <td><small>${escapeHtml(s.start_url)}</small></td>
        <td>${statusBadge}</td>
        <td><strong>${s.pages_discovered}</strong></td>
        <td><strong>${s.transitions_discovered}</strong></td>
        <td><small>${s.started_at ? s.started_at.split("T")[0] : "—"}</small></td>
        <td>
          <button class="btn btn-tool" data-session-id="${escapeHtml(sessionId)}">Screens</button>
          <button class="btn btn-tool" data-transition-session-id="${escapeHtml(sessionId)}">Transitions</button>
        </td>
      `;
      row.querySelector("[data-session-id]").addEventListener("click", () => viewDiscoveredScreens(sessionId));
      row.querySelector("[data-transition-session-id]").addEventListener("click", () => viewDiscoveredTransitions(sessionId));
      tbody.appendChild(row);
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan='7' class='text-rose'>Error: ${escapeHtml(err.message)}</td></tr>`;
  }
}

// ─────────────────────────────────────────────────────────────
// 4. PR Blast Radius & Knowledge Graph Controls
// ─────────────────────────────────────────────────────────────
function initPRControls() {
  const btnFetch = document.getElementById("btnFetchPR");
  if (btnFetch) {
    btnFetch.addEventListener("click", () => {
      const repo = document.getElementById("inputRepo").value.trim();
      const pr = parseInt(document.getElementById("inputPRNumber").value, 10);
      runPRAnalysis(repo, pr);
    });
  }

  // Preset repo tags
  const presetTags = document.querySelectorAll(".quick-presets .preset-tag");
  presetTags.forEach(tag => {
    tag.addEventListener("click", () => {
      const repo = tag.getAttribute("data-repo");
      const pr = parseInt(tag.getAttribute("data-pr"), 10);
      document.getElementById("inputRepo").value = repo;
      document.getElementById("inputPRNumber").value = pr;
      runPRAnalysis(repo, pr);
    });
  });

    const btnZoomIn = document.getElementById("btnZoomIn");
    if (btnZoomIn) {
      btnZoomIn.addEventListener("click", () => {
        if (network) {
          const scale = network.getScale();
          network.moveTo({ scale: scale * 1.3, animation: { duration: 250 } });
        }
      });
    }

    const btnZoomOut = document.getElementById("btnZoomOut");
    if (btnZoomOut) {
      btnZoomOut.addEventListener("click", () => {
        if (network) {
          const scale = network.getScale();
          network.moveTo({ scale: scale / 1.3, animation: { duration: 250 } });
        }
      });
    }

    const btnFit = document.getElementById("btnFitGraph");
    if (btnFit) {
      btnFit.addEventListener("click", () => {
        fitKnowledgeGraph(true);
      });
    }

    const btnReset = document.getElementById("btnResetPhysics");
    if (btnReset) {
      btnReset.addEventListener("click", () => {
        if (network) network.stabilize();
      });
    }

  const btnDownload = document.getElementById("btnDownloadMd");
  if (btnDownload) {
    btnDownload.addEventListener("click", downloadMarkdownReport);
  }

  const btnReindex = document.getElementById("btnRunPipeline");
  if (btnReindex) {
    btnReindex.addEventListener("click", async () => {
      const repo = document.getElementById("inputRepo").value.trim();
      const pr = parseInt(document.getElementById("inputPRNumber").value, 10);
      if (!currentCrawlId) {
        alert("Run and select a completed crawl before building the knowledge graph.");
        return;
      }
      if (!repo || !Number.isInteger(pr)) {
        setAnalysisUnavailable("Enter the matching GitHub repository and real PR number before building the three-layer graph.");
        document.getElementById("inputRepo").focus();
        return;
      }
      btnReindex.disabled = true;
      btnReindex.innerHTML = "<i data-lucide='refresh-cw'></i> <span>Indexing...</span>";
      try {
        const response = await fetch("/api/build-graph", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pr_number: pr, repo: repo, crawl_id: currentCrawlId }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Graph build failed.");
        await runPRAnalysis(repo, pr);
      } catch (err) {
        console.error("Graph build failed", err);
        setAnalysisUnavailable(err.message);
      } finally {
        btnReindex.disabled = false;
        btnReindex.innerHTML = "<i data-lucide='refresh-cw'></i> <span>Re-Index Graph</span>";
        lucide.createIcons();
      }
    });
  }
}

async function loadInitialData() {
  const backendStatus = document.getElementById("backendStatus");
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error("Health check failed");
    backendStatus.innerText = "API reachable • evidence required";
  } catch (_) {
    backendStatus.innerText = "API unavailable";
  }
}

async function runPRAnalysis(repo, prNumber, force = true) {
  document.getElementById("headerRepo").innerText = repo;
  document.getElementById("headerPR").innerText = `#${prNumber}`;

  try {
    const reportRes = await fetch(`/api/report/${prNumber}?repo=${encodeURIComponent(repo)}${force ? "&force=true" : ""}`);
    const report = await reportRes.json();
    if (!reportRes.ok) throw new Error(report.detail || "A provenance-verified report is unavailable.");
    currentReport = report;

    // Update PR Header Details
    document.getElementById("prTitleDisplay").innerText = report.pr_title || `PR #${prNumber}`;
    const risk = report.overall_risk || "UNASSESSED";
    document.getElementById("prRiskBadge").innerText = `${risk} RISK`;
    document.getElementById("prRiskBadge").className = `badge ${risk === "HIGH" ? "badge-risk-high" : risk === "MEDIUM" ? "badge-warning" : "badge-unverified"}`;

    // Update Top Counters
    const changedFilesCount = Array.isArray(report.changed_files) ? report.changed_files.length : (report.metrics?.changed_files ?? "—");
    const astSymbolsCount = report.metrics?.symbols_count ?? "—";

    document.getElementById("statFiles").innerText = changedFilesCount;
    document.getElementById("statSymbols").innerText = astSymbolsCount;
    document.getElementById("statUI").innerText = (report.impacted_ui_elements || []).length;
    document.getElementById("statReqs").innerText = (report.impacted_requirements || []).length;

    renderBlastRadiusReport(report);
    renderEvidenceChains(report);
    await loadKnowledgeGraph(repo, prNumber);
    await loadRequirementsMatrix();
  } catch (err) {
    console.error("PR Analysis failed", err);
    setAnalysisUnavailable(err.message);
  }
}

function setTableMessage(selector, columnCount, message) {
  const tbody = document.querySelector(selector);
  if (tbody) tbody.innerHTML = `<tr><td colspan="${columnCount}" class="text-muted">${escapeHtml(message)}</td></tr>`;
}

function riskBadge(risk) {
  const normalized = String(risk || "UNASSESSED").toUpperCase();
  const styles = {
    HIGH: ["badge-risk-high", "HIGH"],
    MEDIUM: ["badge-warning", "MEDIUM"],
    LOW: ["badge-success", "LOW"],
  };
  const [className, label] = styles[normalized] || ["badge-unverified", "UNASSESSED"];
  return `<span class="badge ${className}">${label}</span>`;
}

function setAnalysisUnavailable(reason) {
  currentReport = null;
  document.getElementById("prTitleDisplay").innerText = "Evidence graph not ready";
  document.getElementById("prRiskBadge").innerText = "UNASSESSED";
  document.getElementById("prRiskBadge").className = "badge badge-unverified";
  document.getElementById("statFiles").innerText = "—";
  document.getElementById("statSymbols").innerText = "—";
  document.getElementById("statUI").innerText = "—";
  document.getElementById("statReqs").innerText = "—";
  document.getElementById("llmEngineBadge").innerText = "EVIDENCE REQUIRED";
  document.getElementById("llmEngineBadge").className = "badge badge-unverified";
  document.getElementById("llmExecutiveSummary").innerText = `No blast-radius claim was generated. ${reason} Build the graph from the selected PR, a completed crawl, and ingested requirements.`;
  document.getElementById("qaRecContent").innerText = "Crawl the application, ingest its product specification, then build the Neo4j graph before reviewing blast radius.";
  setTableMessage("#tableImpactedUI tbody", 5, "No report available — no UI impact claim has been made.");
  setTableMessage("#tableImpactedFlows tbody", 4, "No report available — no affected-flow claim has been made.");
  setTableMessage("#tableImpactedReqs tbody", 5, "No report available — no requirement-risk claim has been made.");
  const evidence = document.getElementById("evidenceCardsList");
  if (evidence) evidence.innerHTML = `<p class="text-muted">${escapeHtml(reason)}</p>`;
}

function formatMarkdownToHtml(text) {
  if (!text) return "";
  return escapeHtml(text)
    .replace(/^### (.*$)/gim, '<h4 style="color: var(--color-cyan); margin-top: 10px; margin-bottom: 8px; font-weight: 700; font-size: 1.02rem;">$1</h4>')
    .replace(/^## (.*$)/gim, '<h3 style="color: var(--color-cyan); margin-top: 14px; margin-bottom: 10px; font-weight: 700; font-size: 1.1rem;">$1</h3>')
    .replace(/\*\*(.*?)\*\*/gim, '<strong style="color: #f8fafc; font-weight: 700;">$1</strong>')
    .replace(/`([^`]+)`/gim, '<code style="background: #090d16; color: #38bdf8; padding: 2px 6px; border-radius: 4px; border: 1px solid #1e293b; font-family: var(--font-mono); font-size: 0.82rem; font-weight: 600;">$1</code>')
    .replace(/\n\n/gim, '<div style="height: 10px;"></div>')
    .replace(/\n/gim, '<br>');
}

function renderBlastRadiusReport(report) {
  // Populate Live AI Executive Summary
  const summaryEl = document.getElementById("llmExecutiveSummary");
  if (summaryEl) {
    summaryEl.innerHTML = formatMarkdownToHtml(report.summary || "The graph traversal found no impact paths for this PR.");
  }
  document.getElementById("llmEngineBadge").innerText = "GRAPH VERIFIED";
  document.getElementById("llmEngineBadge").className = "badge badge-success";

  // Populate QA Test Recommendation
  const recEl = document.getElementById("qaRecContent");
  if (recEl && report.recommendation) {
    recEl.innerText = report.recommendation;
  }

  // Populate UI table
  const uiTbody = document.querySelector("#tableImpactedUI tbody");
  uiTbody.innerHTML = "";
  (report.impacted_ui_elements || []).forEach(item => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><strong>${escapeHtml(item.label)}</strong></td>
      <td><code>${escapeHtml(item.element_type || "UIElement")}</code></td>
      <td>${riskBadge(item.risk_level)}</td>
      <td><code>${(item.confidence * 100).toFixed(0)}%</code></td>
      <td><small>${escapeHtml((item.evidence_chain || []).slice(-2).join(" → ") || "PR change traversal")}</small></td>
    `;
    uiTbody.appendChild(row);
  });
  if (!uiTbody.children.length) setTableMessage("#tableImpactedUI tbody", 5, "No UI impact paths were found in the verified graph traversal.");

  // Populate Flows table
  const flowTbody = document.querySelector("#tableImpactedFlows tbody");
  flowTbody.innerHTML = "";
  (report.impacted_flows || []).forEach(item => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><code>${escapeHtml(item.item_id)}</code></td>
      <td><strong>${escapeHtml(item.label)}</strong></td>
      <td>${riskBadge(item.risk_level)}</td>
      <td><code>${(item.confidence * 100).toFixed(0)}%</code></td>
    `;
    flowTbody.appendChild(row);
  });
  if (!flowTbody.children.length) setTableMessage("#tableImpactedFlows tbody", 4, "No affected flow paths were found in the verified graph traversal.");

  // Populate Reqs table
  const reqTbody = document.querySelector("#tableImpactedReqs tbody");
  reqTbody.innerHTML = "";
  (report.impacted_requirements || []).forEach(item => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><code>${escapeHtml(item.item_id)}</code></td>
      <td>${escapeHtml(item.label)}</td>
      <td><span class="badge badge-partial">${escapeHtml(item.category || "general")}</span></td>
      <td><code>${(item.confidence * 100).toFixed(0)}%</code></td>
      <td>${riskBadge(item.risk_level)}</td>
    `;
    reqTbody.appendChild(row);
  });
  if (!reqTbody.children.length) setTableMessage("#tableImpactedReqs tbody", 5, "No requirement impact paths were found in the verified graph traversal.");
}

function renderEvidenceChains(report) {
  const container = document.getElementById("evidenceCardsList");
  container.innerHTML = "";

  const items = report.impacted_requirements || [];
  if (items.length === 0) {
    container.innerHTML = "<p class='text-muted'>No impacted requirements detected.</p>";
    return;
  }

  items.slice(0, 5).forEach(item => {
    const card = document.createElement("div");
    card.className = "evidence-card";
    const pathStr = (item.evidence_chain || []).join(" ➔ ");

    card.innerHTML = `
      <div class="evidence-card-header">
        <span class="evidence-req-title"><strong>${escapeHtml(item.item_id)}:</strong> ${escapeHtml(item.label)}</span>
        <span class="badge badge-covered">Confidence: ${(item.confidence * 100).toFixed(0)}%</span>
      </div>
      <div class="evidence-path-box">
        ${escapeHtml(pathStr || `PR #${report.pr_number} ➔ Code AST ➔ UI Component ➔ ${item.item_id}`)}
      </div>
    `;
    container.appendChild(card);
  });
}

async function loadRequirementsMatrix() {
  try {
    const res = await fetch("/api/requirements");
    const data = await res.json();
    renderDynamicCoverageMatrix(data.requirements || []);
  } catch (err) {
    console.error("Coverage matrix load error", err);
  }
}

function renderDynamicCoverageMatrix(requirements) {
  const tbody = document.querySelector("#tableReqMatrix tbody");
  tbody.innerHTML = "";

  let coveredCnt = 0, partialCnt = 0, unverifiedCnt = 0, absentCnt = 0;

  requirements.forEach(r => {
    const status = r.coverage_status || "UNVERIFIED";
    if (status === "COVERED") coveredCnt++;
    else if (status === "PARTIAL") partialCnt++;
    else if (status === "UNVERIFIED") unverifiedCnt++;
    else if (status === "ABSENT") absentCnt++;

    const badgeClass = status === "COVERED" ? "badge-covered" 
      : status === "PARTIAL" ? "badge-partial" 
      : status === "ABSENT" ? "badge-absent" : "badge-unverified";

    const row = document.createElement("tr");
    const evidenceDesc = status === "COVERED" 
      ? "Verified across multiple UI selectors (at least two observed elements)"
      : status === "PARTIAL" 
      ? "Single UI component observed in crawl (monitored coverage)"
      : status === "ABSENT" 
      ? "Absent only after an explicit exhaustive coverage certificate"
      : "Search space incomplete — no absence claim is made";

    row.innerHTML = `
      <td><code>${escapeHtml(r.id)}</code></td>
      <td>${escapeHtml(r.category)}</td>
      <td>${escapeHtml(r.text)}</td>
      <td><code>${Number.isFinite(Number(r.testability_score)) ? Number(r.testability_score).toFixed(2) : "—"}</code></td>
      <td><span class="badge ${badgeClass}">${status}</span></td>
      <td><small>${evidenceDesc}</small></td>
    `;
    tbody.appendChild(row);
  });

  document.getElementById("cntCovered").innerText = `COVERED: ${coveredCnt}`;
  document.getElementById("cntPartial").innerText = `PARTIAL: ${partialCnt}`;
  document.getElementById("cntUnverified").innerText = `UNVERIFIED: ${unverifiedCnt}`;
  document.getElementById("cntAbsent").innerText = `ABSENT: ${absentCnt}`;
}

async function loadKnowledgeGraph(repo, prNumber) {
  const container = document.getElementById("networkGraph");
  try {
    const res = await fetch(`/api/graph/visualize?repo=${encodeURIComponent(repo)}&pr_number=${prNumber}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Evidence graph is unavailable.");

    const graphData = {
      nodes: new vis.DataSet(data.nodes || []),
      edges: new vis.DataSet(data.edges || []),
    };

    const options = {
      nodes: {
        shape: "dot",
        font: {
          color: "#f8fafc",
          size: 12,
          face: "Plus Jakarta Sans",
          background: "#0b1329",
          strokeWidth: 2,
          strokeColor: "#1e293b",
        },
        borderWidth: 2.5,
        shadow: {
          enabled: true,
          color: "rgba(0,0,0,0.6)",
          size: 10,
          x: 2,
          y: 2,
        },
      },
      edges: {
        width: 2.2,
        color: {
          color: "rgba(56, 189, 248, 0.75)",
          highlight: "#38bdf8",
          hover: "#818cf8",
        },
        arrows: {
          to: {
            enabled: true,
            scaleFactor: 1.1,
            type: "arrow",
          },
        },
        font: {
          color: "#f8fafc",
          size: 10,
          face: "JetBrains Mono",
          align: "horizontal",
          background: "#090d16",
          strokeWidth: 2,
          strokeColor: "#090d16",
        },
        smooth: { type: "continuous", roundness: 0.2 },
      },
      physics: {
        enabled: true,
        stabilization: { iterations: 120 },
        barnesHut: {
          gravitationalConstant: -15000,
          centralGravity: 0.25,
          springLength: 220,
          springConstant: 0.04,
          damping: 0.09,
          avoidOverlap: 0.9,
        },
      },
      interaction: {
        hover: true,
        tooltipDelay: 100,
        navigationButtons: false,
        keyboard: true,
        zoomView: true,
        dragView: true,
      },
    };

    if (network) network.destroy();
    network = new vis.Network(container, graphData, options);
    network.once("stabilizationIterationsDone", () => fitKnowledgeGraph(false));
    setTimeout(() => fitKnowledgeGraph(false), 80);
  } catch (err) {
    console.error("Knowledge Graph visualization error", err);
  }
}

async function downloadMarkdownReport() {
  const repo = document.getElementById("inputRepo").value.trim();
  const pr = parseInt(document.getElementById("inputPRNumber").value, 10);
  try {
    const res = await fetch(`/api/report/${pr}?repo=${encodeURIComponent(repo)}&format=markdown`);
    const md = await res.text();
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `blast_radius_pr_${pr}.md`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error("Markdown download failed", err);
  }
}
