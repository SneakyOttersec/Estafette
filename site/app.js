(function () {
  "use strict";

  const config = window.ESTAFETTE_CONFIG || {};
  const apiBaseUrl = String(config.apiBaseUrl || "").replace(/\/$/, "");
  const remarkableAppUrl = String(config.remarkableAppUrl || "");
  const connect = document.querySelector("#connect-drive");
  const disconnect = document.querySelector("#disconnect-drive");
  const installRemarkable = document.querySelector("#install-remarkable");
  const note = document.querySelector("#connection-note");
  const remarkableNote = document.querySelector("#remarkable-note");
  const year = document.querySelector("#year");
  const editionList = document.querySelector("#edition-list");
  const editionStatus = document.querySelector("#edition-status");
  const editionYear = document.querySelector("#edition-year");
  const archiveTitle = document.querySelector("#archive-title");
  const releasesApi = "https://api.github.com/repos/SneakyOttersec/Estafette/releases?per_page=100";

  if (year) {
    year.textContent = new Date().getFullYear().toString();
  }

  function enableLink(link, href) {
    if (!link) return;
    link.href = href;
    link.removeAttribute("aria-disabled");
  }

  function showStatus(message, isError) {
    if (!note) return;
    note.textContent = message;
    note.className = isError ? "connection-note status error" : "connection-note status";
  }

  if (apiBaseUrl) {
    enableLink(connect, `${apiBaseUrl}/auth/start`);
    enableLink(disconnect, `${apiBaseUrl}/auth/disconnect`);
  } else if (connect) {
    showStatus("Registration is not configured yet. Set the ESTAFETTE_API_URL repository variable.", true);
  }

  if (remarkableAppUrl) {
    enableLink(installRemarkable, remarkableAppUrl);
    if (remarkableNote) remarkableNote.textContent = "The reMarkable app installer is ready.";
  }

  for (const link of [connect, disconnect, installRemarkable]) {
    if (!link) continue;
    link.addEventListener("click", function (event) {
      if (link.getAttribute("aria-disabled") === "true") {
        event.preventDefault();
      }
    });
  }

  const params = new URLSearchParams(window.location.search);
  if (params.get("connected") === "1") {
    showStatus("Connected. Your Estafette folder is ready in Google Drive.", false);
  } else if (params.get("disconnected") === "1") {
    showStatus("Disconnected. Existing PDFs remain in your Drive; future delivery has stopped.", false);
  } else if (params.has("error")) {
    const knownErrors = {
      access_denied: "Google Drive access was not granted. Nothing was changed.",
      missing_refresh_token: "Google did not return offline access. Please connect again.",
      oauth_failed: "The Google connection could not be completed. Please try again."
    };
    showStatus(knownErrors[params.get("error")] || "The connection could not be completed.", true);
  }

  if (params.has("connected") || params.has("disconnected") || params.has("error")) {
    window.history.replaceState({}, document.title, window.location.pathname + window.location.hash);
  }

  function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return "Download";
    if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function createDownload(asset) {
    const link = document.createElement("a");
    const label = document.createElement("span");
    const type = document.createElement("strong");
    const size = document.createElement("small");
    const arrow = document.createElement("b");
    const extension = asset.name.split(".").pop().toUpperCase();

    link.href = asset.browser_download_url;
    link.dataset.downloadName = asset.name;
    type.textContent = extension;
    size.textContent = formatBytes(asset.size);
    arrow.textContent = "↓";
    arrow.setAttribute("aria-hidden", "true");
    label.append(type, size);
    link.append(label, arrow);
    return link;
  }

  function createEdition(release, assets) {
    const published = new Date(release.published_at || release.created_at);
    const card = document.createElement("article");
    const date = document.createElement("time");
    const day = document.createElement("strong");
    const monthYear = document.createElement("span");
    const copy = document.createElement("div");
    const label = document.createElement("p");
    const title = document.createElement("h3");
    const description = document.createElement("p");
    const downloads = document.createElement("div");

    card.className = "edition-card";
    card.dataset.edition = release.tag_name;
    card.dataset.year = published.getUTCFullYear().toString();
    date.className = "edition-date";
    date.dateTime = published.toISOString().slice(0, 10);
    day.textContent = published.toLocaleDateString("en-GB", { day: "2-digit" });
    monthYear.textContent = `${published.toLocaleDateString("en-GB", { month: "short" }).toUpperCase()} ${published.getUTCFullYear()}`;
    date.append(day, monthYear);

    copy.className = "edition-copy";
    label.className = "edition-label";
    label.textContent = "Published edition";
    title.textContent = release.name || "Estafette weekly edition";
    description.textContent = "The latest security reading bundle, ready for download.";
    copy.append(label, title, description);

    downloads.className = "download-list";
    downloads.setAttribute("aria-label", "Edition downloads");
    for (const asset of assets) downloads.append(createDownload(asset));
    card.append(date, copy, downloads);
    return card;
  }

  function filterArchiveByYear() {
    if (!editionList || !editionYear) return;
    const selectedYear = editionYear.value;
    let visible = 0;

    for (const card of editionList.querySelectorAll(".edition-card")) {
      card.hidden = card.dataset.year !== selectedYear;
      if (!card.hidden) visible += 1;
    }

    if (archiveTitle) archiveTitle.textContent = `${selectedYear} editions`;
    if (editionStatus) {
      editionStatus.textContent = visible
        ? `${visible} edition${visible === 1 ? "" : "s"} published in ${selectedYear}.`
        : `No editions were published in ${selectedYear}.`;
    }
  }

  function updateEditionView() {
    if (!editionList) return;
    const cards = Array.from(editionList.querySelectorAll(".edition-card"));
    const limit = Number.parseInt(editionList.dataset.limit || "0", 10);

    if (limit > 0) {
      cards.forEach((card, index) => {
        card.hidden = index >= limit;
      });
    }

    if (!editionYear) return;
    const previousYear = editionYear.value;
    const years = Array.from(new Set(cards.map((card) => card.dataset.year)))
      .filter(Boolean)
      .sort((left, right) => Number(right) - Number(left));

    editionYear.replaceChildren();
    for (const yearValue of years) {
      const option = document.createElement("option");
      option.value = yearValue;
      option.textContent = yearValue;
      editionYear.append(option);
    }
    editionYear.value = years.includes(previousYear) ? previousYear : years[0] || "";

    if (!editionYear.dataset.ready) {
      editionYear.addEventListener("change", filterArchiveByYear);
      editionYear.dataset.ready = "true";
    }
    filterArchiveByYear();
  }

  async function loadPublishedEditions() {
    if (!editionList || !editionStatus) return;

    try {
      const response = await fetch(releasesApi, {
        headers: { Accept: "application/vnd.github+json" }
      });
      if (!response.ok) throw new Error(`GitHub returned ${response.status}`);

      const releases = await response.json();
      const knownNames = new Set(
        Array.from(document.querySelectorAll("[data-download-name]"), (link) => link.dataset.downloadName)
      );
      let added = 0;

      for (const release of releases.slice().reverse()) {
        const assets = (release.assets || []).filter((asset) => {
          const isDownload = /\.(pdf|zip)$/i.test(asset.name);
          return isDownload && !knownNames.has(asset.name);
        });
        if (!assets.length) continue;
        for (const asset of assets) knownNames.add(asset.name);
        editionList.prepend(createEdition(release, assets));
        added += 1;
      }

      editionStatus.textContent = added
        ? "Showing the newest public releases and the original archive edition."
        : "Showing the latest available edition. New releases appear here automatically.";
      updateEditionView();
    } catch (_error) {
      editionStatus.textContent = "Showing the latest available edition. Release updates are temporarily unavailable.";
      updateEditionView();
    }
  }

  loadPublishedEditions();
})();
