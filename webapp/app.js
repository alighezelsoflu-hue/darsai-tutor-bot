/* DarsAI Mini App, step 1: a read-only Progress page that reports how long it took to open.
 *
 * No telegram-web-app.js (telegram.org may be blocked where students are): the launch parameters come from the
 * page address (tgWebAppData, tgWebAppPlatform, tgWebAppThemeParams), and events go through Telegram's documented
 * channel (TelegramWebviewProxy.postEvent, external.notify, or postMessage to the parent frame). The page works
 * without them too. Texts come from the server (the JSON block in index.html, and the API's answers).
 */
(function () {
  "use strict";

  var texts = {};
  try { texts = JSON.parse(document.getElementById("texts").textContent); } catch (e) { texts = {}; }
  var lang = "en";

  function t(key, params) {
    var text = (texts[lang] && texts[lang][key]) || (texts.en && texts.en[key]) || key;
    Object.keys(params || {}).forEach(function (name) { text = text.split("{" + name + "}").join(params[name]); });
    return text;
  }

  function digits(value) {
    var text = String(value);
    return lang === "fa" ? text.replace(/[0-9]/g, function (d) { return "۰۱۲۳۴۵۶۷۸۹"[d]; }).replace(".", "٫") : text;
  }

  function setLanguage(code) {
    lang = code === "fa" ? "fa" : "en";
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
  }

  // ---- launch parameters (kept for a reload inside Telegram) ----
  function readParams() {
    var params = {};
    [window.location.hash.slice(1), window.location.search.slice(1)].forEach(function (part) {
      part.split("&").forEach(function (pair) {
        var at = pair.indexOf("=");
        if (at < 1) return;
        try {
          var key = decodeURIComponent(pair.slice(0, at));
          if (!(key in params)) params[key] = decodeURIComponent(pair.slice(at + 1).replace(/\+/g, "%20"));
        } catch (e) { /* a malformed part: skip it */ }
      });
    });
    try {
      if (params.tgWebAppData) sessionStorage.setItem("darsai_launch", JSON.stringify(params));
      else params = JSON.parse(sessionStorage.getItem("darsai_launch") || "{}");
    } catch (e) { /* storage may be off */ }
    return params;
  }

  // ---- Telegram's event channel ----
  function postEvent(type, data) {
    try {
      if (window.TelegramWebviewProxy && window.TelegramWebviewProxy.postEvent) {
        window.TelegramWebviewProxy.postEvent(type, JSON.stringify(data || {}));
        return true;
      }
      if (window.external && "notify" in window.external) {
        window.external.notify(JSON.stringify({ eventType: type, eventData: data || {} }));
        return true;
      }
      if (window.parent && window.parent !== window) {
        window.parent.postMessage(JSON.stringify({ eventType: type, eventData: data || {} }), "*");
        return true;
      }
    } catch (e) { /* no channel */ }
    return false;
  }

  function applyTheme(theme) {
    if (!theme || typeof theme !== "object") return;
    var style = document.documentElement.style;
    Object.keys(theme).forEach(function (name) {
      if (/^#[0-9a-fA-F]{3,8}$/.test(theme[name])) style.setProperty("--tg-" + name.replace(/_/g, "-"), theme[name]);
    });
  }

  function receiveEvent(type, data) {
    if (type === "theme_changed" && data) applyTheme(data.theme_params);
  }
  window.Telegram = window.Telegram || {};
  window.Telegram.WebView = window.Telegram.WebView || {};
  window.Telegram.WebView.receiveEvent = receiveEvent;
  window.addEventListener("message", function (event) {
    try {
      var message = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
      if (message && message.eventType) receiveEvent(message.eventType, message.eventData);
    } catch (e) { /* not for us */ }
  });

  // ---- drawing ----
  var main = document.getElementById("app");

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function showMessage(key, retry) {
    main.textContent = "";
    main.appendChild(element("p", "status", t(key)));
    if (retry) {
      var button = element("button", "", t("app.retry"));
      button.addEventListener("click", function () { window.location.reload(); });
      main.appendChild(button);
    }
  }

  function render(data) {
    setLanguage(data.lang);
    main.textContent = "";
    main.appendChild(element("h1", "", data.title));
    if (data.empty) main.appendChild(element("p", "status", data.empty));
    (data.sections || []).forEach(function (section) {
      main.appendChild(element("h2", "", section.level));
      var list = element("ul", "topics");
      section.topics.forEach(function (topic) {
        var item = element("li", "topic");
        item.appendChild(element("div", "topic-name", topic.name));
        var bar = element("div", "bar");
        var fill = element("div", "fill");
        fill.style.width = Math.max(0, Math.min(100, Number(topic.percent) || 0)) + "%";
        bar.appendChild(fill);
        item.appendChild(bar);
        item.appendChild(element("div", "detail", topic.detail));
        list.appendChild(item);
      });
      main.appendChild(list);
    });
    if (data.suggest && !data.empty) main.appendChild(element("p", "suggest", data.suggest));
  }

  // ---- how long it took ----
  function now() { return window.performance && performance.now ? performance.now() : 0; }

  function timings() {
    var result = {};
    var entry = window.performance && performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
    if (entry) {
      result.dns_ms = entry.domainLookupEnd - entry.domainLookupStart;
      result.connect_ms = entry.connectEnd - entry.connectStart;
      result.ttfb_ms = entry.responseStart - entry.startTime;
      result.dom_ms = entry.domContentLoadedEventEnd > 0 ? entry.domContentLoadedEventEnd - entry.startTime : null;
    } else if (window.performance && performance.timing) {
      var old = performance.timing;
      result.dns_ms = old.domainLookupEnd - old.domainLookupStart;
      result.connect_ms = old.connectEnd - old.connectStart;
      result.ttfb_ms = old.responseStart - old.navigationStart;
      result.dom_ms = old.domContentLoadedEventEnd > 0 ? old.domContentLoadedEventEnd - old.navigationStart : null;
    }
    return result;
  }

  function report(initData, bridge, apiMs, totalMs) {
    var body = timings();
    body.platform = params.tgWebAppPlatform || "unknown";
    body.bridge = bridge;
    body.api_ms = apiMs;
    body.total_ms = totalMs;
    try {
      fetch("/api/miniapp/ping", {
        method: "POST",
        keepalive: true,
        headers: { "Authorization": "tma " + initData, "Content-Type": "application/json" },
        body: JSON.stringify(body)
      }).catch(function () { /* the measurement is best effort */ });
    } catch (e) { /* no fetch */ }
  }

  // ---- start ----
  var params = readParams();
  var initData = params.tgWebAppData || "";
  try { applyTheme(JSON.parse(params.tgWebAppThemeParams || "{}")); } catch (e) { /* no theme */ }
  try {
    var user = JSON.parse(new URLSearchParams(initData).get("user") || "{}");
    setLanguage(String(user.language_code || "").indexOf("fa") === 0 ? "fa" : "en");
  } catch (e) { setLanguage("en"); }

  var bridge = postEvent("web_app_ready", {});
  postEvent("web_app_expand", {});
  postEvent("web_app_request_theme", {});

  if (!initData) {
    showMessage("app.open_in_telegram", false);
    return;
  }
  showMessage("app.loading", false);
  var asked = now();
  fetch("/api/me/progress", { headers: { "Authorization": "tma " + initData } })
    .then(function (response) {
      if (response.status === 401) throw new Error("expired");
      if (response.status === 429) throw new Error("slow");
      if (!response.ok) throw new Error("server");
      return response.json();
    })
    .then(function (data) {
      var apiMs = now() - asked;
      render(data);
      var totalMs = now();
      document.getElementById("footer").textContent = t("app.opened_in", { seconds: digits((totalMs / 1000).toFixed(1)) });
      report(initData, bridge, apiMs, totalMs);
    })
    .catch(function (error) {
      var reason = error && error.message;
      showMessage(reason === "expired" ? "app.reopen" : reason === "slow" ? "app.slow" : "app.offline", true);
    });
})();
