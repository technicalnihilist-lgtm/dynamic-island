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

    box = lambda: pg.eval_on_selector("#island", "e=>{const r=e.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height),y:Math.round(r.top)}}")
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
    op.evaluate("window.__setMax(240)"); op.evaluate("window.__setState('music')"); op.wait_for_timeout(1500)
    chk("overlay honours the max width it is given", obox()["w"] <= 240, obox())
    chk("overlay has no errors", len(oerrs) == 0, oerrs[:3])

    b.close()

print("\n%d checks, %d failed" % (checks[0], len(fails)))
sys.exit(1 if fails else 0)
