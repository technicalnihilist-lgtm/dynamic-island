"""Behavioural test run for the Dynamic Island web app.

    pip install playwright && playwright install chromium
    python tools/test_app.py [path/to/index.html]

Every check drives the real page in a real browser and asserts on geometry,
visibility, accessibility state and timing. Exit code is non-zero on failure.
"""
import os
import sys
from playwright.sync_api import sync_playwright

URL = "file://" + os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else
                                 os.path.join(os.path.dirname(__file__), "..", "app", "index.html"))
EXE = os.environ.get("CHROME_PATH")  # optional: point at a specific chromium build
fails=[]
checks=[0]
def chk(name, cond, extra=""):
    checks[0]+=1
    print(("PASS " if cond else "FAIL ")+name+(("  -> "+str(extra)) if not cond else ""))
    if not cond: fails.append(name)

with sync_playwright() as p:
    b=p.chromium.launch(executable_path=EXE, args=["--no-sandbox"]) if EXE else p.chromium.launch(args=["--no-sandbox"])
    ctx=b.new_context(viewport={"width":390,"height":844}, device_scale_factor=3, color_scheme="dark")
    pg=ctx.new_page()
    errs=[]
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    pg.goto(URL); pg.wait_for_timeout(800)

    box=lambda: pg.eval_on_selector("#island","e=>{const r=e.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height),y:Math.round(r.y)}}")
    near=lambda g,w,h: abs(g["w"]-w)<=1 and abs(g["h"]-h)<=1
    def tap_body():
        # 8px inside the island's top-left corner: never a button
        r = pg.eval_on_selector("#island","e=>{const b=e.getBoundingClientRect();return [b.x,b.y]}")
        pg.mouse.click(r[0]+8, r[1]+8)

    chk("idle geometry", near(box(),112,32), box())

    for st,exp in [("incoming",(272,78)),("calling",(240,58)),("music",(276,112))]:
        pg.click(f'#states .chip[data-s="{st}"]'); pg.wait_for_timeout(1700)
        g=box(); chk(f"state {st} size", near(g,*exp), g)
        chk(f"state {st} content visible", pg.eval_on_selector("#content","e=>getComputedStyle(e).opacity")=="1")
        chk(f"state {st} content not empty", pg.eval_on_selector("#content","e=>e.innerHTML.length>50"))

    # accept -> ongoing
    pg.click('#states .chip[data-s="incoming"]'); pg.wait_for_timeout(1300)
    pg.click('#island [data-a="accept"]'); pg.wait_for_timeout(1700)
    g=box(); chk("state ongoing size", near(g,276,104), g)
    chk("ongoing highlights the Incoming chip", pg.eval_on_selector('.chip[data-s="incoming"]',"e=>e.classList.contains('on')"))
    t1=pg.eval_on_selector('#content [data-role="time"]',"e=>e.textContent")
    pg.wait_for_timeout(1100)
    t2=pg.eval_on_selector('#content [data-role="time"]',"e=>e.textContent")
    chk("call timer ticks", t1!=t2, (t1,t2))
    pg.click('#island [data-a="mute"]'); pg.wait_for_timeout(200)
    chk("mute aria-pressed", pg.eval_on_selector('#island [data-a="mute"]',"e=>e.getAttribute('aria-pressed')")=="true")
    pg.click('#island [data-a="end"]'); pg.wait_for_timeout(1750)
    chk("end -> idle", near(box(),112,32), box())
    chk("timer stops on idle", pg.eval_on_selector("#content","e=>e.innerHTML.trim()")=="")

    # music controls
    pg.click('#states .chip[data-s="music"]'); pg.wait_for_timeout(1300)
    pg.click('#island [data-a="play"]'); pg.wait_for_timeout(200)
    chk("pause sets paused class", pg.eval_on_selector("#content .rows","e=>e.classList.contains('paused')"))
    chk("play btn label flips", pg.eval_on_selector('#island [data-a="play"]',"e=>e.getAttribute('aria-label')")=="Play")
    name0=pg.eval_on_selector("#content .col .t1","e=>e.textContent")
    pg.click('#island [data-a="next"]'); pg.wait_for_timeout(200)
    name1=pg.eval_on_selector("#content .col .t1","e=>e.textContent")
    chk("next changes track", name0!=name1, (name0,name1))

    # tap an empty part of the island body
    tap_body(); pg.wait_for_timeout(1750)
    chk("tap body collapses", near(box(),112,32), box())
    tap_body(); pg.wait_for_timeout(1750)
    chk("tap body reopens last state (music)", near(box(),276,112), box())

    # power
    pg.click("#pw"); pg.wait_for_timeout(900)
    chk("power off hides island", float(pg.eval_on_selector("#island","e=>getComputedStyle(e).opacity"))<0.2)
    chk("power off label", "Off" in pg.eval_on_selector("#pwLabel","e=>e.textContent"))
    chk("power off pointer-events none", pg.eval_on_selector("#island","e=>getComputedStyle(e).pointerEvents")=="none")
    pg.click('#states .chip[data-s="incoming"]'); pg.wait_for_timeout(900)
    chk("chip wakes the island up", float(pg.eval_on_selector("#island","e=>getComputedStyle(e).opacity"))>0.8)
    chk("chip wake sets power label On", "On" in pg.eval_on_selector("#pwLabel","e=>e.textContent"))

    # sliders
    pg.eval_on_selector("#sw","e=>{e.value=115;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))}")
    pg.wait_for_timeout(1700)
    chk("width slider scales island", pg.eval_on_selector("#island","e=>Math.round(e.getBoundingClientRect().width)")>300)
    pg.click("#btnReset"); pg.wait_for_timeout(1750)
    chk("reset restores width", near(box(),272,78), box())

    # accordion + sheet
    pg.click("#accHead"); pg.wait_for_timeout(600)
    chk("accordion closes", pg.eval_on_selector("#accLook","e=>e.classList.contains('closed')"))
    pg.click("#accHead"); pg.wait_for_timeout(400)
    pg.click("#grab"); pg.wait_for_timeout(700)
    chk("sheet collapses", pg.eval_on_selector("#sheet","e=>e.classList.contains('collapsed')"))

    # back button behaviour
    r=pg.evaluate("window.__onBack()"); pg.wait_for_timeout(1750)
    chk("back closes the island first", r==True and near(box(),112,32), (r,box()))
    r=pg.evaluate("window.__onBack()"); pg.wait_for_timeout(400)
    chk("back reopens the sheet next", r==True and not pg.eval_on_selector("#sheet","e=>e.classList.contains('collapsed')"))
    chk("back exits when nothing is left", pg.evaluate("window.__onBack()")==False)

    # persistence
    pg.click("#pw"); pg.wait_for_timeout(400)
    pg.reload(); pg.wait_for_timeout(1000)
    chk("power state persists across reload", "Off" in pg.eval_on_selector("#pwLabel","e=>e.textContent"))
    pg.click("#pw"); pg.wait_for_timeout(400)
    pg.reload(); pg.wait_for_timeout(1000)
    chk("power on persists too", "On" in pg.eval_on_selector("#pwLabel","e=>e.textContent"))

    # rapid state thrashing must never leave the island blank or mis-sized
    for s in ["music","idle","incoming","idle","calling","music","ongoing"]:
        pg.evaluate(f"window.__di.setState('{s}')"); pg.wait_for_timeout(60)
    pg.wait_for_timeout(2000)
    chk("no blank island after rapid switching", float(pg.eval_on_selector("#content","e=>getComputedStyle(e).opacity"))>0.9 and pg.eval_on_selector("#content","e=>e.innerHTML.length>50"))

    chk("no console/page errors", len(errs)==0, errs[:3])
    b.close()
print("\n%d checks, %d failed" % (checks[0], len(fails)))
sys.exit(1 if fails else 0)
