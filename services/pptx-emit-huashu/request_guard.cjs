'use strict';
// The export page's request guard: what a slide's page may load, decided in
// Node for every request its browser context makes (Playwright routing), never
// by the page. render_slide.cjs loads each slide from a file: URL, and nothing
// in the page itself stops slide script from navigating it elsewhere: one line,
// `location.href = 'file:///etc/hosts'`, used to export that file's text, a
// directory URL its listing, and on Databricks Apps any user who can edit a
// slide's HTML could have read the container's files into a deck. The slide
// CSP (src/utils/html_safety.py SLIDE_CSP) cannot stop a frame navigating
// itself, and a caller's document may carry no CSP at all, so this holds
// whatever the document says.
//
// A request is allowed when it is
//   * the slide's own file URL, exactly (its fragment aside);
//   * a data: or blob: URL;
//   * an https request, on https's own port and without credentials, to a host
//     the slide CSP allows for its kind of request: `hosts` maps each
//     Playwright resourceType() to its hosts, as the wrapper derives them from
//     SLIDE_CSP's fetch directives (html_safety.py slide_csp_request_hosts) and
//     passes them in the stdin payload (emit_deck.mjs, `allowedHosts`): a
//     script the script-src hosts, a stylesheet the style-src host, a font the
//     font-src hosts. A host the CSP allows for one kind of request is none for
//     another, as in the page, so a frame or a fetch to a CDN is no request the
//     guard lets through.
// Everything else is aborted: any other file:, http:, a loopback or link-local
// address (127.0.0.0/8, ::1, 169.254.0.0/16), any other https host. A
// navigation is allowed only to the slide itself: in the main frame, a
// navigation anywhere else is the slide leaving itself, which fails the slide
// (render_slide.cjs), and in any other frame it is aborted. Aborted with
// ERR_ABORTED, so a frame commits no error page that names the URL it was
// denied. WebSockets are closed before they connect, and a popup
// (window.open) is closed as it opens.
//
// WebRTC is no request routing sees: a peer connection's ICE gathering sends
// STUN over UDP and opens TURN over TCP to whatever its servers name, a
// loopback or internal address included (measured: both reach local
// listeners from Chrome and from Playwright's Chromium). So every realm of the
// context (the page's, each frame's and each popup's) has its peer-connection
// constructors taken away by an init script, which runs in it before any of
// its own script (NO_PEER_CONNECTIONS); and render_slide.cjs launches the
// browser with an IP-handling policy that sends no UDP but through a proxy,
// which it has none of, should a realm ever keep one.
//
// Playwright's routing sees the first request of a redirect chain only, so a
// redirect a host the CSP allows answers with is followed unchecked. The hosts
// are the slide CDNs (jsdelivr, Tailwind's, Google Fonts), and what a slide
// loads from them is a script, a stylesheet or a font, whose bytes the page
// cannot read; a document, which would show what it reached, is never
// allowed to them.
//
//   requestHostsOf(value) -> {hosts: Map<resourceType, Set<host>>, ignored}
//     The payload's host list, each entry kept only when its key is a request
//     type and its hosts lower-case host names; `ignored` counts the rest. A
//     value that is no such object allows no https request at all.
//   requestVerdict({url, resourceType, navigation, mainFrame}, {slideUrl, hosts})
//     -> 'allow' | 'block' | 'leave'
//     'leave' is a main-frame navigation away from the slide.
//   guardContext(context, slideUrl, hosts, onLeave) -> Promise<Guard>
//     Routes every request and WebSocket of `context` through the verdicts.
//     onLeave(scheme) is called for each navigation away from the slide, the
//     target's URL scheme its only detail: the URL itself is the page's.
//   Guard.watch(page)  the slide's page: its main frame leaving the slide
//     without a request (a blob: URL, a history entry) is a leave too, and
//     each popup opened from now on is closed.
//   Guard.counts()     {blockedRequests, closedPopups}, for the slide summary.

// The init script that takes a realm's peer-connection constructors away
// (measured: gone in the page's realm, a fresh about:blank iframe's, a srcdoc
// iframe's, an <object>'s and a popup's). Each is a configurable property of
// the realm's global, so delete takes it.
const NO_PEER_CONNECTIONS = `(() => {
  for (const name of ['RTCPeerConnection', 'webkitRTCPeerConnection']) {
    try { delete globalThis[name]; } catch (error) { /* a realm without it: nothing to take */ }
  }
})();`;

