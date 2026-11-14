package com.hubclue.dynamicisland;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.media.MediaMetadata;
import android.media.session.MediaController;
import android.media.session.MediaSessionManager;
import android.media.session.PlaybackState;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.util.List;

/**
 * Draws the island in a system overlay window so it stays on screen above every
 * other app. Started and stopped by the switch in MainActivity.
 *
 * The island itself is the same spring engine as the in-app preview, rendered in
 * a transparent, non-focusable WebView window that is resized to exactly fit the
 * current island so it never steals touches it does not need.
 */
public class IslandService extends Service {

    public static final String ACTION_START = "com.hubclue.dynamicisland.START";
    public static final String ACTION_STOP = "com.hubclue.dynamicisland.STOP";

    /** breathing room under the island inside its window; the island itself sits at the very top */
    private static final int PAD_DP = 10;
    private static final int NOTIF_ID = 7;
    private static final String CHANNEL_ID = "island";

    /** how often the player is read while something is playing, and otherwise */
    private static final long FAST_POLL_MS = 1500;
    private static final long LAZY_POLL_MS = 6000;

    public static volatile boolean RUNNING = false;
    /** last state the island was put in, so the app can mirror it on resume */
    public static volatile String currentState = "idle";
    /** last failure, surfaced in the app so a broken overlay is never silent */
    public static volatile String lastError = "";

    private static final String PREFS = "island";
    /* where the island sits, as a percentage of the free space: 50/0 = centred at the top */
    private float posX = 50f, posY = 0f;
    private static float pendingX = 50f, pendingY = 0f;
    private static boolean hasPendingPos = false;

    /* the incoming call's own answer / decline actions, taken from the phone's notification */
    private PendingIntent callAnswer, callDecline, callOpen;
    private String[] pendingCall;
    /* who the live call is from, so the phone re-posting its own notification
       for the same call is not mistaken for a second call */
    private String callName = "";
    /* A call the phone announced is live until it ends, and it owns the island
       for all of that time - not only while the island happens to be drawing
       it. `currentState` is the state on screen, and the island is 318 px of a
       phone screen: tapping it away during a call sets that state to idle,
       which is one of the two states the player is allowed to take. islandFree()
       then said yes, the loop un-parked at the playing cadence and the player
       was pushed at a window the call still owned. This is the fact the loop
       actually wants: the call is running, whatever is drawn. Cleared where a
       call really ends - the phone hung up (clearCall), or End/Decline was
       tapped in the island (Bridge.callEnded, which an answered call sends
       too). */
    private volatile boolean callActive = false;

    /* real media, read straight out of the player's media session */
    /* written on the main thread by applyMedia(), read from the media thread by
       the transport buttons - so it is volatile, or a press could act on a
       controller the poll has already replaced */
    private volatile MediaController media;
    private String mediaPkg = "";
    /* what the island was last told about the player, so an unchanged track is
       not pushed into the WebView again on the next poll */
    private String lastMediaSig = "";
    private boolean showOnLock = true;
    /* some OEM skins (MIUI, One UI) quietly push overlay windows down by the
       status-bar height. We measure the real position once and subtract it. */
    private int driftY = 0;
    private int driftFixes = 0;
    private final int[] locTmp = new int[2];
    private float density = 2f;
    private boolean screenOn = true;
    private long mediaPollDelay = LAZY_POLL_MS;
    /* the media read is binder traffic, so it runs on its own thread and only
       its answer comes back to the main thread. The transport buttons are
       posted to the same thread (see Bridge.media), and that post comes in from
       the JS bridge thread, so the handle is volatile. */
    private HandlerThread mediaThread;
    private volatile Handler mediaIo;
    private boolean mediaBusy = false;
    /* true while the loop is on the lazy cadence only because a call or a
       notification owns the island - the one case Bridge.stateChanged has to
       take a read early for. Written on the main thread, read from the bridge
       thread in stateChanged. */
    private volatile boolean mediaParked = false;
    private volatile boolean mediaStopped = false;
    private static boolean pendingLock = true;
    private static boolean hasPendingLock = false;
    private static IslandService sInstance;
    private boolean attached = false;
    /* the page died on us and had to be rebuilt; a rebuild loop is not a fix */
    private long lastRebuildAt = 0;
    private static final long REBUILD_GAP_MS = 10000L;

    private WindowManager wm;
    private WebView web;
    private WindowManager.LayoutParams lp;
    private final Handler ui = new Handler(Looper.getMainLooper());

    private boolean pageReady = false;
    private String pendingState;
    private String[] pendingNotif;

    // ---------------------------------------------------------------- lifecycle

