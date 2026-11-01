# Dynamic Island · Liquid Glass

A Dynamic Island that actually lives on your screen. Flip the switch and it floats above every app
until you flip it back; flip it off and it is gone. It started as a single HTML mockup — this repo is
that mockup with its bugs fixed, rebuilt as a real Android app with a real system overlay, and shipped
as a signed APK.

**[⬇ Download the APK](https://github.com/technicalnihilist-lgtm/dynamic-island/releases/latest)** ·
Android 7.0+ · 102 KB · no internet permission

<img src="screenshots/app-sysmode.jpg" width="270" alt="The app, with the island previewed and the system-wide switch on"> <img src="screenshots/over-music.jpg" width="270" alt="The island floating over another app"> <img src="screenshots/over-notification.jpg" width="270" alt="A real notification in the island">

## System-wide, on and off

The switch in the app is the whole story:

- **Off** — the island lives inside this app only. That is the preview, where you can poke at every
  state and tune the size and the glass.
- **On** — a foreground service puts the island in a `TYPE_APPLICATION_OVERLAY` window above
  everything else. Press home, open a game, read your mail: it stays.
- Turning it off tears the window down immediately. No background process is left behind.

The preview does not disappear when you switch it on. It stays exactly where it was, showing the same
state and the same size, so the sliders always have something to act on — and whatever you change
applies to both. While this app is on screen the floating window detaches itself, so you never see two
islands stacked on each other and the overlay never eats a touch meant for the app underneath. The
moment you leave, the floating one takes over, and any state it moved to (a notification arriving, a
tap on the island) is mirrored back into the preview when you return.

Android will not let any app do this without permission, so the first time you switch it on the app
sends you to **Display over other apps** and comes back once you have granted it.

**Optional but recommended: notification access.** With it, real notifications show up in the island —
app, sender, message — for seven seconds, then it collapses back to the pill. A ringing call gets the
incoming-call view instead, with the same green and red buttons as the demo, wired to the answer and
decline actions of whichever phone app you use. Without it the island
still works; it just has nothing to report. Nothing leaves your device: there is no network code in
this app at all.

## What it does

The island is a spring simulation, not a CSS transition. Width, height, corner radius and scale each
run their own damped spring, so a morph squashes, overshoots and settles instead of easing in a
straight line. The **Bounce** slider changes the damping ratio of those springs live.

States: idle, incoming call, outgoing call, a live call with a running timer, now playing, and a
notification. Tap the island to open or collapse it, tap the wallpaper to collapse it, or drive it
from the sheet at the bottom — which drives the floating island too when it is on.

- Real glass in the app (`backdrop-filter` blur + saturation over the wallpaper, with an inset
  specular highlight). Over other apps the island is a solid near-black pill, because Android gives
  no app the ability to blur another app's pixels — pretending otherwise would be a lie.
- Controls that stay out of the way — the sheet collapses to a grabber for a full-screen island
- Opacity, blur, corner, width, height and bounce are adjustable and remembered between launches
- Haptics on every state change, a working hardware back button, edge-to-edge layout with the real
  status-bar inset
- Dark and light themes, and full `prefers-reduced-motion` support

## Install

Download `DynamicIsland-1.7.0.apk` and open it. Android will ask you to allow installs from your
browser or file manager — normal for anything that is not from the Play Store. The APK is signed
(v2 + v3) and targets Android 14 (API 34), minimum Android 7.0 (API 24).

| Permission | Why |
| --- | --- |
| Display over other apps | the floating island itself |
| Notification access | optional: mirrors notifications, gives the incoming-call view its green and red buttons, and lets the island read and control the playing song |
| Post notifications | the foreground-service notice that Android requires while the overlay runs |
| Vibrate | haptics |

Any earlier version installs straight over the top — same signing key.

## Bugs fixed

The original mockup looked right in a screenshot but misbehaved when you used it. Everything below was
reproduced, fixed and covered by `tools/test_app.py` (96 checks, all passing).

### 1.7.4 — optimisation slot 7

1. **The app stopped waking every 30 seconds to draw a battery level it no longer has.** When the fake
   status bar was removed in 1.3.0 its battery readout went with it, but the timer that fed it stayed:
   every 30 s, for ever, the page crossed into Java (`Native.battery()`, which registers a sticky
   broadcast receiver to read the level), then wrote that number into `#batFill` — a node that has not
   existed since the fake bar was deleted, so every one of those wakeups was guaranteed to change
   nothing on screen. The dead poll, and the bridge method behind it, are gone. The suite asserts that a
   fresh page never calls `Native.battery` and never schedules a repeating timer of five seconds or more;
   the clock's once-a-minute timer is unaffected.

### 1.7.3 — optimisation slot 6

1. **A state the island is already in no longer rebuilds the island.** Every `setState` tore the view
   down, waited 110 ms and built it again from scratch — so pressing *Expand* during a call wiped the
   call view and restarted the call timer at `00:00`, tapping the activity chip you were already on
   blinked the island and pushed the same state into the floating window again, and the always-on
   overlay window paid a fade, a DOM rebuild and a re-raster for a screen it was already showing. The
   state is now only re-entered when it actually changes; the paths that carry a new payload (a
   different caller, a different notification) say so explicitly and still redraw. Nothing on screen
   changed — the suite asserts that Expand during a call keeps the same timer node and a rising count,
   that a repeat chip tap sends no state to the overlay, and that a repeated state leaves the overlay's
   nodes and size untouched.

### 1.7.2 — optimisation slot 5

1. **The wallpaper clock wakes once a minute, not sixty times.** It only shows hours and minutes, so
   59 of every 60 wakeups redrew exactly the same pixels — and each one also reformatted the date
   string through `toLocaleDateString` for a value that changes at midnight. It now sets one timer for
   the next minute boundary, and refreshes immediately on `visibilitychange` and `focus` so a clock
   that was frozen while the app sat in the background is never up to a minute stale when you come
   back. Nothing on screen moved: the suite asserts the same time, the same date, and that the page
   builds at most two `Date`s in four and a half seconds instead of eight.

### 1.7.1 — optimisation slot 1

1. **The player is only pushed into the island when it changed.** The service reads the media session
   every 1.5 s while something plays and used to re-send the same title, artist and play state to the
   overlay on every one of those ticks — and the overlay rebuilt its play icon from scratch each time,
   costing a style recalculation and a re-raster of the floating window every second and a half, for
   ever. It now remembers what it last sent and stays quiet unless the track, the artist, the play
   state, or the island's own view actually changed.

### 1.7.0 — the first optimisation pass

Ten changes, all under the hood. Nothing looks different.

1. **Spring damping is precomputed.** It only changes when the bounce slider moves, so `2·ζ·√k` is
   calculated once per change instead of once per spring per frame — four square roots per frame, gone.
2. **The render loop only writes styles that changed.** Transform and opacity are constant through a
   morph, so two of the five writes per frame are skipped.
3. **A real rendering bug, found by the test suite:** the stage used `overflow: hidden`, which still
   allows a container to be scrolled. When the island sat near an edge the stage could scroll by a few
   pixels and drag the island off-centre — intermittently, which is exactly how it hid for so long.
   `overflow: clip` removes the scroll container entirely.
4. **The clock wakes on the second**, not on a drifting 1000 ms interval, and skips the DOM write when
   the minute has not changed.
5. **Slider input is coalesced to one update per frame** instead of one per `input` event, so dragging
   a slider no longer queues dozens of layout passes.
6. **The island is repositioned when a morph settles**, so the offsets are always computed against the
   final width rather than a mid-animation one.
7. **Media polling adapts:** every 1.5 s while something is playing, every 6 s when idle, and it stops
   completely while the screen is off.
8. **The service caches display density** instead of asking the resources for it on every conversion.
9. **`measureDrift` reuses one buffer** instead of allocating an `int[2]` on each call.
10. **`tools/env.sh`** now bootstraps a JDK and the Android SDK, so a fresh machine (or a scheduled run
    in a clean sandbox) can build the APK with one `source`.

### 1.6.0 — the preview and the floating island now agree

11. **The floating island sat lower than the preview.** The app drew it at `y = 0` for 0% vertical
   while the overlay window added the status-bar height on top, so the same setting produced two
   different positions. Both are `y = 0` now.
12. **MIUI (and friends) quietly push overlay windows down.** The window now measures where the system
   actually put it with `getLocationOnScreen`, compares that with what it asked for, and subtracts the
   difference — up to three times, then it stops. That absorbs the OEM inset without you having to
   fight the slider.
13. **MIUI's own "Dynamic Island is displaying over other apps" notice hijacked the island.** The
   notification listener now drops persistent system notices: a blocklist for system UI, security
   centre and permission-controller packages, plus a rule that a quiet, ongoing notification which is
   not a call, transport, message, alarm or reminder is not worth showing. Your own notifications and
   real calls and songs are untouched.

### 1.5.0 — higher, on the lock screen, and it runs your music

14. **Position reaches the absolute top.** Vertical 0% is now y = 0 — the island can sit over the
   status bar, not just under it — and the whole range is live in both the preview and the floating
   window.
15. **It shows on the lock screen.** The overlay window carries `FLAG_SHOW_WHEN_LOCKED`, with a
   "Show on lock screen" switch in the Position card so you can turn it off. Honest caveat: whether an
   overlay may join the keyguard is up to the OEM, so on some phones the lock screen still wins.
16. **Real music, not a demo.** With notification access the app reads the active `MediaSession` — the
   same mechanism the system's own media controls use — and puts the playing song's title and artist in
   the island with previous / play-pause / next. Those three buttons drive the actual player through
   `TransportControls`, so pause really pauses and next really skips. When the player goes away the
   island collapses. The demo still works when nothing is playing.
17. **Bouncier morph.** Default bounce is up to 72%, and every state change now gets a velocity kick in
   the direction of travel, so a big jump overshoots more than a small one instead of every morph
   feeling the same.
18. Fixed on the way: the play/pause button's `aria-label` did not follow its icon after a tap.

### 1.4.0 — put it anywhere, and answer real calls from it

19. **Position is yours now.** Two sliders — horizontal and vertical, 0–100% — place the island
   anywhere on the screen. They drive the preview *and* the floating window from the same numbers, so
   what you set is what you get out there, and the choice is remembered. 50% / 0% is centred at the
   very top.
20. **A real incoming call now gets the demo's buttons.** The notification listener recognises
   `CATEGORY_CALL` notifications and switches the island to the incoming-call view — the same green
   accept and red decline circles as the demo, same phone glyph, no text labels — with the caller's
   name and line from the notification. The two buttons fire the dialer's *own* answer and decline
   actions, taken straight out of that notification, so it works with whichever phone app you use and
   needs no extra permission beyond notification access. When the call notification goes away the
   island collapses on its own.

### 1.3.0 — it actually runs over other apps now, at the top

21. **The overlay never stayed on screen.** The hand-off between the app and the floating window was
   inverted: `onPause` — which fires the moment you leave the app — *detached* the window, and
   `onResume` attached it. So switching it on and pressing home made the island vanish, which is
   exactly when it should have appeared. The two calls are now one method with an unambiguous name,
   `setHostInForeground(boolean)`, and the service also checks a `VISIBLE` flag when it starts so the
   window never flashes over the app you just turned it on from.
22. **The island sat 40dp down the screen.** The app was drawing its own fake status bar underneath the
   real Android one — two clocks, two battery icons — and parked the island below that. The fake bar is
   gone and the island now hugs the top edge, at the status-bar inset + 2dp. The overlay window does
   the same: `y = statusBarHeight + 2dp` with the island at 0 inside it.
23. **The overlay window could keep its default size.** `resize` bailed out whenever the view was
   detached, so a window that started while the app was in front never picked up the island's real
   size. The size is now always kept current and only the `updateViewLayout` call is gated.
24. **Failures were silent.** If the window could not be added — permission revoked mid-flight, an OEM
   blocking overlays, a bad token — the service just stopped and the app showed "On" over nothing. The
   reason is now carried back into the app and printed under the switch.

### 1.2.0 — the settings that vanished, and a bigger island

25. **The size controls could disappear.** The sheet is a flex column, and flex children shrink by
   default. Once the content was taller than the sheet, the tallest card — the one holding width,
   height, corner, opacity, blur and bounce — was squeezed to a 2px sliver instead of the sheet
   scrolling. Everything else looked fine, which is what made it so confusing. Fixed with
   `flex: 0 0 auto` on the sheet's children, and there is now a test that asserts the controls keep
   their height on a 640px-tall screen and are still reachable by scrolling.
26. **The island was too small.** Base geometry up about 16% (idle 112×32 → 130×38, now playing
   276×112 → 318×128), type up a notch, controls up from 38 to 42dp, and the width/height sliders now
   reach 60–125% and 70–150% so you can go bigger still.
27. **The preview used to vanish when you switched the overlay on**, leaving you tuning something you
   could not see. It stays now, and the floating window detaches itself while the app is in front —
   detached rather than hidden, because a hidden overlay window still swallows touches.
28. **The overlay could be stranded mid-morph** when frames were throttled, and it would then report a
   stale size to the native window, clipping the island. It has the same 1.5s settle watchdog the app
   has had since 1.0.0.
29. **The wallpaper clock could sit under a tall island.** It is now measured against the space it
   actually has, so it shrinks instead of sliding under the island.

### 1.1.0 — going system-wide

30. The island is a real overlay window now, not a page inside the app. The window is sized to exactly
   the island's current box and grown *before* each morph, so nothing is ever clipped mid-animation
   and the overlay never swallows touches it does not need.
31. The overlay island had no `box-sizing: border-box`, so its 1px border made it render 2px wider than
   the size it reported to the native window — which then clipped the border. Caught by the geometry
   assertions, fixed at the source.
32. The switch used to mean "is the preview drawn". It now means "is the island running over other
   apps", and it is the single source of truth: the label, the accessibility state, the preview, the
   service and `localStorage` are all driven from one function instead of five places drifting apart.
33. Permission was assumed rather than checked. Toggling without it silently did nothing; now it opens
   the right settings screen, stays off, and explains why.
34. The service could be left running with the switch showing "Off" after a reboot or a low-memory
   kill. The app re-syncs on resume and restarts the service if the switch is on.

### 1.0.0 — the original seventeen

**Things that visibly broke**

35. The activity chips declared `font: 500 14px inherit` — not a legal shorthand, so the entire
   declaration was thrown away and every chip rendered at the browser default 13.3px/400 instead of
   14px/500. Replaced with explicit `font-family`/`font-size`/`font-weight`.
36. Tapping the island after closing a live call reopened an *incoming call* rather than the call you
   were on: the "remember last state" line mapped `ongoing` to `incoming`. It now stores the real
   previous state.
37. Switching away from **Call someone** within 3.6 seconds could still drop you into a live call. The
   auto-promote `setTimeout` shared a variable with the call-duration `setInterval` and was cancelled
   with `clearInterval`, which is not a reliable way to cancel a timeout. Every timer now has its own
   handle plus a state guard.
38. Two quick state changes could leave the island **empty and invisible**: `clearTimeout` cancelled the
   pending "fade the contents back in", stranding the `.out` class. Swaps are token-guarded now and the
   visible state is always restored.
39. Turning the island off mid-call left the duration interval and the promote timer running forever,
    and left `pointer-events` / `aria-hidden` out of sync with the switch.
40. Play/pause wrote to `content.firstChild` and next/previous searched the island for the first `.t1` —
    both silently target the wrong node after a re-render. Every lookup is scoped to the current view.
41. The huge wallpaper clock used to bleed through the island text. The clock is now centred in the
    space *below* the island, and the default island opacity went from 44% to 75%.
42. White text on the light-blue "active" chip was about 2.2:1 contrast — barely readable. It is dark
    ink on the accent now, around 7:1.

**Things that broke under the hood**

43. The corner-radius target could exceed half the height; the render loop clamped it silently, so the
    morph snapped at the very end. The target is clamped before it reaches the spring.
44. All motion was driven by `requestAnimationFrame` alone. In a backgrounded tab that pauses, leaving
    the island stranded mid-morph and the contents never faded in. Contents now fade on a timer, and a
    1.5 s watchdog snaps any spring that has not finished.
45. The clock and date were hardcoded strings ("9:41", "Friday, October 30"). They are live now.
46. `prefers-reduced-motion` only stopped the wallpaper orbs; the waveform, equaliser and pulse ring
    kept animating. All of it stops now.
47. Settings reset on every reload — they persist in `localStorage` now.
48. The accordion measured `offsetHeight` on every frame and animated `height` in pixels, which broke
    after a rotation or a font-size change. It is a pure-CSS `max-height` transition now.
49. The island carried `role="button"` while containing real buttons — nested interactive elements,
    which screen readers announce badly. The container is a `role="group"`; the controls keep their own
    roles, labels and `aria-pressed` state, and state changes are announced in a live region.
50. No `theme-color`, no safe-area handling for the notch or the gesture bar, no `touch-action`, so taps
    were delayed ~300 ms on some devices.

## Build the APK yourself

No Gradle. `build.sh` drives `aapt2`, `javac`, `d8`, `zipalign` and `apksigner` directly, which keeps
the build to a few seconds and the repo to a few hundred KB.

```bash
# needs JDK 17+ and Android SDK build-tools 34 + platform android-34
export ANDROID_HOME="$HOME/Android/Sdk"
./app/build.sh
# -> app/dist/DynamicIsland-1.7.0.apk
```

`build.sh` copies `app/index.html` and `app/overlay.html` into the Android assets folder itself, so the
web app has exactly one source of truth. GitHub Actions runs the same script on every push
(`.github/workflows/build.yml`) and uploads the APK as an artifact.

## Run the web version

Open `app/index.html` in any browser — no bundler, no dependencies, no `npm install`. The system-wide
switch needs the Android shell, so in a browser it stays off; everything else works. `app/overlay.html`
is the floating island on its own and can be opened directly to see what the overlay looks like.

## Tests

```bash
pip install playwright && playwright install chromium
python tools/test_app.py
```

96 checks against a real browser: geometry per state, the island at the absolute top, the position
sliders moving it to every edge, the lock-screen switch, content visibility, timer ticking,
mute/pause/next, the system-wide switch (permission handling, service start/stop, the preview staying
put, chips and sliders reaching the overlay, state mirroring in both directions), accordion, sheet,
back-button order, persistence, a rapid state-thrash test, the size controls surviving a 640px-tall
screen, a broken overlay being reported instead of swallowed, and the overlay page itself — transparent
body, size reporting, max-width handling, notification arrival and auto-dismiss, tap-to-collapse, a real
call arriving with exactly one green and one red unlabelled button that fire the right action, and a real
song whose pause, next and previous reach the player, and repeated reports of an unchanged song
leaving the island's DOM untouched.

## Project layout

```
app/index.html                         the control room: preview, switch, settings
app/overlay.html                       the floating island, rendered in the overlay window
app/android/AndroidManifest.xml        one activity, one foreground service, one listener
app/android/src/.../MainActivity.java  WebView shell: insets, battery, haptics, back, permissions
app/android/src/.../IslandService.java the overlay window: sizing, state, notification channel
app/android/src/.../NotifListener.java optional notification mirroring
app/android/res/                       theme, gradient background, launcher icon, status icon
app/build.sh                           the whole build pipeline
keystore/                              signing key, base64 encoded (see below)
tools/test_app.py                      Playwright run against both pages
dist/                                  prebuilt signed APK
```

## About the signing key

`keystore/dynamic-island.jks.base64` is the throwaway key the released APK is signed with, published
on purpose so that future releases can be installed as updates over this one (Android refuses an update
signed with a different key). It is not a secret and it protects nothing. `build.sh` decodes it if
`keystore/dynamic-island.jks` is missing, and generates a fresh key if that is missing too.

```bash
base64 -d keystore/dynamic-island.jks.base64 > keystore/dynamic-island.jks
# storepass / keypass: dynamicisland   alias: dynamicisland
```

If you fork this and publish your own build, generate your own key — do not sign with this one.

## License

MIT. Do what you like with it.

---

## ⭐ Like this work? Give it a star

If you like this app and our work, please **star this repository** ⭐ and **[follow technicalnihilist-lgtm on GitHub](https://github.com/technicalnihilist-lgtm)**. If our work isn't for you, that's completely fine — the choice is yours. Thank you for stopping by!

<details>
<summary><b>🌍 Same message in 32 languages (A–Z + Indian languages)</b></summary>

- **A — Arabic** (العربية): ⭐ إذا أعجبك هذا التطبيق وعملنا، فيرجى منح المستودع نجمة ومتابعتنا. وإذا لم يعجبك عملنا، فلا مشكلة على الإطلاق — القرار قرارك. شكرًا لزيارتك!
- **B — Bengali** (বাংলা): ⭐ যদি আপনার এই অ্যাপ এবং আমাদের কাজ ভালো লাগে, তবে অনুগ্রহ করে রিপোজিটরিটিকে একটি স্টার দিন এবং আমাদের ফলো করুন। আমাদের কাজ যদি আপনার পছন্দ না হয়, তাতেও কোনো সমস্যা নেই — সিদ্ধান্ত আপনার। আমাদের পেজে আসার জন্য ধন্যবাদ!
- **C — Chinese** (中文): ⭐ 如果你喜欢这个应用和我们的作品，请给仓库点个星标并关注我们。如果我们的作品不适合你，也完全没关系——选择权在你。感谢你的到访！
- **D — Dutch** (Nederlands): ⭐ Vind je deze app en ons werk leuk? Geef de repository dan een ster en volg ons. Vind je ons werk niets, dan is dat helemaal prima — de keuze is aan jou. Bedankt voor je bezoek!
- **E — English** (English): ⭐ If you like this app and our work, please give the repository a star and follow us. If our work isn't for you, that's completely fine — the choice is yours. Thank you for stopping by!
- **F — French** (Français): ⭐ Si cette application et notre travail vous plaisent, mettez une étoile au dépôt et suivez-nous. Si notre travail n'est pas pour vous, aucun souci — c'est votre choix. Merci de votre visite !
- **G — German** (Deutsch): ⭐ Wenn dir diese App und unsere Arbeit gefallen, gib dem Repository einen Stern und folge uns. Wenn unsere Arbeit nichts für dich ist, ist das völlig in Ordnung — die Wahl liegt bei dir. Danke fürs Vorbeischauen!
- **H — Hindi** (हिन्दी): ⭐ अगर आपको यह ऐप और हमारा काम पसंद है, तो कृपया रिपॉजिटरी को स्टार दें और हमें फॉलो करें। अगर हमारा काम आपके लिए नहीं है, तो भी कोई बात नहीं — यह पूरी तरह आपकी मर्ज़ी है। यहाँ आने के लिए आपका धन्यवाद!
- **I — Indonesian** (Bahasa Indonesia): ⭐ Jika kamu suka aplikasi ini dan karya kami, beri bintang pada repositori ini dan ikuti kami. Kalau karya kami bukan untukmu, tidak masalah sama sekali — itu pilihanmu. Terima kasih sudah mampir!
- **J — Japanese** (日本語): ⭐ このアプリと私たちの仕事が気に入ったら、リポジトリにスターを付けてフォローしてください。合わない場合はまったく問題ありません — 選ぶのはあなたです。お越しいただきありがとうございます！
- **K — Korean** (한국어): ⭐ 이 앱과 저희 작업이 마음에 드신다면 저장소에 스타를 눌러 주시고 팔로우해 주세요. 저희 작업이 맞지 않으셔도 전혀 괜찮습니다 — 선택은 여러분의 몫입니다. 방문해 주셔서 감사합니다!
- **L — Lithuanian** (Lietuvių): ⭐ Jei tau patinka ši programa ir mūsų darbas, duok saugyklai žvaigždutę ir sek mus. Jei mūsų darbas ne tau, viskas gerai — pasirinkimas tavo. Ačiū, kad užsukai!
- **M — Malayalam** (മലയാളം): ⭐ നിങ്ങൾക്ക് ഈ ആപ്പും ഞങ്ങളുടെ പ്രവർത്തനവും ഇഷ്ടപ്പെട്ടെങ്കിൽ, ദയവായി റെപ്പോസിറ്ററിക്ക് ഒരു സ്റ്റാർ നൽകുകയും ഞങ്ങളെ ഫോളോ ചെയ്യുകയും ചെയ്യുക. ഞങ്ങളുടെ പ്രവർത്തനം നിങ്ങൾക്ക് അനുയോജ്യമല്ലെങ്കിൽ, അതും തികച്ചും കുഴപ്പമില്ല — തീരുമാനം നിങ്ങളുടേതാണ്. ഇവിടെ വന്നതിന് നന്ദി!
- **N — Nepali** (नेपाली): ⭐ यदि तपाईंलाई यो एप र हाम्रो काम मन पर्‍यो भने, कृपया रिपोजिटरीलाई स्टार दिनुहोस् र हामीलाई फलो गर्नुहोस्। यदि हाम्रो काम तपाईंलाई मन पर्दैन भने, पनि ठीकै छ — यो तपाईंको इच्छा हो। यहाँ आउनुभएकोमा धन्यवाद!
- **O — Odia** (ଓଡ଼ିଆ): ⭐ ଯଦି ଆପଣଙ୍କୁ ଏହି ଆପ୍ ଏବଂ ଆମର କାମ ଭଲ ଲାଗୁଛି, ତେବେ ଦୟାକରି ରିପୋଜିଟୋରୀକୁ ଗୋଟିଏ ଷ୍ଟାର୍ ଦିଅନ୍ତୁ ଏବଂ ଆମକୁ ଫଲୋ କରନ୍ତୁ। ଯଦି ଆମର କାମ ଆପଣଙ୍କ ପାଇଁ ନୁହେଁ, ତେବେ କିଛି ଅସୁବିଧା ନାହିଁ — ପସନ୍ଦ ଆପଣଙ୍କର। ଆମ ପାଖକୁ ଆସିଥିବାରୁ ଧନ୍ୟବାଦ!
- **P — Polish** (Polski): ⭐ Jeśli podoba Ci się ta aplikacja i nasza praca, daj repozytorium gwiazdkę i obserwuj nas. Jeśli nasza praca nie jest dla Ciebie, to zupełnie w porządku — wybór należy do Ciebie. Dziękujemy za odwiedziny!
- **Q — Quechua** (Runa Simi): ⭐ Kay app, ñuqaykup ruwasqanchikpas gustasunki chayqa, repositorioman huk estrella churay, ñuqaykutapas qatipayku. Mana gustasunki chayqa, allinmi — qampa akllayki. Hamusqaykimanta sulpayki!
- **R — Russian** (Русский): ⭐ Если вам нравится это приложение и наша работа, поставьте звёздочку репозиторию и подпишитесь на нас. Если наша работа не для вас — это совершенно нормально, выбор за вами. Спасибо, что заглянули!
- **S — Spanish** (Español): ⭐ Si te gusta esta app y nuestro trabajo, dale una estrella al repositorio y síguenos. Si nuestro trabajo no es para ti, no pasa nada — la decisión es tuya. ¡Gracias por pasarte!
- **T — Tamil** (தமிழ்): ⭐ உங்களுக்கு இந்த ஆப்பும் எங்க வேலையும் பிடிச்சிருந்தா, தயவுசெஞ்சு இந்த ரெபாசிட்டரிக்கு ஒரு ஸ்டார் குடுத்து, எங்களை ஃபாலோ பண்ணுங்க. எங்க வேலை உங்களுக்கு செட் ஆகலைன்னாலும் பரவாயில்லை — அது உங்க விருப்பம். இங்கே வந்ததுக்கு நன்றி!
- **U — Urdu** (اردو): ⭐ اگر آپ کو یہ ایپ اور ہمارا کام پسند آئے تو براہ کرم ریپازٹری کو سٹار دیں اور ہمیں فالو کریں۔ اگر ہمارا کام آپ کے لیے نہیں ہے، تو یہ بالکل ٹھیک ہے — انتخاب آپ کا ہے۔ یہاں تشریف لانے کا شکریہ!
- **V — Vietnamese** (Tiếng Việt): ⭐ Nếu bạn thích ứng dụng này và công việc của chúng tôi, hãy tặng kho lưu trữ một ngôi sao và theo dõi chúng tôi. Nếu công việc của chúng tôi không phù hợp với bạn, điều đó hoàn toàn ổn — lựa chọn là của bạn. Cảm ơn bạn đã ghé qua!
- **W — Welsh** (Cymraeg): ⭐ Os ydych chi'n hoffi'r ap hwn a'n gwaith, rhowch seren i'r storfa a dilynwch ni. Os nad yw ein gwaith ar eich cyfer, mae hynny'n hollol iawn — chi sydd i benderfynu. Diolch am alw heibio!
- **X — Xhosa** (isiXhosa): ⭐ Ukuba uyayithanda le app nomsebenzi wethu, nika irepo inkwenkwezi kwaye usilandele. Ukuba umsebenzi wethu awukufanelanga, akukho ngxaki — lukhetho lwakho. Enkosi ngokutyelela!
- **Y — Yoruba** (Yorùbá): ⭐ Bí app yìí àti iṣẹ́ wa bá wù ọ́, jọ̀wọ́ fún àkójọpọ̀ náà ní ìràwọ̀ kí o sì tẹ̀lé wa. Bí iṣẹ́ wa kò bá yẹ ọ́, kò séwu — ìwọ ni ó yàn. Ẹ ṣé fún wíwá!
- **Z — Zulu** (isiZulu): ⭐ Uma uthanda le app nomsebenzi wethu, nikeza isitoreji inkanyezi bese usilandela. Uma umsebenzi wethu ungakufanele, akunankinga — wukukhetha kwakho. Siyabonga ngokuvakasha!

**More Indian languages**

- **Assamese** (অসমীয়া): ⭐ যদি আপুনি এই এপটো আৰু আমাৰ কাম ভাল পায়, তেন্তে অনুগ্ৰহ কৰি ৰিপজিটৰীটোক এটা ষ্টাৰ দিয়ক আৰু আমাক ফ'ল' কৰক। যদি আমাৰ কাম আপোনাৰ বাবে নহয়, তেন্তে সেয়া একেবাৰে ঠিক আছে — সিদ্ধান্তটো আপোনাৰ। আমাৰ ইয়ালৈ অহাৰ বাবে ধন্যবাদ!
- **Gujarati** (ગુજરાતી): ⭐ જો તમને આ એપ અને અમારું કામ ગમતું હોય, તો પ્લીઝ રિપોઝિટરીને સ્ટાર આપો અને અમને ફોલો કરો. જો અમારું કામ તમને ન ગમતું હોય, તો તે પણ બરાબર છે — પસંદગી તમારી છે. અહીં આવવા બદલ આભાર!
- **Kannada** (ಕನ್ನಡ): ⭐ ನಿಮಗೆ ಈ ಆ್ಯಪ್ ಮತ್ತು ನಮ್ಮ ಕೆಲಸ ಇಷ್ಟವಾದರೆ, ದಯವಿಟ್ಟು ರೆಪೊಸಿಟರಿಗೆ ಸ್ಟಾರ್ ಕೊಡಿ ಮತ್ತು ನಮ್ಮನ್ನು ಫಾಲೋ ಮಾಡಿ. ನಮ್ಮ ಕೆಲಸ ನಿಮಗೆ ಸರಿಹೊಂದದಿದ್ದರೆ, ಅದೂ ಪರವಾಗಿಲ್ಲ — ಆಯ್ಕೆ ನಿಮ್ಮದು. ಭೇಟಿ ನೀಡಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದಗಳು!
- **Marathi** (मराठी): ⭐ जर तुम्हाला हे ॲप आणि आमचं काम आवडलं असेल, तर कृपया रिपॉझिटरीला स्टार द्या आणि आम्हाला फॉलो करा. जर आमचं काम तुम्हाला आवडत नसेल, तर काही हरकत नाही — ती तुमची निवड आहे. इथे आल्याबद्दल धन्यवाद!
- **Punjabi** (ਪੰਜਾਬੀ): ⭐ ਜੇ ਤੁਹਾਨੂੰ ਇਹ ਐਪ ਅਤੇ ਸਾਡਾ ਕੰਮ ਪਸੰਦ ਹੈ, ਤਾਂ ਕਿਰਪਾ ਕਰਕੇ ਰਿਪੋਜ਼ਟਰੀ ਨੂੰ ਸਟਾਰ ਦਿਓ ਅਤੇ ਸਾਨੂੰ ਫਾਲੋ ਕਰੋ। ਜੇ ਸਾਡਾ ਕੰਮ ਤੁਹਾਡੇ ਲਈ ਨਹੀਂ ਹੈ, ਤਾਂ ਕੋਈ ਗੱਲ ਨਹੀਂ — ਚੋਣ ਤੁਹਾਡੀ ਹੈ। ਸਾਡੇ ਪੇਜ 'ਤੇ ਆਉਣ ਲਈ ਧੰਨਵਾਦ!
- **Telugu** (తెలుగు): ⭐ మీకు ఈ యాప్, మా పని నచ్చితే, దయచేసి రిపోజిటరీకి ఒక స్టార్ ఇచ్చి మమ్మల్ని ఫాలో అవ్వండి. ఒకవేళ మా పని మీకు నచ్చకపోతే, పర్వాలేదు — అది మీ ఇష్టం. మమ్మల్ని సందర్శించినందుకు ధన్యవాదాలు!

</details>
