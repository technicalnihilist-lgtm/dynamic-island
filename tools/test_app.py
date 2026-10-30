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
  setOverlayState: function(s){ rec('setOverlayState', [s]); },
  setOverlayConfig: function(){ rec('setOverlayConfig', arguments); }
};
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

    box = lambda: pg.eval_on_selector("#island", "e=>{const r=e.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height)}}")
    near = lambda g, w, h: abs(g["w"] - w) <= 1 and abs(g["h"] - h) <= 1
    calls = lambda: pg.evaluate("window.__calls.map(c=>c[0])")
    last = lambda n: pg.evaluate("(function(){var c=window.__calls.filter(x=>x[0]==='%s');return c.length?c[c.length-1]:null})()" % n)

    # ---- preview geometry -------------------------------------------------
    chk("idle geometry", near(box(), 112, 32), box())
    for st, exp in [("incoming", (272, 78)), ("calling", (240, 58)), ("music", (276, 112))]:
        pg.click(f'#states .chip[data-s="{st}"]'); pg.wait_for_timeout(1700)
        g = box(); chk(f"state {st} size", near(g, *exp), g)
        chk(f"state {st} content visible", pg.eval_on_selector("#content", "e=>getComputedStyle(e).opacity") == "1")

    pg.click('#states .chip[data-s="incoming"]'); pg.wait_for_timeout(1300)
    pg.click('#island [data-a="accept"]'); pg.wait_for_timeout(1700)
    chk("ongoing size", near(box(), 276, 104), box())
    t1 = pg.eval_on_selector('#content [data-role="time"]', "e=>e.textContent"); pg.wait_for_timeout(1100)
    chk("call timer ticks", t1 != pg.eval_on_selector('#content [data-role="time"]', "e=>e.textContent"))
    pg.click('#island [data-a="end"]'); pg.wait_for_timeout(1750)
    chk("end -> idle", near(box(), 112, 32), box())

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

    pg.click("#pw"); pg.wait_for_timeout(800)
    chk("switch turns on", "On" in pg.eval_on_selector("#pwLabel", "e=>e.textContent"))
    chk("overlay service started", "startOverlay" in calls())
    chk("preview island steps aside", pg.eval_on_selector("#island", "e=>getComputedStyle(e).visibility") == "hidden")
    chk("stage shows the live tip", float(pg.eval_on_selector("#systip", "e=>getComputedStyle(e).opacity")) > .5)
    chk("switch state persists", pg.evaluate("localStorage.getItem('di.settings')").find('"on":true') >= 0)

    pg.click('#states .chip[data-s="music"]'); pg.wait_for_timeout(900)
    chk("chips drive the floating island", last("setOverlayState")[1] == "music", last("setOverlayState"))
    pg.eval_on_selector("#sw", "e=>{e.value=110;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))}")
    pg.wait_for_timeout(400)
    chk("sliders push config to the overlay", "setOverlayConfig" in calls())

    pg.click("#pw"); pg.wait_for_timeout(700)
    chk("switch turns off", "Off" in pg.eval_on_selector("#pwLabel", "e=>e.textContent"))
    chk("overlay service stopped", "stopOverlay" in calls())
    chk("preview island returns", pg.eval_on_selector("#island", "e=>getComputedStyle(e).visibility") == "visible")

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

    # ---- the overlay page itself -----------------------------------------
    ov = b.new_context(viewport={"width": 390, "height": 200}, device_scale_factor=3, color_scheme="dark")
    ov.add_init_script(MOCK)
    op = ov.new_page()
    oerrs = []
    op.on("pageerror", lambda e: oerrs.append(str(e)))
    op.goto(OVERLAY_URL)
    op.wait_for_timeout(800)
    obox = lambda: op.eval_on_selector("#island", "e=>{const r=e.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height)}}")
    chk("overlay idle size", near(obox(), 112, 32), obox())
    chk("overlay reports its size to native", "resize" in op.evaluate("window.__calls.map(c=>c[0])"))
    chk("overlay body is transparent",
        op.evaluate("getComputedStyle(document.body).backgroundColor").startswith("rgba(0, 0, 0, 0)"))
    op.evaluate("window.__notify('Messages','Maya Chen','See you at 8')")
    op.wait_for_timeout(1500)
    chk("notification grows the island", near(obox(), 280, 84), obox())
    chk("notification shows its text", "Maya Chen" in op.eval_on_selector("#content", "e=>e.textContent"))
    op.wait_for_timeout(6600)
    chk("notification auto-dismisses", near(obox(), 112, 32), obox())
    op.evaluate("window.__setState('music')"); op.wait_for_timeout(1500)
    chk("native can drive the overlay state", near(obox(), 276, 112), obox())
    op.click("#island"); op.wait_for_timeout(1600)
    chk("tapping the overlay collapses it", near(obox(), 112, 32), obox())
    chk("overlay has no errors", len(oerrs) == 0, oerrs[:3])

    b.close()

print("\n%d checks, %d failed" % (checks[0], len(fails)))
sys.exit(1 if fails else 0)
