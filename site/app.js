(function () {
  "use strict";

  const config = window.ESTAFETTE_CONFIG || {};
  const apiBaseUrl = String(config.apiBaseUrl || "").replace(/\/$/, "");
  const connect = document.querySelector("#connect-drive");
  const disconnect = document.querySelector("#disconnect-drive");
  const note = document.querySelector("#connection-note");
  const year = document.querySelector("#year");

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
    note.className = isError ? "status error" : "status";
  }

  if (apiBaseUrl) {
    enableLink(connect, `${apiBaseUrl}/auth/start`);
    enableLink(disconnect, `${apiBaseUrl}/auth/disconnect`);
  } else if (connect) {
    showStatus("Registration is not configured yet. Set the ESTAFETTE_API_URL repository variable.", true);
  }

  for (const link of [connect, disconnect]) {
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
})();
