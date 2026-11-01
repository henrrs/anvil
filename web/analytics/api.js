(function exposeAnalyticsApi(global) {
  class HttpAnalyticsApi {
    async request(path, options = {}) {
      const response = await fetch(path, {
        credentials: "same-origin",
        cache: "no-store",
        ...options,
        headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
      });
      const contentType = response.headers.get("content-type") || "";
      const payload = contentType.includes("application/json") ? await response.json() : {};
      if (!response.ok) {
        const error = new Error(payload?.error?.message || `Request failed (${response.status})`);
        error.code = payload?.error?.code || "HTTP_ERROR";
        error.status = response.status;
        error.retryable = Boolean(payload?.error?.retryable);
        throw error;
      }
      return payload;
    }

    async streamChat(body, onEvent) {
      const response = await fetch("/api/anvil/chat", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
        body: JSON.stringify(body),
      });
      if (!response.ok || !response.body) {
        const payload = await response.json().catch(() => ({}));
        const error = new Error(payload?.error?.message || `Ask Anvil failed (${response.status})`);
        error.code = payload?.error?.code || "CHAT_HTTP_ERROR";
        throw error;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";
        for (const frame of frames) {
          const event = frame.match(/^event: ([^\n]+)/m)?.[1];
          const data = frame.match(/^data: (.*)$/m)?.[1];
          if (!event || !data) continue;
          const payload = JSON.parse(data);
          onEvent?.(event, payload);
          if (event === "error") {
            const error = new Error(payload.message || "Ask Anvil could not finish.");
            error.code = payload.code || "CHAT_FAILED";
            throw error;
          }
        }
        if (done) break;
      }
    }
  }

  global.HttpAnalyticsApi = HttpAnalyticsApi;
})(window);