// Playwright's request types (Request.resourceType()).
const REQUEST_TYPES = new Set([
  'document', 'stylesheet', 'image', 'media', 'font', 'script', 'texttrack', 'xhr',
  'fetch', 'eventsource', 'websocket', 'manifest', 'other',
]);
// A host name as the URL parser writes one: lower-case labels, at least two.
const HOST_NAME = /^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;

const ALLOW = 'allow';
const BLOCK = 'block';
const LEAVE = 'leave';
// What an aborted request fails with: no error page is committed for it.
const ABORT_ERROR = 'aborted';
const NO_HOSTS = new Set();

function requestHostsOf(value) {
  const hosts = new Map();
  let ignored = 0;
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { hosts, ignored: value === undefined || value === null ? 0 : 1 };
  }
  for (const [kind, names] of Object.entries(value)) {
    if (!REQUEST_TYPES.has(kind) || !Array.isArray(names)) {
      ignored += 1;
      continue;
    }
    const kept = new Set();
    for (const name of names) {
      if (typeof name === 'string' && HOST_NAME.test(name)) kept.add(name);
      else ignored += 1;
    }
    if (kept.size) hosts.set(kind, kept);
  }
  return { hosts, ignored };
}

// The URL without its fragment, or null when it does not parse.
function fragmentless(url) {
  try {
    const parsed = new URL(url);
    parsed.hash = '';
    return parsed.href;
  } catch (error) {
    return null;
  }
}

function requestVerdict(request, policy) {
  let url;
  try {
    url = new URL(String(request.url));
  } catch (error) {
    return BLOCK;
  }
  const own = fragmentless(url.href) === policy.slideUrl;
  if (request.navigation) {
    if (own) return ALLOW;
    return request.mainFrame ? LEAVE : BLOCK;
  }
  if (own) return ALLOW;
  if (url.protocol === 'data:' || url.protocol === 'blob:') return ALLOW;
  if (url.protocol !== 'https:' || url.port !== '' || url.username !== '' || url.password !== '') {
    return BLOCK;
  }
  return (policy.hosts.get(request.resourceType) || NO_HOSTS).has(url.hostname) ? ALLOW : BLOCK;
}

// The URL's scheme, the one thing about a page's URL a failure says.
function schemeOf(url) {
  try {
    return new URL(String(url)).protocol.replace(/:$/, '');
  } catch (error) {
    return 'unparsed';
  }
}

// Whether the request is its page's main frame's own: a service worker's
// request has no frame, and Playwright throws reading it.
function isMainFrame(request, page) {
  try {
    return page !== null && request.frame() === page.mainFrame();
  } catch (error) {
    return false;
  }
}

async function guardContext(context, slideUrl, hosts, onLeave) {
  const policy = { slideUrl, hosts };
  let page = null;
  let blockedRequests = 0;
  let closedPopups = 0;
  // Each settles once the page or the browser is gone too: never wait on it.
  const settle = (promise) => promise.catch(() => {});
  await context.addInitScript(NO_PEER_CONNECTIONS);
  await context.route(() => true, (route) => {
    const request = route.request();
    const verdict = requestVerdict({
      url: request.url(),
      resourceType: request.resourceType(),
      navigation: request.isNavigationRequest(),
      mainFrame: isMainFrame(request, page),
    }, policy);
    if (verdict === ALLOW) return settle(route.continue());
    if (verdict === LEAVE) onLeave(schemeOf(request.url()));
    else blockedRequests += 1;
    return settle(route.abort(ABORT_ERROR));
  });
  await context.routeWebSocket(() => true, (socket) => {
    blockedRequests += 1;
    settle(socket.close());
  });
  return {
    watch(slidePage) {
      page = slidePage;
      slidePage.on('framenavigated', (frame) => {
        if (frame === slidePage.mainFrame() && fragmentless(frame.url()) !== slideUrl) {
          onLeave(schemeOf(frame.url()));
        }
      });
      context.on('page', (popup) => {
        if (popup === slidePage) return;
        closedPopups += 1;
        settle(popup.close());
      });
    },
    counts() {
      return { blockedRequests, closedPopups };
    },
  };
}

module.exports = { guardContext, requestHostsOf, requestVerdict, fragmentless };
