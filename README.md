# Dynamic Island · Liquid Glass

A Dynamic Island that actually lives on your screen. Flip the switch and it floats above every app
until you flip it back; flip it off and it is gone. It started as a single HTML mockup — this repo is
that mockup with its bugs fixed, rebuilt as a real Android app with a real system overlay, and shipped
as a signed APK.

**[⬇ Download the APK](https://github.com/technicalnihilist-lgtm/dynamic-island/releases/latest)** ·
Android 7.0+ · 100 KB · no internet permission

<img src="screenshots/over-music.jpg" width="270" alt="The island floating over another app"> <img src="screenshots/over-notification.jpg" width="270" alt="A real notification in the island"> <img src="screenshots/app-sysmode.jpg" width="270" alt="The switch that turns it on">

## System-wide, on and off

The switch in the app is the whole story:

- **Off** — the island lives inside this app only. That is the preview, where you can poke at every
  state and tune the glass.
- **On** — a foreground service puts the island in a `TYPE_APPLICATION_OVERLAY` window above
  everything else. Press home, open a game, read your mail: it stays. The in-app preview steps aside
  so you never see two islands at once.
- Turning it off tears the window down immediately. No background process is left behind.

Android will not let any app do this without permission, so the first time you switch it on the app
sends you to **Display over other apps** and comes back once you have granted it.

**Optional but recommended: notification access.** With it, real notifications show up in the island —
app, sender, message — for seven seconds, then it collapses back to the pill. Without it the island
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
  status-bar inset, and the real battery level in the status line
- Dark and light themes, and full `prefers-reduced-motion` support

## Install

Download `DynamicIsland-1.1.0.apk` and open it. Android will ask you to allow installs from your
browser or file manager — normal for anything that is not from the Play Store. The APK is signed
(v2 + v3) and targets Android 14 (API 34), minimum Android 7.0 (API 24).

| Permission | Why |
| --- | --- |
| Display over other apps | the floating island itself |
| Notification access | optional, to mirror notifications into it |
| Post notifications | the foreground-service notice that Android requires while the overlay runs |
| Vibrate | haptics |

1.0.0 users can install 1.1.0 straight over the top — same signing key.

## Bugs fixed

The original mockup looked right in a screenshot but misbehaved when you used it. Everything below was
reproduced, fixed and covered by `tools/test_app.py` (42 checks, all passing).

### 1.1.0 — going system-wide

1. The island is a real overlay window now, not a page inside the app. The window is sized to exactly
   the island's current box and grown *before* each morph, so nothing is ever clipped mid-animation
   and the overlay never swallows touches it does not need.
2. The overlay island had no `box-sizing: border-box`, so its 1px border made it render 2px wider than
   the size it reported to the native window — which then clipped the border. Caught by the geometry
   assertions, fixed at the source.
3. The switch used to mean "is the preview drawn". It now means "is the island running over other
   apps", and it is the single source of truth: the label, the accessibility state, the preview, the
   service and `localStorage` are all driven from one function instead of five places drifting apart.
4. Permission was assumed rather than checked. Toggling without it silently did nothing; now it opens
   the right settings screen, stays off, and explains why.
5. The service could be left running with the switch showing "Off" after a reboot or a low-memory
   kill. The app re-syncs on resume and restarts the service if the switch is on.

### 1.0.0 — the original seventeen

**Things that visibly broke**

6. The activity chips declared `font: 500 14px inherit` — not a legal shorthand, so the entire
   declaration was thrown away and every chip rendered at the browser default 13.3px/400 instead of
   14px/500. Replaced with explicit `font-family`/`font-size`/`font-weight`.
7. Tapping the island after closing a live call reopened an *incoming call* rather than the call you
   were on: the "remember last state" line mapped `ongoing` to `incoming`. It now stores the real
   previous state.
8. Switching away from **Call someone** within 3.6 seconds could still drop you into a live call. The
   auto-promote `setTimeout` shared a variable with the call-duration `setInterval` and was cancelled
   with `clearInterval`, which is not a reliable way to cancel a timeout. Every timer now has its own
   handle plus a state guard.
9. Two quick state changes could leave the island **empty and invisible**: `clearTimeout` cancelled the
   pending "fade the contents back in", stranding the `.out` class. Swaps are token-guarded now and the
   visible state is always restored.
10. Turning the island off mid-call left the duration interval and the promote timer running forever,
    and left `pointer-events` / `aria-hidden` out of sync with the switch.
11. Play/pause wrote to `content.firstChild` and next/previous searched the island for the first `.t1` —
    both silently target the wrong node after a re-render. Every lookup is scoped to the current view.
12. The huge wallpaper clock used to bleed through the island text. The clock is now centred in the
    space *below* the island, and the default island opacity went from 44% to 75%.
13. White text on the light-blue "active" chip was about 2.2:1 contrast — barely readable. It is dark
    ink on the accent now, around 7:1.

**Things that broke under the hood**

14. The corner-radius target could exceed half the height; the render loop clamped it silently, so the
    morph snapped at the very end. The target is clamped before it reaches the spring.
15. All motion was driven by `requestAnimationFrame` alone. In a backgrounded tab that pauses, leaving
    the island stranded mid-morph and the contents never faded in. Contents now fade on a timer, and a
    1.5 s watchdog snaps any spring that has not finished.
16. The clock and date were hardcoded strings ("9:41", "Friday, October 30"). They are live now.
17. `prefers-reduced-motion` only stopped the wallpaper orbs; the waveform, equaliser and pulse ring
    kept animating. All of it stops now.
18. Settings reset on every reload — they persist in `localStorage` now.
19. The accordion measured `offsetHeight` on every frame and animated `height` in pixels, which broke
    after a rotation or a font-size change. It is a pure-CSS `max-height` transition now.
20. The island carried `role="button"` while containing real buttons — nested interactive elements,
    which screen readers announce badly. The container is a `role="group"`; the controls keep their own
    roles, labels and `aria-pressed` state, and state changes are announced in a live region.
21. No `theme-color`, no safe-area handling for the notch or the gesture bar, no `touch-action`, so taps
    were delayed ~300 ms on some devices.

## Build the APK yourself

No Gradle. `build.sh` drives `aapt2`, `javac`, `d8`, `zipalign` and `apksigner` directly, which keeps
the build to a few seconds and the repo to a few hundred KB.

```bash
# needs JDK 17+ and Android SDK build-tools 34 + platform android-34
export ANDROID_HOME="$HOME/Android/Sdk"
./app/build.sh
# -> app/dist/DynamicIsland-1.1.0.apk
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

42 checks against a real browser: geometry per state, content visibility, timer ticking,
mute/pause/next, the system-wide switch (permission handling, service start/stop, preview stepping
aside, chips and sliders reaching the overlay), accordion, sheet, back-button order, persistence, a
rapid state-thrash test, and the overlay page itself — transparent body, size reporting, notification
arrival and auto-dismiss, and tap-to-collapse.

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