    @Override
    public void onCreate() {
        super.onCreate();
        sInstance = this;
        wm = (WindowManager) getSystemService(WINDOW_SERVICE);
        density = getResources().getDisplayMetrics().density;
        loadPrefs();
        try {
            mediaThread = new HandlerThread("island-media");
            mediaThread.start();
            mediaIo = new Handler(mediaThread.getLooper());
        } catch (Throwable ignored) {
            /* no thread to be had: the read falls back to the main thread */
            mediaThread = null;
            mediaIo = null;
        }
        try {
            IntentFilter f = new IntentFilter();
            f.addAction(Intent.ACTION_SCREEN_ON);
            f.addAction(Intent.ACTION_SCREEN_OFF);
            registerReceiver(screenRx, f);
        } catch (Throwable ignored) {
        }
        if (hasPendingLock) showOnLock = pendingLock;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopSelf();
            return START_NOT_STICKY;
        }
        try {
            Notification n = buildNotification();
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            } else {
                startForeground(NOTIF_ID, n);
            }
        } catch (Throwable t) {
            // no notification permission, or the system refused the FGS: the
            // overlay is still worth trying, so fall through
            lastError = "fg: " + t.getClass().getSimpleName();
        }
        if (web == null) addOverlay();
        ui.removeCallbacks(mediaTick);
        if (screenOn) ui.postDelayed(mediaTick, 2500);
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        mediaStopped = true;
        ui.removeCallbacks(mediaTick);
        if (mediaThread != null) {
            try {
                mediaThread.quitSafely();
            } catch (Throwable ignored) {
            }
            mediaThread = null;
            mediaIo = null;
        }
        try {
            unregisterReceiver(screenRx);
        } catch (Throwable ignored) {
        }
        removeOverlay();
        RUNNING = false;
        sInstance = null;
        try {
            stopForeground(true);
        } catch (Throwable ignored) {
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    // ------------------------------------------------------------ public hooks

    public static void setState(String state) {
        IslandService s = sInstance;
        if (s != null && state != null) s.applyState(state);
    }

    public static void showNotification(String app, String title, String text) {
        IslandService s = sInstance;
        if (s != null) s.pushNotification(app, title, text);
    }

    /* The look the page last asked for. It is kept here as well as in the page,
       because the page is not always there to keep it: it is built from scratch
       when Android kills its renderer (see overlayFailure), and on a cold start
       it takes a moment to load. applyConfig used to hand the four numbers
       straight to the WebView and return - and it returned early, throwing them
       away, whenever the page had not reported itself ready yet. The page's own
       pushConfig fires 700 ms after the switch goes on, which on a slow phone is
       before the page has finished loading: the floating island then ran at the
       page's defaults - 100% width and height, its own bounce - for the rest of
       the session, while the preview showed the size the user had set, and only
       touching a slider again put the two back together. Every other thing the
       service pushes into that page (the state, a call, a notification) already
       survives a page that is not ready and is replayed the moment it says it
       is; the look was the one that did not. */
    private static float cfgWm = 1f, cfgHm = 1f, cfgRm = 1f, cfgBounce = 0.65f;
    private static boolean hasConfig = false;

    public static void config(float wm_, float hm_, float rm_, float bounce) {
        cfgWm = wm_;
        cfgHm = hm_;
        cfgRm = rm_;
        cfgBounce = bounce;
        hasConfig = true;
        IslandService s = sInstance;
        if (s != null) s.applyConfig();
    }

    /**
     * While the app is in front it draws its own preview, so the floating window
     * is detached. Detaching (rather than hiding) matters: a hidden overlay
     * window would still swallow touches meant for the app underneath.
     */
    public static void setLock(boolean on) {
        pendingLock = on;
        hasPendingLock = true;
        IslandService s = sInstance;
        if (s != null) s.applyLock(on);
    }

    private void applyLock(boolean on) {
        showOnLock = on;
        if (lp == null) return;
        if (on) lp.flags |= WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED;
        else lp.flags &= ~WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED;
        if (attached) {
            try {
                wm.updateViewLayout(web, lp);
            } catch (Throwable ignored) {
            }
        }
    }

    /* ------------------------------------------------------------- media */

    private final Runnable mediaTick = new Runnable() {
        @Override
        public void run() {
            pollMedia();
        }
    };

    /* no point reading media sessions while the screen is off */
    private final BroadcastReceiver screenRx = new BroadcastReceiver() {
        @Override
        public void onReceive(Context ctx, Intent intent) {
            String a = intent == null ? "" : intent.getAction();
            if (Intent.ACTION_SCREEN_OFF.equals(a)) {
                screenOn = false;
                ui.removeCallbacks(mediaTick);
            } else if (Intent.ACTION_SCREEN_ON.equals(a)) {
                screenOn = true;
                ui.removeCallbacks(mediaTick);
                ui.postDelayed(mediaTick, 400);
            }
        }
    };

    /* Reading the phone's media sessions is synchronous binder traffic into
       system_server: getActiveSessions, a getPlaybackState for every session in
       the list, and then a getMetadata and another getPlaybackState for the one
       that was picked. Four to six blocking round trips, every 1.5 s for as long
       as anything is playing - and the whole loop ran on the main thread, the
       one drawing the island's springs. On a phone with a busy system_server
       that is a stutter in the morph, on a timer, once a second and a half.
       The read now happens on its own thread and only its answer comes back to
       the main thread, where every field the service owns is still written in
       one place. Nothing else about the loop changed: the same sessions, the
       same preference for the playing one, the same cadence, the same pushes
       into the page, the same backing off when there is nothing to read. */
    private void pollMedia() {
        /* Nothing on screen to keep up to date. While the app's own screen is
           in front the floating window is detached - applyHostVisible removes
           it from the window manager, because a hidden overlay window would
           swallow touches meant for the app underneath - so the island the
           poll exists to feed is not there. The read still ran, every 1.5 s
           for as long as music was playing: four to six binder round trips
           into system_server plus an eval into a WebView nobody can see, for
           a picture that cannot be seen either. The loop parks on the lazy
           cadence instead of stopping - it is always still running, so no
           detach can wedge it - and applyHostVisible arms it the moment the
           window goes back up, which is the first moment it matters again. */
        if (!attached) {
            mediaPollDelay = LAZY_POLL_MS;
            scheduleMediaPoll();
            return;
        }
        if (!pageReady) {
            scheduleMediaPoll();
            return;
        }
        /* The same argument one state further on. A ringing call, a call in
           progress and a notification own the island until they finish, and
           applyMedia refuses to push the player over them - so for the whole
           length of a call, and for the seven seconds of a notification, the
           answer this loop fetches is thrown away unread. The read still ran
           at the playing cadence all the same: getActiveSessions plus a
           getPlaybackState for every session in it, every 1.5 s, four to six
           binder round trips into system_server for a picture nothing on
           screen is waiting for. It parks on the lazy cadence instead, the
           way a detached window already does, and stateChanged() takes the
           read the moment the island is free again - so the player is back on
           screen in 400 ms of a call ending rather than at the end of a park. */
        if (!islandFree()) {
            mediaParked = true;
            mediaPollDelay = LAZY_POLL_MS;
            scheduleMediaPoll();
            return;
        }
        mediaParked = false;
        if (mediaBusy) return;                  /* a read is already in flight */
        final String knownPkg = mediaPkg;
        if (mediaIo == null) {                  /* no thread to be had: read here */
            applyMedia(readMedia(knownPkg));
            scheduleMediaPoll();
            return;
        }
        mediaBusy = true;
        try {
            mediaIo.post(new Runnable() {
                @Override
                public void run() {
                    final MediaSnapshot snap = readMedia(knownPkg);
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            mediaBusy = false;
                            applyMedia(snap);
                            scheduleMediaPoll();
                        }
                    });
                }
            });
        } catch (Throwable t) {
            mediaBusy = false;
            mediaPollDelay = LAZY_POLL_MS;
            scheduleMediaPoll();
        }
    }

    /**
     * The island is free for the player again: take the read now instead of
     * waiting out a park, so a track is back on screen 400 ms after a call ends
     * rather than up to six seconds later.
     */
    private void wakeMediaSoon() {
        ui.post(new Runnable() {
            @Override
            public void run() {
                if (!islandFree() || !attached || !pageReady || !screenOn) return;
                mediaParked = false;
                ui.removeCallbacks(mediaTick);
                ui.postDelayed(mediaTick, 400);
            }
        });
    }

    private void scheduleMediaPoll() {
        ui.removeCallbacks(mediaTick);
        if (!mediaStopped && screenOn) ui.postDelayed(mediaTick, mediaPollDelay);
    }

    private static final int MEDIA_FAILED = 0, MEDIA_NONE = 1, MEDIA_OK = 2;

    /** what one read of the phone's players found, carried across threads */
    private static final class MediaSnapshot {
        int status = MEDIA_FAILED;
        MediaController controller;
        String pkg = "";
        String title;
        String artist;
        boolean playing = false;
    }

    /** everything that blocks: binder calls only, no service state written here */
    private MediaSnapshot readMedia(String knownPkg) {
        MediaSnapshot snap = new MediaSnapshot();
        try {
            MediaSessionManager msm = (MediaSessionManager) getSystemService(MEDIA_SESSION_SERVICE);
            if (msm == null) return snap;
            List<MediaController> list = msm.getActiveSessions(new ComponentName(this, NotifListener.class));
            MediaController playing = null, known = null;
            if (list != null) {
                for (MediaController c : list) {
                    PlaybackState ps = c.getPlaybackState();
                    if (ps == null) continue;
                    int st = ps.getState();
                    if (st == PlaybackState.STATE_PLAYING && playing == null) playing = c;
                    if (known == null && knownPkg != null && knownPkg.equals(c.getPackageName())) known = c;
                }
            }
            MediaController target = playing != null ? playing : known;
            if (target == null) {
                snap.status = MEDIA_NONE;
                return snap;
            }
            MediaMetadata md = target.getMetadata();
            String title = md == null ? null : str(md.getString(MediaMetadata.METADATA_KEY_TITLE));
            String artist = md == null ? null : str(md.getString(MediaMetadata.METADATA_KEY_ARTIST));
            snap.pkg = target.getPackageName();
            snap.title = title == null ? snap.pkg : title;
            snap.artist = artist;
            PlaybackState ps = target.getPlaybackState();
            snap.playing = ps != null && ps.getState() == PlaybackState.STATE_PLAYING;
            snap.controller = target;
            snap.status = MEDIA_OK;
        } catch (Throwable ignored) {
            snap.status = MEDIA_FAILED;
        }
        return snap;
    }

    /**
     * Whether the player is allowed to be on screen right now. Idle is where a
     * track is restored, music is where it is already up; a call arriving, a
     * call being placed, a call in progress and a notification all own the
     * island until they finish, and the player waits its turn (see applyMedia).
     */
    private boolean islandFree() {
        if (callActive) return false;
        String s = currentState;
        return "idle".equals(s) || "music".equals(s);
    }

    /** the answer, applied on the main thread */
    private void applyMedia(MediaSnapshot snap) {
        if (snap == null || snap.status == MEDIA_FAILED) {
            /* A read that failed says nothing about playback, so it is no reason
               to stay at the playing cadence on the strength of an older, happy
               read - notification access being revoked while music plays would
               otherwise leave it throwing every 1.5 s for ever. */
            mediaPollDelay = LAZY_POLL_MS;
            return;
        }
        if (snap.status == MEDIA_NONE) {
            /* There is nothing left to read, so there is nothing to read
               quickly for. The cadence used to stay wherever it had got to
               while the track was playing, so the first time any player
               closed its session instead of pausing - a swipe out of recents,
               a video that finished - the service went on waking every 1.5 s
               for ever to ask system_server about a session that was gone. */
            mediaPollDelay = LAZY_POLL_MS;
            if (mediaPkg.length() > 0) {
                mediaPkg = "";
                media = null;
                lastMediaSig = "";
                eval("window.__musicEnd&&window.__musicEnd()");
            }
            return;
        }
        media = snap.controller;
        mediaPkg = snap.pkg;
        /* poll briskly while something is playing, lazily when idle */
        mediaPollDelay = snap.playing ? FAST_POLL_MS : LAZY_POLL_MS;
        /* Reading the session is cheap; crossing into the WebView is not, and
           the island rebuilds part of its DOM for every push. So only speak
           when the track, the artist or the play state changed - or when the
           island has fallen back to idle and needs the player again. */
        String sig = snap.title + '\0' + (snap.artist == null ? "" : snap.artist) + '\0' + snap.playing;
        /* A call or a notification owns the island until it finishes, so the
           player waits its turn. Re-asserting the track on the next tick
           used to take the island back from them - a notification with
           seven seconds on screen lived one and a half, and a ringing call
           lost its green and red buttons while the phone was still
           ringing - and it cost an eval into the WebView on every tick for
           as long as they were up. Idle is the only state that needs the
           player restored, so it is the only one that gets a push. */
        if (islandFree() && (!sig.equals(lastMediaSig) || !"music".equals(currentState))) {
            lastMediaSig = sig;
            eval("window.__music&&window.__music("
                    + JSONObject.quote(snap.title) + ","
                    + JSONObject.quote(snap.artist == null ? "" : snap.artist) + ","
                    + snap.playing + ")");
        }
    }

    private static String str(String v) {
        if (v == null) return null;
        String t = v.trim();
        return t.isEmpty() ? null : (t.length() > 60 ? t.substring(0, 58) + "…" : t);
    }

    private void mediaAction(String what) {
        final MediaController c = media;
        if (c == null) return;
        try {
            MediaController.TransportControls tc = c.getTransportControls();
            if (tc == null) return;
            if ("play".equals(what)) tc.play();
            else if ("pause".equals(what)) tc.pause();
            else if ("next".equals(what)) tc.skipToNext();
            else if ("prev".equals(what)) tc.skipToPrevious();
        } catch (Throwable ignored) {
        }
    }

    public static void setPosition(float px, float py) {
        pendingX = clampPct(px);
        pendingY = clampPct(py);
        hasPendingPos = true;
        IslandService s = sInstance;
        if (s != null) s.applyPositionNow(pendingX, pendingY);
    }

    public static void showCall(String name, String label,
                                PendingIntent answer, PendingIntent decline, PendingIntent open) {
        IslandService s = sInstance;
        if (s != null) s.applyCall(name, label, answer, decline, open);
    }

    public static void endCall() {
        IslandService s = sInstance;
        if (s != null) s.clearCall();
    }

    private static float clampPct(float v) {
        if (Float.isNaN(v)) return 0f;
        return v < 0f ? 0f : (v > 100f ? 100f : v);
    }

    private void applyPositionNow(float px, float py) {
        posX = clampPct(px);
        posY = clampPct(py);
        savePrefs();
        applyPosition();
    }

    /** Puts the window at posX/posY of the free space on screen. */
    private void applyPosition() {
        if (lp == null) return;
        try {
            DisplayMetrics dm = getResources().getDisplayMetrics();
            /* 0% must mean the same thing here as it does in the app's preview:
               the absolute top of the screen, not below the status bar */
            int baseTop = 0;
            int availX = Math.max(0, dm.widthPixels - lp.width);
            int availY = Math.max(0, dm.heightPixels - baseTop - lp.height);
            lp.gravity = Gravity.TOP | Gravity.LEFT;
            lp.x = Math.round((posX / 100f) * availX);
            int wantY = baseTop + Math.round((posY / 100f) * availY) - driftY;
            lp.y = Math.max(-120, wantY);
            if (attached) wm.updateViewLayout(web, lp);
        } catch (Throwable ignored) {
        }
    }

    /** compares where the window asked to be with where the system put it */
    private void measureDrift() {
        if (web == null || lp == null || !attached) return;
        try {
            web.getLocationOnScreen(locTmp);
            int d = locTmp[1] - lp.y;
            if (Math.abs(d) > 4 && driftFixes < 3) {
                driftY += d;
                driftFixes++;
                applyPosition();
            }
        } catch (Throwable ignored) {
        }
    }

    private void applyCall(String name, String label,
                           PendingIntent answer, PendingIntent decline, PendingIntent open) {
        String n = name == null ? "Unknown" : name;
        String l = label == null ? "Incoming call" : label;
        /* The phone posts its call notification again every time the call
           changes - answered, held, the other side picked up - and each of
           those used to be announced here as a new call: currentState was put
           back to "incoming" and the page was told to draw the ringing view
           again. So answering a call in the island put it straight back to
           green and red buttons for a call that was already connected, and
           the app's preview, which mirrors currentState, was told the same
           thing. A call that is live is the same call whatever the phone says
           about it; what is worth taking from a repeat is the newest label and
           the newest answer / decline actions. The page is told too, and
           ignores it for a call it is already drawing - or for one the user
           has put away, which is a gesture this must not undo. */
        boolean sameCall = callActive
                && (n.equals(callName) || "ongoing".equals(currentState)
                    || "calling".equals(currentState));
        callAnswer = answer;
        callDecline = decline;
        callOpen = open;
        if (sameCall) {
            if (pendingCall != null) pendingCall[1] = l;
            if (pageReady) {
                eval("window.__call&&window.__call("
                        + JSONObject.quote(n) + "," + JSONObject.quote(l) + ")");
            }
            return;
        }
        callName = n;
        pendingCall = new String[]{n, l};
        currentState = "incoming";
        callActive = true;
        if (!pageReady) return;
        eval("window.__call&&window.__call("
                + JSONObject.quote(pendingCall[0]) + "," + JSONObject.quote(pendingCall[1]) + ")");
        pendingCall = null;
    }

    private void clearCall() {
        callAnswer = null;
        callDecline = null;
        callOpen = null;
        pendingCall = null;
        callName = "";
        callActive = false;
        if ("incoming".equals(currentState) || "ongoing".equals(currentState)) currentState = "idle";
        eval("window.__callEnd&&window.__callEnd()");
        /* the island may have been put away while the call was up, in which
           case the page has nothing to redraw and reports no state change -
           so the player has to be let back in from here */
        wakeMediaSoon();
    }

    private void loadPrefs() {
        try {
            SharedPreferences sp = getSharedPreferences(PREFS, MODE_PRIVATE);
            posX = sp.getFloat("px", 50f);
            posY = sp.getFloat("py", 0f);
        } catch (Throwable ignored) {
        }
        if (hasPendingPos) {
            posX = pendingX;
            posY = pendingY;
        }
    }

    private void savePrefs() {
        try {
            getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                    .putFloat("px", posX).putFloat("py", posY).apply();
        } catch (Throwable ignored) {
        }
    }

    public static void setHostInForeground(boolean inForeground) {
        IslandService s = sInstance;
        if (s != null) s.applyHostVisible(!inForeground);
    }

    private void applyHostVisible(final boolean visible) {
        ui.post(new Runnable() {
            @Override
            public void run() {
                if (web == null || wm == null || lp == null) return;
                if (visible && !attached) {
                    try {
                        wm.addView(web, lp);
                        attached = true;
                        driftFixes = 0;
                        eval("window.__reportSize&&window.__reportSize()");
                        /* the window is up again, so the island is one read
                           away from the truth: take it now instead of at the
                           end of the parked lazy cadence */
                        ui.removeCallbacks(mediaTick);
                        if (screenOn) ui.postDelayed(mediaTick, 400);
                        ui.postDelayed(new Runnable() {
                            @Override
                            public void run() {
                                measureDrift();
                            }
                        }, 500);
                    } catch (Throwable ignored) {
                    }
                } else if (!visible && attached) {
                    try {
                        wm.removeView(web);
                    } catch (Throwable ignored) {
                    }
                    attached = false;
                }
            }
        });
    }

    // ---------------------------------------------------------------- overlay

    /**
     * What to do when the island's page cannot be drawn. Both cases used to be
     * silent: the window was already on screen, so the app went on reporting a
     * working island over an empty one - and a renderer that died took the
     * whole process with it, because the base WebViewClient answers that by
     * letting the framework kill the app.
     */
    private final IslandWebClient.Failure overlayFailure = new IslandWebClient.Failure() {
        @Override
        public void onLoadFailed(String reason) {
            /* the window is up but empty; say so in the app instead of claiming
               the island is live */
            lastError = reason;
        }

        @Override
        public void onRendererGone() {
            long now = SystemClock.uptimeMillis();
            if (now - lastRebuildAt < REBUILD_GAP_MS) {
                /* it died again straight away: rebuilding for ever would be a
                   worse answer than stopping with something to show for it */
                lastError = "renderer:gone";
                removeOverlay();
                RUNNING = false;
                try {
                    stopSelf();
                } catch (Throwable ignored) {
                }
                return;
            }
            lastRebuildAt = now;
            /* the state survives the page: it is pushed again into the new one
               as soon as it reports itself ready */
            if (pendingState == null) pendingState = currentState;
            removeOverlay();
            addOverlay();
        }
    };

    private void addOverlay() {
        try {
            web = new WebView(this);
            web.setBackgroundColor(Color.TRANSPARENT);
            web.setOverScrollMode(View.OVER_SCROLL_NEVER);
            WebSettings s = web.getSettings();
            s.setJavaScriptEnabled(true);
            s.setDomStorageEnabled(true);
            s.setAllowFileAccess(true);
            s.setSupportZoom(false);
            s.setBuiltInZoomControls(false);
            s.setMediaPlaybackRequiresUserGesture(false);
            s.setTextZoom(100);
            s.setUseWideViewPort(true);
            s.setLoadWithOverviewMode(false);
            web.setWebViewClient(IslandWebClient.create(overlayFailure));
            web.addJavascriptInterface(new Bridge(), "Native");

            int type = Build.VERSION.SDK_INT >= 26
                    ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                    : WindowManager.LayoutParams.TYPE_PHONE;

            int flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                    | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                    | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                    | WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED;
            if (showOnLock) flags |= WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED;

            lp = new WindowManager.LayoutParams(
                    dp(150), dp(48) + dp(PAD_DP), type, flags, PixelFormat.TRANSLUCENT);
            lp.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL;
            lp.y = 0;

            wm.addView(web, lp);
            attached = true;
            driftFixes = 0;
            applyPosition();
            ui.postDelayed(new Runnable() {
                @Override
                public void run() {
                    measureDrift();
                }
            }, 500);
            web.loadUrl("file:///android_asset/overlay.html");
            /* a brand new page has been told nothing yet */
            lastMediaSig = "";
            RUNNING = true;
            lastError = "";
            // if the app is on screen right now, step aside until it leaves
            if (MainActivity.VISIBLE) applyHostVisible(false);
        } catch (Throwable t) {
            RUNNING = false;
            lastError = "window: " + t.getClass().getSimpleName();
            try {
                stopSelf();
            } catch (Throwable ignored) {
            }
        }
    }

    private void removeOverlay() {
        if (web != null && wm != null) {
            try {
                wm.removeView(web);
            } catch (Throwable ignored) {
            }
        }
        if (web != null) {
            try {
                web.destroy();
            } catch (Throwable ignored) {
            }
        }
        web = null;
        lp = null;
        pageReady = false;
        attached = false;
        lastMediaSig = "";
    }

    /** JS reports the island box in CSS px, which is dp inside a WebView. */
    private void resizeTo(final int wCss, final int hCss) {
        ui.post(new Runnable() {
            @Override
            public void run() {
                if (web == null || lp == null) return;
                try {
                    int maxW = getResources().getDisplayMetrics().widthPixels - dp(8);
                    int w = Math.min(dp(Math.max(24, wCss)) + dp(PAD_DP) * 2, maxW);
                    int h = dp(Math.max(16, hCss)) + dp(PAD_DP);
                    if (w == lp.width && h == lp.height) return;
                    lp.width = w;
                    lp.height = h;
                    // the size is kept up to date even while detached, so the
                    // window is already right the moment it is re-attached
                    if (attached) wm.updateViewLayout(web, lp);
                    applyPosition();
                } catch (Throwable ignored) {
                }
            }
        });
    }

    private void applyState(String state) {
        pendingState = state;
        currentState = state;
        if (!pageReady) return;
        eval("window.__setState&&window.__setState(" + JSONObject.quote(state) + ")");
    }

    private void pushNotification(String app, String title, String text) {
        pendingNotif = new String[]{
                app == null ? "" : app,
                title == null ? "" : title,
                text == null ? "" : text};
        if (!pageReady) return;
        deliverNotification();
    }

    private void deliverNotification() {
        if (pendingNotif == null) return;
        eval("window.__notify&&window.__notify("
                + JSONObject.quote(pendingNotif[0]) + ","
                + JSONObject.quote(pendingNotif[1]) + ","
                + JSONObject.quote(pendingNotif[2]) + ")");
        pendingNotif = null;
    }

    private void applyConfig() {
        if (!pageReady || !hasConfig) return;
        eval("window.__setConfig&&window.__setConfig("
                + cfgWm + "," + cfgHm + "," + cfgRm + "," + cfgBounce + ")");
    }

    private void eval(final String code) {
        ui.post(new Runnable() {
            @Override
            public void run() {
                if (web == null) return;
                try {
                    web.evaluateJavascript(code, null);
                } catch (Throwable ignored) {
                }
            }
        });
    }

    // ------------------------------------------------------------------ bridge

    public class Bridge {

        @JavascriptInterface
        public void ready() {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    pageReady = true;
                    eval("window.__setMax&&window.__setMax(" + maxWidthDp() + ")");
                    /* the look the page was last given, in case it never got it */
                    applyConfig();
                    if (pendingState != null) applyState(pendingState);
                    if (pendingCall != null) {
                        eval("window.__call&&window.__call("
                                + JSONObject.quote(pendingCall[0]) + ","
                                + JSONObject.quote(pendingCall[1]) + ")");
                        pendingCall = null;
                    }
                    deliverNotification();
                }
            });
        }

        @JavascriptInterface
        public void resize(int w, int h) {
            resizeTo(w, h);
        }

        /** the floating island moved on its own (a tap, a notification) */
        @JavascriptInterface
        public void stateChanged(String state) {
            if (state == null) return;
            currentState = state;
            /* The island may have just been given back to the player - the
               caller hung up, a notification's seven seconds ran out - and the
               media loop is parked on the lazy cadence for as long as something
               else owns it. Take the read now instead of waiting out that park,
               so the track is back on screen 400 ms after a call ends and not
               up to six seconds later. The flag, not the state before this
               call, is what says so: the service marks a call ended before the
               page gets to report it, so "what it was" has already been
               overwritten by the time the report arrives. An ordinary tap
               between idle and music parks nothing and takes no read here. */
            if (!islandFree() || !mediaParked) return;
            wakeMediaSoon();
        }

        /**
         * A call ended in the island rather than in the phone. End and Decline
         * both send this, whether or not the phone owned the call - one that was
         * answered here carries no PendingIntent to fire, so nothing else would
         * tell the service the call is over, and it would go on holding the
         * player back for it.
         */
        @JavascriptInterface
        public void callEnded() {
            callActive = false;
            if (mediaParked) wakeMediaSoon();
        }

        @JavascriptInterface
        public void haptic(String kind) {
            try {
                MainActivity.vibrate(IslandService.this, kind);
            } catch (Throwable ignored) {
            }
        }

        @JavascriptInterface
        public void media(String what) {
            final String a = what == null ? "" : what;
            /* Play, pause, next and previous used to be fired from the main
               thread: the bridge left its own thread for that one, and then made
               two binder calls into whichever app owns the session -
               getTransportControls() and then play(), pause(), skipToNext() or
               skipToPrevious(). That is the same thread drawing the island's
               springs, and the tap that asks for the action is also the tap that
               starts the 24 px wobble, so a player that took a moment to answer
               (a cold Spotify, a video app coming back from the background)
               stuttered the one animation the user had just asked for. The
               media *read* was moved off this thread for exactly this reason;
               the write goes the same way now, onto the same thread, and a tap
               only pays for the frame it draws. Nothing waits on the answer
               either way - the icon has already flipped optimistically, and the
               next poll corrects it if the player disagreed. With no media
               thread to be had it still runs on the main thread, which is where
               it has always run. */
            Runnable send = new Runnable() {
                @Override
                public void run() {
                    mediaAction(a);
                }
            };
            Handler io = mediaIo;
            if (io != null) {
                try {
                    if (io.post(send)) return;
                } catch (Throwable ignored) {
                }
            }
            ui.post(send);
        }

        @JavascriptInterface
        public void setOverlayPosition(float px, float py) {
            final float fx = clampPct(px), fy = clampPct(py);
            ui.post(new Runnable() {
                @Override
                public void run() {
                    applyPositionNow(fx, fy);
                }
            });
        }

        /** the green and red buttons: fire the phone's own answer / decline action */
        @JavascriptInterface
        public void callAction(String what) {
            final boolean accept = "accept".equals(what);
            ui.post(new Runnable() {
                @Override
                public void run() {
                    PendingIntent pi = accept ? callAnswer : callDecline;
                    if (pi != null) {
                        try {
                            pi.send();
                            return;
                        } catch (Throwable ignored) {
                        }
                    }
                    if (accept && callOpen != null) {
                        try {
                            callOpen.send();
                        } catch (Throwable ignored) {
                        }
                    }
                }
            });
        }

        @JavascriptInterface
        public void openApp() {
            try {
                Intent i = new Intent(IslandService.this, MainActivity.class);
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                startActivity(i);
            } catch (Throwable ignored) {
            }
        }
    }

    // ------------------------------------------------------------ notification

    private Notification buildNotification() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (nm != null && nm.getNotificationChannel(CHANNEL_ID) == null) {
                NotificationChannel ch = new NotificationChannel(
                        CHANNEL_ID, "Floating island", NotificationManager.IMPORTANCE_MIN);
                ch.setShowBadge(false);
                ch.setDescription("Keeps the Dynamic Island on screen over other apps");
                nm.createNotificationChannel(ch);
            }
        }
        int piFlags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= 23) piFlags |= PendingIntent.FLAG_IMMUTABLE;

        PendingIntent open = PendingIntent.getActivity(
                this, 0, new Intent(this, MainActivity.class), piFlags);
        PendingIntent off = PendingIntent.getService(
                this, 1, new Intent(this, IslandService.class).setAction(ACTION_STOP), piFlags);

        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL_ID)
                : new Notification.Builder(this);
        b.setContentTitle("Dynamic Island is on")
                .setContentText("Floating over your apps")
                .setSmallIcon(R.drawable.ic_stat)
                .setOngoing(true)
                .setShowWhen(false)
                .setContentIntent(open)
                .addAction(new Notification.Action.Builder(
                        null, "Turn off", off).build());
        if (Build.VERSION.SDK_INT < 26) b.setPriority(Notification.PRIORITY_MIN);
        return b.build();
    }

    // ------------------------------------------------------------------ utils

    private int dp(int v) {
        return Math.round(v * density);
    }

    private int maxWidthDp() {
        try {
            float d = getResources().getDisplayMetrics().density;
            return Math.max(160, Math.round(getResources().getDisplayMetrics().widthPixels / d) - 24);
        } catch (Throwable t) {
            return 320;
        }
    }

    private int statusBarHeight() {
        try {
            int id = getResources().getIdentifier("status_bar_height", "dimen", "android");
            if (id > 0) return getResources().getDimensionPixelSize(id);
        } catch (Throwable ignored) {
        }
        return dp(24);
    }
}
