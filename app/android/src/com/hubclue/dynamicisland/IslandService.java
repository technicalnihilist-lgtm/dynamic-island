package com.hubclue.dynamicisland;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

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

    public static volatile boolean RUNNING = false;
    /** last state the island was put in, so the app can mirror it on resume */
    public static volatile String currentState = "idle";
    /** last failure, surfaced in the app so a broken overlay is never silent */
    public static volatile String lastError = "";
    private static IslandService sInstance;
    private boolean attached = false;

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
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
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

    public static void config(float wm_, float hm_, float rm_, float bounce) {
        IslandService s = sInstance;
        if (s != null) s.applyConfig(wm_, hm_, rm_, bounce);
    }

    /**
     * While the app is in front it draws its own preview, so the floating window
     * is detached. Detaching (rather than hiding) matters: a hidden overlay
     * window would still swallow touches meant for the app underneath.
     */
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
                        eval("window.__reportSize&&window.__reportSize()");
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
            web.setWebViewClient(new WebViewClient());
            web.addJavascriptInterface(new Bridge(), "Native");

            int type = Build.VERSION.SDK_INT >= 26
                    ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                    : WindowManager.LayoutParams.TYPE_PHONE;

            int flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                    | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                    | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                    | WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED;

            lp = new WindowManager.LayoutParams(
                    dp(150), dp(48) + dp(PAD_DP), type, flags, PixelFormat.TRANSLUCENT);
            lp.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL;
            // hard against the top of the screen, just under the status bar
            lp.y = statusBarHeight() + dp(2);

            wm.addView(web, lp);
            attached = true;
            web.loadUrl("file:///android_asset/overlay.html");
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

    private void applyConfig(float wm_, float hm_, float rm_, float bounce) {
        if (!pageReady) return;
        eval("window.__setConfig&&window.__setConfig(" + wm_ + "," + hm_ + "," + rm_ + "," + bounce + ")");
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
                    if (pendingState != null) applyState(pendingState);
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
            if (state != null) currentState = state;
        }

        @JavascriptInterface
        public void haptic(String kind) {
            try {
                MainActivity.vibrate(IslandService.this, kind);
            } catch (Throwable ignored) {
            }
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
        return Math.round(v * getResources().getDisplayMetrics().density);
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
