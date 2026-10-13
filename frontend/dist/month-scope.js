(function () {
  var originalFetch = window.fetch;
  if (!originalFetch || originalFetch.__entryMonthScoped) {
    return;
  }

  function currentReportMonth() {
    var value = new URLSearchParams(window.location.search).get("month");
    return /^\d{4}-\d{2}$/.test(value || "") ? value : "";
  }

  function shouldScope(pathname) {
    if (pathname === "/api/templates" || pathname === "/api/responsibilities") {
      return true;
    }
    return /^\/api\/templates\/[^/]+$/.test(pathname);
  }

  function scopedUrl(input) {
    var reportMonth = currentReportMonth();
    if (!reportMonth || typeof input !== "string") {
      return input;
    }
    var url = new URL(input, window.location.origin);
    if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/")) {
      return input;
    }
    if (!shouldScope(url.pathname) || url.searchParams.has("version") || url.searchParams.has("report_month")) {
      return input;
    }
    url.searchParams.set("report_month", reportMonth);
    return input.startsWith(window.location.origin) ? url.toString() : url.pathname + url.search + url.hash;
  }

  function monthScopedFetch(input, init) {
    if (input instanceof Request) {
      var updated = scopedUrl(input.url);
      if (updated !== input.url) {
        input = new Request(updated, input);
      }
      return originalFetch.call(this, input, init);
    }
    return originalFetch.call(this, scopedUrl(input), init);
  }

  monthScopedFetch.__entryMonthScoped = true;
  window.fetch = monthScopedFetch;
})();
