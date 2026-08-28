// Open in Full Release - client action handler.
//
// The toolbar click dispatches to this handler (registered via HandlerName "open" on the
// server-side ExtensionAction) instead of the default apiEndpoint dispatch, because a plain
// POST response cannot open a new browser tab. We still call the same apiEndpoint ourselves,
// read the resolved Full Release URL back, and open it with window.open. Returning
// { suppressToast: true } skips the host's default "queued" success alert, which does not
// apply here - nothing was queued, a tab was opened.
export default {
  actionHandlers: {
    async open(action, payload) {
      const res = await fetch(action.apiEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      let data = {};
      try { data = await res.json(); } catch { /* no body */ }
      if (!res.ok) {
        throw new Error(data.message || `HTTP ${res.status}`);
      }
      if (data.url) {
        window.open(data.url, "_blank", "noopener,noreferrer");
      }
      return { suppressToast: true };
    },
  },
};
