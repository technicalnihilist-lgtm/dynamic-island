"""Behavioural tests for the Dynamic Island web app (in-app preview + overlay)."""
import os, sys
from playwright.sync_api import sync_playwright

HTML = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else
                       os.path.join(os.path.dirname(__file__), "..", "app", "index.html"))
URL = "file://" + HTML
OVERLAY_URL = "file://" + os.path.join(os.path.dirname(HTML), "overlay.html")
EXE = os.environ.get("CHROME_PATH")

MOCK = """
window.__calls = [];
function rec(n, a){ window.__calls.push([n].concat(Array.prototype.slice.call(a))); }
window.Native = {
  insets: function(){ return "24,16"; },
  battery: function(){ return 72; },
  haptic: function(){ rec('haptic', arguments); },
  canDrawOverlays: function(){ return window.__canDraw === true; },
  overlayRunning: function(){ return window.__running === true; },
  hasNotifAccess: function(){ return window.__notif === true; },
  requestOverlay: function(){ rec('requestOverlay', arguments); },
  requestNotifAccess: function(){ rec('requestNotifAccess', arguments); },
  startOverlay: function(){ window.__running = true; rec('startOverlay', arguments); },
  stopOverlay: function(){ window.__running = false; rec('stopOverlay', arguments); },
  resize: function(){ rec('resize', arguments); },
  stateChanged: function(){ rec('stateChanged', arguments); },
  setOverlayState: function(s){ rec('setOverlayState', [s]); },
  setOverlayConfig: function(){ rec('setOverlayConfig', arguments); },
  setOverlayPosition: function(){ rec('setOverlayPosition', arguments); },
  setOverlayLock: function(){ rec('setOverlayLock', arguments); },
  media: function(){ rec('media', arguments); },
  callAction: function(){ rec('callAction', arguments); }
};
"""

CLOCK_FAKE = """
(function(){
  var RD = Date;
  window.__off = 0;          /* test-controlled offset, in ms */
  window.__dateCalls = 0;    /* how often the page built a Date */
  window.__nowCalls = 0;
  function FD(a,b,c,d,e,f,g){
    window.__dateCalls++;
    var n = arguments.length;
    if(n === 0) return new RD(RD.now() + window.__off);
    if(n === 1) return new RD(a);
    return new RD(a, b, c === undefined ? 1 : c, d || 0, e || 0, f || 0, g || 0);
  }
  FD.now = function(){ window.__nowCalls++; return RD.now() + window.__off; };
  FD.parse = RD.parse; FD.UTC = RD.UTC; FD.prototype = RD.prototype;
  window.Date = FD;
})();
"""

WAKE_FAKE = """
(function(){
  var si = window.setInterval;
  window.__intervals = [];      /* every repeating timer the page schedules */
  window.__batteryCalls = 0;
  window.setInterval = function(fn, d){
    window.__intervals.push(d);
    return si.apply(window, arguments);
  };
  var N = window.Native;
  if (N && N.battery){
    var b0 = N.battery;
    N.battery = function(){ window.__batteryCalls++; return b0.apply(N, arguments); };
  }
})();
"""

VIEWPORT_FAKE = """
(function(){
  /* counts every read of window.innerWidth, the way a forced layout is asked for */
  window.__vwReads = 0;
  Object.defineProperty(window, 'innerWidth', {
    configurable: true,
    get: function(){ window.__vwReads++; return document.documentElement.clientWidth; }
  });
})();
"""

STAGE_FAKE = """
(function(){
  /* counts every read of the stage's box, the way a forced layout is asked for */
  var orig = Element.prototype.getBoundingClientRect;
  window.__stageReads = 0;
  Element.prototype.getBoundingClientRect = function(){
    if (this && this.id === 'stage') window.__stageReads++;
    return orig.apply(this, arguments);
  };
})();
"""

fails = []
checks = [0]
def chk(name, cond, extra=""):
    checks[0] += 1
    print(("PASS " if cond else "FAIL ") + name + (("  -> " + str(extra)) if not cond else ""))
    if not cond: fails.append(name)

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE, args=["--no-sandbox"]) if EXE else p.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, color_scheme="dark")
    ctx.add_init_script(MOCK)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto(URL); pg.wait_for_timeout(900)

    box_of = lambda page: page.eval_on_selector("#island", "e=>{const r=e.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height),y:Math.round(r.top)}}")
    box = lambda: box_of(pg)
    near = lambda g, w, h: abs(g["w"] - w) <= 1 and abs(g["h"] - h) <= 1
    calls = lambda: pg.evaluate("window.__calls.map(c=>c[0])")
    last = lambda n: pg.evaluate("(function(){var c=window.__calls.filter(x=>x[0]==='%s');return c.length?c[c.length-1]:null})()" % n)

    # ---- preview geometry -------------------------------------------------
    chk("idle geometry", near(box(), 130, 38), box())
    chk("island sits at the absolute top by default", box()["y"] <= 6, box())
    for st, exp in [("incoming", (312, 88)), ("calling", (274, 66)), ("music", (318, 128))]:
        pg.click(f'#states .chip[data-s="{st}"]'); pg.wait_for_timeout(1700)
        g = box(); chk(f"state {st} size", near(g, *exp), g)
        chk(f"state {st} content visible", pg.eval_on_selector("#content", "e=>getComputedStyle(e).opacity") == "1")

    pg.click('#states .chip[data-s="incoming"]'); pg.wait_for_timeout(1300)
    pg.click('#island [data-a="accept"]'); pg.wait_for_timeout(1700)
    chk("ongoing size", near(box(), 318, 118), box())
    t1 = pg.eval_on_selector('#content [data-role="time"]', "e=>e.textContent"); pg.wait_for_timeout(1100)
    chk("call timer ticks", t1 != pg.eval_on_selector('#content [data-role="time"]', "e=>e.textContent"))

    # Expand while a call is already on screen re-entered the same state, which
    # rebuilt the view and reset the call timer to 00:00
    elapsed = lambda: pg.eval_on_selector(
        '#content [data-role="time"]',
        "e=>{const p=e.textContent.split(':');return (+p[0])*60+(+p[1])}")
    pg.evaluate("window.__tNode = document.querySelector('#content .t1')")
    was = elapsed()
    pg.click("#btnExpand"); pg.wait_for_timeout(400)
    chk("Expand during a call does not rebuild the call view",
        pg.evaluate("document.querySelector('#content .t1') === window.__tNode"))
    chk("Expand during a call does not restart the call timer", elapsed() >= was, (was, elapsed()))
    pg.wait_for_timeout(1100)
    chk("the call timer keeps counting after Expand", elapsed() > was, (was, elapsed()))
    pg.click('#island [data-a="end"]'); pg.wait_for_timeout(1750)
    chk("end -> idle", near(box(), 130, 38), box())

    # ---- system-wide switch ----------------------------------------------
    chk("starts with the switch off", "Off" in pg.eval_on_selector("#pwLabel", "e=>e.textContent"))
    chk("preview island visible when off", pg.eval_on_selector("#island", "e=>getComputedStyle(e).visibility") == "visible")

    pg.click("#pw"); pg.wait_for_timeout(500)      # no permission yet
    chk("without permission it stays off", "Off" in pg.eval_on_selector("#pwLabel", "e=>e.textContent"))
    chk("without permission it asks for it", "requestOverlay" in calls())
    chk("hint explains the permission", "Display over other apps" in pg.eval_on_selector("#sysHint", "e=>e.textContent"))
    chk("service was not started", "startOverlay" not in calls())

    pg.evaluate("window.__canDraw = true; window.__sysState(true, false, false)")
    pg.wait_for_timeout(300)
    chk("permission granted hides the grant button", pg.eval_on_selector("#btnPerm", "e=>e.hidden") is True)

    pg.evaluate("window.__sysState(true, false, false, 'window: BadTokenException')")
    pg.wait_for_timeout(200)
    chk("a broken overlay is reported, not swallowed",
        "BadTokenException" in pg.eval_on_selector("#sysHint", "e=>e.textContent"))
    pg.evaluate("window.__sysState(true, false, false, '')")
    pg.wait_for_timeout(200)

    pg.click("#pw"); pg.wait_for_timeout(800)
    chk("switch turns on", "On" in pg.eval_on_selector("#pwLabel", "e=>e.textContent"))
    chk("overlay service started", "startOverlay" in calls())
    chk("preview stays on screen while the overlay runs",
        pg.eval_on_selector("#island", "e=>getComputedStyle(e).visibility") == "visible")
    pg.click('#states .chip[data-s="music"]'); pg.wait_for_timeout(1700)
    chk("preview keeps its size while the overlay runs", near(box(), 318, 128), box())
    chk("size settings are still on screen",
        pg.eval_on_selector("#accLook", "e=>e.getBoundingClientRect().height") > 40)
    chk("switch state persists", pg.evaluate("localStorage.getItem('di.settings')").find('"on":true') >= 0)

    pg.click('#states .chip[data-s="music"]'); pg.wait_for_timeout(900)
    chk("chips drive the floating island", last("setOverlayState")[1] == "music", last("setOverlayState"))
    pushes = calls().count("setOverlayState")
    pg.click('#states .chip[data-s="music"]'); pg.wait_for_timeout(400)
    chk("tapping the chip you are already on pushes nothing to the floating island",
        calls().count("setOverlayState") == pushes, calls().count("setOverlayState"))
    pg.eval_on_selector("#sw", "e=>{e.value=110;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))}")
    pg.wait_for_timeout(400)
    chk("sliders push config to the overlay", "setOverlayConfig" in calls())

    pg.click("#pw"); pg.wait_for_timeout(700)
    chk("switch turns off", "Off" in pg.eval_on_selector("#pwLabel", "e=>e.textContent"))
    chk("overlay service stopped", "stopOverlay" in calls())
    chk("preview island still there after switching off",
        pg.eval_on_selector("#island", "e=>getComputedStyle(e).visibility") == "visible")

    # the floating island can move on its own while the app is in the background
    pg.eval_on_selector("#btnReset", "e=>e.click()"); pg.wait_for_timeout(1700)
    pg.evaluate("window.__overlayState('incoming')"); pg.wait_for_timeout(1700)
    chk("preview mirrors the floating island", near(box(), 312, 88), box())
    chk("mirroring does not echo back to the overlay", last("setOverlayState")[1] == "music", last("setOverlayState"))

    # ---- "Reset to default" must not touch the system-wide switch ---------
    # the reset copied every default over the settings, `on` included, and told
    # neither the service nor the switch: the stored settings said off, the
    # switch still said On, the window was still on screen - and the next
    # __sysState (the one that arrives when you come back to the app) saw that
    # disagreement and stopped the floating island, as if it had died on its own
    rst = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, color_scheme="dark")
    rst.add_init_script(MOCK)
    rp = rst.new_page()
    rerrs = []
    rp.on("pageerror", lambda e: rerrs.append(str(e)))
    rp.goto(URL); rp.wait_for_timeout(900)
    rp.evaluate("window.__sysState(true,false,false,'')"); rp.wait_for_timeout(200)
    rp.click("#pw"); rp.wait_for_timeout(500)
    chk("the switch turns the floating island on", "On" in rp.eval_on_selector("#pwLabel", "e=>e.textContent"))
    chk("the island is running before the reset", rp.evaluate("window.__running") is True)
    rp.eval_on_selector("#sw", "e=>{e.value=70;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))}")
    rp.wait_for_timeout(1700)
    chk("the width slider moved the island off its default",
        abs(rp.eval_on_selector("#island", "e=>Math.round(e.getBoundingClientRect().width)") - 130) > 8,
        rp.eval_on_selector("#island", "e=>Math.round(e.getBoundingClientRect().width)"))
    rp.evaluate("window.__calls.length = 0")
    rp.eval_on_selector("#btnReset", "e=>e.click()"); rp.wait_for_timeout(1700)
    chk("reset puts the look back",
        abs(rp.eval_on_selector("#island", "e=>Math.round(e.getBoundingClientRect().width)") - 130) <= 1,
        rp.eval_on_selector("#island", "e=>Math.round(e.getBoundingClientRect().width)"))
    chk("reset leaves the system-wide switch on",
        "On" in rp.eval_on_selector("#pwLabel", "e=>e.textContent")
        and rp.eval_on_selector("#pw", "e=>e.getAttribute('aria-checked')") == "true")
    chk("reset does not stop the floating island",
        "stopOverlay" not in rp.evaluate("window.__calls.map(c=>c[0])") and rp.evaluate("window.__running") is True)
    chk("reset stores the switch as it is",
        rp.evaluate("JSON.parse(localStorage.getItem('di.settings')).on") is True)
    rp.evaluate("window.__calls.length = 0")
    rp.evaluate("window.__sysState(true,true,false,'')"); rp.wait_for_timeout(300)
    chk("coming back to the app keeps the island running",
        rp.evaluate("window.__running") is True
        and "stopOverlay" not in rp.evaluate("window.__calls.map(c=>c[0])")
        and "On" in rp.eval_on_selector("#pwLabel", "e=>e.textContent"),
        rp.evaluate("window.__calls.map(c=>c[0])"))
    chk("the reset page has no errors", len(rerrs) == 0, rerrs[:3])
    rst.close()

    # ---- the rest of the app ---------------------------------------------
    pg.eval_on_selector("#accHead", "e=>e.click()"); pg.wait_for_timeout(600)
    chk("accordion closes", pg.eval_on_selector("#accLook", "e=>e.classList.contains('closed')"))
    pg.eval_on_selector("#accHead", "e=>e.click()"); pg.wait_for_timeout(400)
    pg.click("#grab"); pg.wait_for_timeout(700)
    chk("sheet collapses", pg.eval_on_selector("#sheet", "e=>e.classList.contains('collapsed')"))
    chk("back reopens the sheet", pg.evaluate("window.__onBack()") is True)
    pg.wait_for_timeout(900)

    pg.eval_on_selector("#btnNotif", "e=>e.click()"); pg.wait_for_timeout(200)
    chk("notification access button asks natively", "requestNotifAccess" in calls())

    for s in ["music", "idle", "incoming", "idle", "calling", "music", "ongoing"]:
        pg.evaluate(f"window.__di.setState('{s}')"); pg.wait_for_timeout(60)
    pg.wait_for_timeout(2000)
    chk("no blank island after rapid switching",
        float(pg.eval_on_selector("#content", "e=>getComputedStyle(e).opacity")) > .9
        and pg.eval_on_selector("#content", "e=>e.innerHTML.length>50"))
    chk("no console/page errors", len(errs) == 0, errs[:3])

    # ---- position -------------------------------------------------------
    st = pg.eval_on_selector("#stage", "e=>{const r=e.getBoundingClientRect();return {x:r.x,w:r.width,bottom:r.bottom}}")
    pg.eval_on_selector("#sx", "e=>{e.value=0;e.dispatchEvent(new Event('input',{bubbles:true}))}")
    pg.wait_for_timeout(700)
    chk("0% horizontal puts the island at the left edge",
        abs(pg.eval_on_selector("#island", "e=>e.getBoundingClientRect().x") - st["x"]) < 8)
    pg.eval_on_selector("#sx", "e=>{e.value=100;e.dispatchEvent(new Event('input',{bubbles:true}))}")
    pg.wait_for_timeout(700)
    chk("100% horizontal puts the island at the right edge",
        abs((pg.eval_on_selector("#island", "e=>e.getBoundingClientRect().right")) - (st["x"] + st["w"])) < 8)
    pg.eval_on_selector("#sy", "e=>{e.value=100;e.dispatchEvent(new Event('input',{bubbles:true}))}")
    pg.wait_for_timeout(700)
    chk("100% vertical puts the island at the bottom of the stage",
        pg.eval_on_selector("#island", "e=>e.getBoundingClientRect().bottom") > st["bottom"] - 14)
    chk("position reaches the floating window", "setOverlayPosition" in calls())

    # ---- a drag must not cross into Java on every frame -------------------
    # the position sliders fire once per animation frame, and every one of those
    # used to cross the bridge into Java, where the service rewrote its prefs and
    # re-laid-out the system overlay window: ~60 binder calls, ~60 disk writes
    # and ~60 window relayouts a second, for a value that only has to be right
    # when the finger stops
    pos = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, color_scheme="dark")
    pos.add_init_script(MOCK)
    pp = pos.new_page()
    perrs = []
    pp.on("pageerror", lambda e: perrs.append(str(e)))
    pp.goto(URL); pp.wait_for_timeout(900)
    pp.evaluate("window.__calls.length = 0")
    drag_ms = pp.evaluate("""new Promise(function(res){
        var el = document.getElementById('sx'), n = 0, t0 = performance.now();
        window.__steps = 0;
        function step(){
          el.value = String(n % 2 ? 8 : 92);          /* keeps changing, like a drag */
          el.dispatchEvent(new Event('input', {bubbles:true}));
          window.__steps++;
          if(++n < 80) requestAnimationFrame(step); else res(performance.now() - t0);
        }
        requestAnimationFrame(step);
      })""")
    pp.wait_for_timeout(400)
    steps = pp.evaluate("window.__steps")
    pushes = pp.evaluate("window.__calls.filter(function(c){return c[0]==='setOverlayPosition'}).length")
    # one push per animation frame before, at most one per 80 ms now - checked
    # against the real elapsed time so the bound does not depend on frame rate
    chk("dragging a position slider does not cross into Java on every frame",
        pushes < steps and pushes <= drag_ms / 80.0 + 2, (pushes, steps, round(drag_ms)))
    chk("a drag still moves the floating island while it runs", pushes >= 1, pushes)
    pp.evaluate("window.__calls.length = 0")
    pp.eval_on_selector("#sy", "e=>{e.value=70;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))}")
    pp.wait_for_timeout(400)
    lastpos = pp.evaluate("(function(){var c=window.__calls.filter(function(x){return x[0]==='setOverlayPosition'});return c.length?c[c.length-1]:null})()")
    sxNow = int(pp.eval_on_selector("#sx", "e=>e.value"))
    chk("the last value of a drag reaches the floating window at once",
        lastpos is not None and lastpos[1] == sxNow and lastpos[2] == 70, (lastpos, sxNow))
    chk("the position page has no errors", len(perrs) == 0, perrs[:3])
    pos.close()

    # ---- lock screen toggle ---------------------------------------------
    chk("lock screen is on by default", "Show on lock screen" in pg.eval_on_selector("#lkLabel", "e=>e.textContent"))
    pg.eval_on_selector("#lk", "e=>e.click()"); pg.wait_for_timeout(200)
    chk("lock screen toggle reaches the window", last("setOverlayLock")[1] is False, last("setOverlayLock"))
    chk("lock screen label follows", "Hidden" in pg.eval_on_selector("#lkLabel", "e=>e.textContent"))
    pg.eval_on_selector("#lk", "e=>e.click()"); pg.wait_for_timeout(200)
    chk("lock screen toggle turns back on", last("setOverlayLock")[1] is True, last("setOverlayLock"))
    pg.eval_on_selector("#btnReset", "e=>e.click()")
    pg.wait_for_timeout(1500)

    # ---- the size controls must survive a short screen -------------------
    small = b.new_context(viewport={"width": 360, "height": 640}, device_scale_factor=2, color_scheme="dark")
    small.add_init_script(MOCK)
    sp = small.new_page()
    sp.goto(URL); sp.wait_for_timeout(800)
    chk("size controls keep their height on a short screen",
        sp.eval_on_selector("#accLook", "e=>e.getBoundingClientRect().height") > 200,
        sp.eval_on_selector("#accLook", "e=>e.getBoundingClientRect().height"))
    sp.eval_on_selector("#sw", "e=>e.scrollIntoView({block:'center'})")
    sp.wait_for_timeout(400)
    chk("width slider is reachable by scrolling",
        sp.eval_on_selector("#sw", "e=>{const r=e.getBoundingClientRect();return r.top>0 && r.bottom<window.innerHeight}"))
    sp.eval_on_selector("#sw", "e=>{e.value=60;e.dispatchEvent(new Event('input',{bubbles:true}))}")
    sp.wait_for_timeout(1600)
    chk("shrinking from the slider works on a short screen",
        sp.eval_on_selector("#island", "e=>Math.round(e.getBoundingClientRect().width)") < 130,
        sp.eval_on_selector("#island", "e=>Math.round(e.getBoundingClientRect().width)"))
    small.close()

    # ---- the keyboard belongs to the buttons, not to the island ----------
    # Enter or Space on the island itself expands/collapses it, but the island
    # also holds real buttons. Their keydown bubbled up to that shortcut, which
    # cancelled the button's own activation and clicked the island instead: a
    # keyboard user pressing Play, Accept or Decline closed the island.
    kb = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, color_scheme="dark")
    kb.add_init_script(MOCK)
    kp = kb.new_page()
    kerrs = []
    kp.on("pageerror", lambda e: kerrs.append(str(e)))
    kp.goto(URL); kp.wait_for_timeout(900)
    kp.click('#states .chip[data-s="music"]'); kp.wait_for_timeout(1700)
    chk("the player is open for the keyboard test", near(box_of(kp), 318, 128), box_of(kp))

    play_label = lambda: kp.eval_on_selector('#content [data-a="play"]', "e=>e.getAttribute('aria-label')")
    paused = lambda: kp.evaluate("!!document.querySelector('#content .rows.paused')")
    kp.focus('#content [data-a="play"]')
    chk("a button inside the island can take focus",
        kp.evaluate("document.activeElement && document.activeElement.getAttribute('data-a')") == "play")
    kp.keyboard.press("Enter"); kp.wait_for_timeout(1200)
    chk("Enter on Play pauses, it does not collapse the island",
        kp.evaluate("window.__di.state") == "music" and near(box_of(kp), 318, 128), box_of(kp))
    chk("Enter on Play really pressed the button", paused() and play_label() == "Play", (paused(), play_label()))
    kp.keyboard.press(" "); kp.wait_for_timeout(1200)
    chk("Space on Play resumes, it does not collapse the island",
        kp.evaluate("window.__di.state") == "music" and not paused() and play_label() == "Pause",
        (kp.evaluate("window.__di.state"), paused(), play_label()))

    kp.click('#states .chip[data-s="incoming"]'); kp.wait_for_timeout(1700)
    kp.focus('#content [data-a="accept"]')
    kp.keyboard.press("Enter"); kp.wait_for_timeout(1700)
    chk("Enter on Accept answers the call, it does not dismiss the island",
        kp.evaluate("window.__di.state") == "ongoing", kp.evaluate("window.__di.state"))

    # the island's own shortcut still works when the island has the focus
    kp.evaluate("window.__di.setState('music')"); kp.wait_for_timeout(1700)
    kp.focus("#island")
    chk("the island itself can take focus", kp.evaluate("document.activeElement && document.activeElement.id") == "island")
    kp.keyboard.press("Enter"); kp.wait_for_timeout(1700)
    chk("Enter on the island itself still collapses it",
        kp.evaluate("window.__di.state") == "idle" and near(box_of(kp), 130, 38), box_of(kp))
    kp.keyboard.press(" "); kp.wait_for_timeout(1700)
    chk("Space on the island itself still opens it again",
        kp.evaluate("window.__di.state") == "music", kp.evaluate("window.__di.state"))
    chk("the keyboard page has no errors", len(kerrs) == 0, kerrs[:3])
    kb.close()

    # ---- the wallpaper clock ---------------------------------------------
    # it used to wake every second to redraw something that only changes once a
    # minute, and to reformat the date string on every one of those wakeups
    clk = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, color_scheme="dark")
    clk.add_init_script(MOCK)
    clk.add_init_script(CLOCK_FAKE)
    cp = clk.new_page()
    cerrs = []
    cp.on("pageerror", lambda e: cerrs.append(str(e)))
    cp.goto(URL); cp.wait_for_timeout(900)
    hhmm = ("(function(){var d=new Date();var h=d.getHours()%12;if(h===0)h=12;"
            "return h+':'+('0'+d.getMinutes()).slice(-2)})()")
    clock_text = lambda: cp.eval_on_selector("#clock", "e=>e.textContent")
    chk("the clock shows the current time", clock_text() == cp.evaluate(hhmm), clock_text())
    chk("the date shows today",
        cp.eval_on_selector("#date", "e=>e.textContent") ==
        cp.evaluate("new Date().toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric'})"))
    cp.evaluate("window.__dateCalls = 0; window.__nowCalls = 0")
    cp.wait_for_timeout(4500)
    woken = cp.evaluate("window.__dateCalls + window.__nowCalls")
    chk("the clock wakes about once a minute, not every second", woken <= 2, woken)
    before = clock_text()
    cp.evaluate("window.__off += 3*60000")
    cp.evaluate("window.dispatchEvent(new Event('focus'))")
    cp.wait_for_timeout(150)
    chk("coming back to the app refreshes a stale clock",
        clock_text() == cp.evaluate(hhmm) and clock_text() != before,
        (before, clock_text(), cp.evaluate(hhmm)))
    chk("the clock page has no errors", len(cerrs) == 0, cerrs[:3])
    clk.close()

    # ---- needless wakeups ------------------------------------------------
    # the fake status bar that owned #batFill went away in 1.3.0, but the app
    # kept waking every 30 s to ask the native shell for a battery level and
    # write it into a node that no longer exists - a timer that could never
    # change a pixel, plus a crossing into Java for it
    wake = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, color_scheme="dark")
    wake.add_init_script(MOCK)
    wake.add_init_script(WAKE_FAKE)
    wp = wake.new_page()
    werrs = []
    wp.on("pageerror", lambda e: werrs.append(str(e)))
    wp.goto(URL); wp.wait_for_timeout(2600)
    chk("nothing asks the native shell for a battery level it does not show",
        wp.evaluate("window.__batteryCalls") == 0, wp.evaluate("window.__batteryCalls"))
    chk("no half-minute wakeup is scheduled",
        wp.evaluate("window.__intervals.filter(function(d){return d>=5000})") == [],
        wp.evaluate("window.__intervals"))
    chk("the wakeup page has no errors", len(werrs) == 0, werrs[:3])
    wake.close()

    # ---- the overlay page itself -----------------------------------------
    ov = b.new_context(viewport={"width": 390, "height": 200}, device_scale_factor=3, color_scheme="dark")
    ov.add_init_script(MOCK)
    op = ov.new_page()
    oerrs = []
    op.on("pageerror", lambda e: oerrs.append(str(e)))
    op.goto(OVERLAY_URL)
    op.wait_for_timeout(1700)
    obox = lambda: op.eval_on_selector("#island", "e=>{const r=e.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height)}}")
    chk("overlay idle size", near(obox(), 130, 38), obox())
    chk("overlay island sits at the top of its window",
        op.eval_on_selector("#island", "e=>Math.round(e.getBoundingClientRect().top)") == 0,
        op.eval_on_selector("#island", "e=>Math.round(e.getBoundingClientRect().top)"))
    chk("overlay reports its size to native", "resize" in op.evaluate("window.__calls.map(c=>c[0])"))
    chk("overlay body is transparent",
        op.evaluate("getComputedStyle(document.body).backgroundColor").startswith("rgba(0, 0, 0, 0)"))
    op.evaluate("window.__notify('Messages','Maya Chen','See you at 8')")
    op.wait_for_timeout(1500)
    chk("notification grows the island", near(obox(), 318, 94), obox())
    chk("notification shows its text", "Maya Chen" in op.eval_on_selector("#content", "e=>e.textContent"))
    op.wait_for_timeout(6600)
    # the springs are deliberately under-damped, so wait until the collapse has
    # actually stopped moving instead of sampling it mid-bounce (this used to
    # flake ~1 run in 3, sometimes passing through the right box on its way past)
    prev = None
    for _ in range(30):
        g = obox()
        if near(g, 130, 38) and g == prev: break
        prev = g
        op.wait_for_timeout(100)
    chk("notification auto-dismisses", near(obox(), 130, 38), obox())
    op.evaluate("window.__setState('music')"); op.wait_for_timeout(1500)
    chk("native can drive the overlay state", near(obox(), 318, 128), obox())
    op.evaluate("window.__t1Node = document.querySelector('#content .t1')")
    op.evaluate("window.__setState('music')"); op.wait_for_timeout(400)
    chk("the overlay does not rebuild a view it is already showing",
        op.evaluate("document.querySelector('#content .t1') === window.__t1Node"))
    chk("a repeated state leaves the island the same size", near(obox(), 318, 128), obox())
    op.click("#island"); op.wait_for_timeout(1600)
    chk("tapping the overlay collapses it", near(obox(), 130, 38), obox())
    chk("overlay tells native when it changes state", "stateChanged" in op.evaluate("window.__calls.map(c=>c[0])"))

    olast = lambda n: op.evaluate("(function(){var c=window.__calls.filter(x=>x[0]==='%s');return c.length?c[c.length-1]:null})()" % n)
    op.evaluate("window.__call('Ravi Kumar','Incoming call')")
    op.wait_for_timeout(1600)
    chk("a real call opens the demo's incoming view", near(obox(), 312, 88), obox())
    chk("the caller's name is shown", "Ravi" in op.eval_on_selector("#content", "e=>e.textContent"))
    chk("there is one green accept button",
        op.eval_on_selector_all("#content .btn.green", "els=>els.length") == 1)
    chk("there is one red decline button",
        op.eval_on_selector_all("#content .btn.red", "els=>els.length") == 1)
    chk("the buttons are round and unlabelled, like the demo",
        op.eval_on_selector("#content .btn.green", "e=>e.textContent.trim()") == ""
        and op.eval_on_selector("#content .btn.green", "e=>Math.round(e.getBoundingClientRect().width)") == 42)
    op.click("#content .btn.green")
    op.wait_for_timeout(400)
    chk("the green button answers the real call", olast("callAction")[1] == "accept", olast("callAction"))
    op.evaluate("window.__callEnd()")
    op.wait_for_timeout(1600)
    chk("ending the call collapses the island", near(obox(), 130, 38), obox())

    # ---- real music ------------------------------------------------------
    op.evaluate("window.__music('Kesariya','Arijit Singh',true)")
    op.wait_for_timeout(1600)
    chk("a playing song opens the music view", near(obox(), 318, 128), obox())
    chk("the real song title is shown", "Kesariya" in op.eval_on_selector("#content", "e=>e.textContent"))
    chk("the real artist is shown", "Arijit" in op.eval_on_selector("#content", "e=>e.textContent"))

    # the service polls the player every 1.5s while it plays, and every report of
    # an unchanged song used to rebuild the play icon from scratch
    op.evaluate("""window.__svgRef = document.querySelector("#content [data-a='play'] svg")""")
    op.evaluate("for(var i=0;i<3;i++) window.__music('Kesariya','Arijit Singh',true)")
    op.wait_for_timeout(250)
    chk("repeating the same song report rebuilds nothing",
        op.evaluate("""document.querySelector("#content [data-a='play'] svg") === window.__svgRef"""))
    chk("the song survives repeated reports",
        "Kesariya" in op.eval_on_selector("#content", "e=>e.textContent"))
    op.evaluate("window.__music('Kesariya','Arijit Singh',false)")
    op.wait_for_timeout(250)
    chk("a report that playback stopped still flips the icon",
        op.eval_on_selector('#content [data-a="play"]', "e=>e.getAttribute('aria-label')") == "Play"
        and op.eval_on_selector("#content .rows", "e=>e.classList.contains('paused')"))
    op.evaluate("window.__music('Tum Hi Ho','Arijit Singh',true)")
    op.wait_for_timeout(250)
    chk("a new song still updates the text",
        "Tum Hi Ho" in op.eval_on_selector("#content", "e=>e.textContent"))
    chk("a report that playback resumed still flips the icon back",
        op.eval_on_selector('#content [data-a="play"]', "e=>e.getAttribute('aria-label')") == "Pause")
    op.evaluate("window.__music('Kesariya','Arijit Singh',true)")
    op.wait_for_timeout(250)
    chk("there is a pause button while playing",
        op.eval_on_selector('#content [data-a="play"]', "e=>e.getAttribute('aria-label')") == "Pause")
    op.click('#content [data-a="play"]'); op.wait_for_timeout(300)
    chk("pause goes to the real player", olast("media")[1] == "pause", olast("media"))
    chk("the icon flips to play",
        op.eval_on_selector('#content [data-a="play"]', "e=>e.getAttribute('aria-label')") == "Play")
    op.click('#content [data-a="next"]'); op.wait_for_timeout(300)
    chk("next goes to the real player", olast("media")[1] == "next", olast("media"))
    op.click('#content [data-a="prev"]'); op.wait_for_timeout(300)
    chk("previous goes to the real player", olast("media")[1] == "prev", olast("media"))
    op.evaluate("window.__musicEnd()")
    op.wait_for_timeout(1600)
    chk("stopping the music collapses the island", near(obox(), 130, 38), obox())

    # ---- the player must not take the island from a call or a notification --
    # the service polls the player every 1.5 s, and every one of those polls
    # used to hand the island back to the music view: a notification with seven
    # seconds on screen lived one and a half, and a ringing call lost its green
    # and red buttons while the phone was still ringing
    def settle_box(w=130, h=38):
        prev = None
        for _ in range(30):
            g = obox()
            if near(g, w, h) and g == prev:
                return g
            prev = g
            op.wait_for_timeout(100)
        return obox()

    otext = lambda: op.eval_on_selector("#content", "e=>e.textContent")
    op.evaluate("window.__music('Kesariya','Arijit Singh',true)")
    op.wait_for_timeout(1500)
    chk("the player opens the island from idle", near(obox(), 318, 128), obox())
    op.evaluate("window.__notify('Messages','Maya Chen','See you at 8')")
    op.wait_for_timeout(1400)
    chk("a notification takes the island from the player", "Maya Chen" in otext(), otext())
    op.evaluate("window.__music('Kesariya','Arijit Singh',true)")      # the next 1.5 s poll
    op.wait_for_timeout(600)
    chk("the next player poll leaves the notification alone", "Maya Chen" in otext(), otext())
    chk("and does not resize the island under it", near(obox(), 318, 94), obox())
    op.wait_for_timeout(6400)
    g = settle_box()
    chk("the notification still gets its full time on screen", near(g, 130, 38), g)
    op.evaluate("window.__music('Kesariya','Arijit Singh',true)")
    op.wait_for_timeout(1500)
    chk("the player is back once the notification is gone",
        near(obox(), 318, 128) and "Kesariya" in otext(), obox())

    op.evaluate("window.__call('Ravi Kumar','Incoming call')")
    op.wait_for_timeout(1500)
    chk("a ringing call takes the island from the player", near(obox(), 312, 88), obox())
    op.evaluate("window.__music('Kesariya','Arijit Singh',true)")
    op.wait_for_timeout(600)
    chk("the player poll leaves a ringing call alone", "Ravi" in otext(), otext())
    chk("the answer buttons are still there while it rings",
        op.eval_on_selector_all("#content .btn.green", "els=>els.length") == 1
        and op.eval_on_selector_all("#content .btn.red", "els=>els.length") == 1)
    op.evaluate("window.__callEnd()")
    op.wait_for_timeout(1500)
    op.evaluate("window.__music('Kesariya','Arijit Singh',true)")
    op.wait_for_timeout(1500)
    chk("the player returns when the call ends",
        near(obox(), 318, 128) and "Kesariya" in otext(), obox())
    op.evaluate("window.__musicEnd()")
    op.wait_for_timeout(1600)
    chk("and leaves again when the music stops", near(obox(), 130, 38), obox())

    # ---- the native window has to grow before the island does ------------
    # the island is drawn inside a native window cut to exactly its own size, so
    # a morph that makes it bigger has to grow that window first or the island is
    # clipped at the old window's edges for the whole animation. setState did
    # that; the size sliders went through __setConfig, which only moved the
    # targets - so dragging Width or Height up on the floating island morphed it
    # inside a window still sized for the old box and the growing pill was cut
    # off on all four sides until the springs stopped and the settle resized it
    chk("the island is idle before the size test", near(obox(), 130, 38), obox())
    chk("the window starts out the island's size", olast("resize")[1:] == [130, 38], olast("resize"))
    op.evaluate("window.__setConfig(1.25,1.6,1,0.65)")
    r = olast("resize")
    chk("a bigger island grows its window at once, not when the morph ends",
        r[1] >= 162 and r[2] >= 60, r)
    op.wait_for_timeout(150)
    chk("the window is not left at the old size mid-morph", olast("resize")[1] >= 162, olast("resize"))
    g = settle_box(163, 61)
    chk("the island really does grow", near(g, 163, 61), g)
    chk("the window still covers the island it settled at",
        olast("resize")[1] >= g["w"] and olast("resize")[2] >= g["h"], (olast("resize"), g))
    op.evaluate("window.__setConfig(1,1,1,0.65)")
    chk("shrinking does not shrink the window out from under the island",
        olast("resize")[1] >= 163, olast("resize"))
    g = settle_box()
    for _ in range(25):                      # the settle resize lands a beat later
        if olast("resize")[1:] == [130, 38]:
            break
        op.wait_for_timeout(100)
    chk("and the window follows it down once it has settled",
        near(g, 130, 38) and olast("resize")[1:] == [130, 38], (g, olast("resize")))
    op.evaluate("window.__setState('music')")
    r = olast("resize")
    chk("a state change still grows the window first", r[1] >= 318 and r[2] >= 128, r)
    op.evaluate("window.__setState('idle')")
    op.wait_for_timeout(1700)

    op.evaluate("window.__setMax(240)"); op.evaluate("window.__setState('music')"); op.wait_for_timeout(1500)
    chk("overlay honours the max width it is given", obox()["w"] <= 240, obox())
    chk("overlay has no errors", len(oerrs) == 0, oerrs[:3])

    # ---- the render loop must not force a layout every frame --------------
    # paint() runs on every frame of every morph and read window.innerWidth
    # there, which makes the browser flush the style and layout the previous
    # frame had just dirtied by writing width and height: a synchronous layout
    # sixty times a second, for a number that only changes when the window does
    lay = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, color_scheme="dark")
    lay.add_init_script(MOCK)
    lay.add_init_script(VIEWPORT_FAKE)
    lp = lay.new_page()
    lerrs = []
    lp.on("pageerror", lambda e: lerrs.append(str(e)))
    lp.goto(URL); lp.wait_for_timeout(900)
    chk("the viewport read counter is wired up",
        lp.evaluate("(function(){window.__vwReads=0; void window.innerWidth; return window.__vwReads})()") == 1)
    lp.evaluate("window.__vwReads = 0")
    lp.evaluate("window.__di.setState('music')")
    lp.wait_for_timeout(500)                       # mid-morph, the loop is running
    reads = lp.evaluate("window.__vwReads")
    chk("the render loop does not ask for the viewport on every frame", reads <= 1, reads)
    lp.wait_for_timeout(1700)
    chk("the morph still lands on the right size", near(box_of(lp), 318, 128), box_of(lp))
    # the cached width has to follow a real resize, or the island overflows it
    lp.set_viewport_size({"width": 300, "height": 700})
    lp.wait_for_timeout(1800)
    w = lp.eval_on_selector("#island", "e=>Math.round(e.getBoundingClientRect().width)")
    chk("a narrower window still clamps the island", w <= 284, w)
    chk("and does not squash it any further than the clamp", w >= 260, w)
    chk("the render page has no errors", len(lerrs) == 0, lerrs[:3])
    lay.close()

    # ---- the position maths must not force a layout every frame -----------
    # applyPos() runs on every frame of a size-slider drag, and it read the
    # stage's box each time. paint() had just written the island's width and
    # height, so that read flushed the layout those writes had dirtied: write,
    # flush, write, flush, sixty times a second, for a box that only changes
    # when the window does or the sheet resizes.
    pos2 = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, color_scheme="dark")
    pos2.add_init_script(MOCK)
    pos2.add_init_script(STAGE_FAKE)
    qp = pos2.new_page()
    qerrs = []
    qp.on("pageerror", lambda e: qerrs.append(str(e)))
    qp.goto(URL); qp.wait_for_timeout(900)
    chk("the stage read counter is wired up",
        qp.evaluate("(function(){window.__stageReads=0; void document.getElementById('stage').getBoundingClientRect(); return window.__stageReads})()") == 1)
    qp.evaluate("window.__stageReads = 0")
    qp.evaluate("""new Promise(function(res){
        var el = document.getElementById('sw'), n = 0;
        window.__steps = 0;
        function step(){
          el.value = String(60 + (n % 60));        /* keeps changing, like a drag */
          el.dispatchEvent(new Event('input', {bubbles:true}));
          window.__steps++;
          if(++n < 80) requestAnimationFrame(step); else res(1);
        }
        requestAnimationFrame(step);
      })""")
    qp.wait_for_timeout(300)
    steps = qp.evaluate("window.__steps")
    sreads = qp.evaluate("window.__stageReads")
    chk("dragging a size slider does not measure the stage on every frame",
        steps >= 60 and sreads <= 1, (sreads, steps))

    # the cached box still has to follow the stage, or the island stops
    # honouring the position it is set to
    geo = ("(function(){var s=document.getElementById('stage').getBoundingClientRect(),"
           "i=document.getElementById('island').getBoundingClientRect();"
           "return {top:Math.round(s.top),h:Math.round(s.height),ib:Math.round(i.bottom),"
           "il:Math.round(i.left),ir:Math.round(i.right),iw:Math.round(i.width)}})()")
    qp.eval_on_selector("#sx", "e=>{e.value=0;e.dispatchEvent(new Event('input',{bubbles:true}))}")
    qp.eval_on_selector("#sy", "e=>{e.value=70;e.dispatchEvent(new Event('input',{bubbles:true}))}")
    qp.wait_for_timeout(900)
    g = qp.evaluate(geo)
    chk("0% horizontal still puts the island at the left edge of the stage",
        abs(g["il"] - 0) < 8, g)
    want = g["top"] + 0.70 * (g["h"] - 38) + 38
    chk("70% vertical still puts the island where it says", abs(g["ib"] - want) < 5, (g, round(want)))

    # the stage also changes size with no window resize at all - the sheet
    # animating, the accordion, a WebView that re-lays itself out. A
    # ResizeObserver catches those, and hands over the new box already measured
    qp.evaluate("document.getElementById('sheet').style.maxHeight = '140px'")
    qp.wait_for_timeout(800)
    g2 = qp.evaluate(geo)
    want2 = g2["top"] + 0.70 * (g2["h"] - 38) + 38
    chk("the island follows a stage that resized without the window doing so",
        g2["h"] > g["h"] + 100 and abs(g2["ib"] - want2) < 5, (g, g2, round(want2)))

    # and the sheet collapsing, which was already handled, must still work
    qp.evaluate("document.getElementById('sheet').style.maxHeight = ''")
    qp.wait_for_timeout(900)
    qp.click("#grab")
    qp.wait_for_timeout(1400)
    g3 = qp.evaluate(geo)
    want3 = g3["top"] + 0.70 * (g3["h"] - 38) + 38
    chk("the island follows the stage when the sheet collapses",
        g3["h"] > g["h"] + 100 and abs(g3["ib"] - want3) < 5, (g, g3, round(want3)))

    # a window that really resizes must refresh the cached box, not go stale
    qp.set_viewport_size({"width": 320, "height": 640})
    qp.wait_for_timeout(1200)
    g4 = qp.evaluate(geo)
    want4 = g4["top"] + 0.70 * (g4["h"] - 38) + 38
    chk("a real resize refreshes the cached stage box",
        abs(g4["ib"] - want4) < 6 and g4["iw"] <= 320, (g4, round(want4)))
    chk("the position page has no errors", len(qerrs) == 0, qerrs[:3])
    pos2.close()

    b.close()

print("\n%d checks, %d failed" % (checks[0], len(fails)))
sys.exit(1 if fails else 0)
