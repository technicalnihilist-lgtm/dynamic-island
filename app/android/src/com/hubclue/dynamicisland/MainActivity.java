package com.hubclue.dynamicisland;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Insets;
import android.net.Uri;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Bundle;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.provider.Settings;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * The control room. Holds the in-app preview of the island and the switch that
 * turns the system-wide overlay on and off.
 */
public class MainActivity extends Activity {

    private WebView web;
    private int insetTop = 0;
    private int insetBottom = 0;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);

        Window w = getWindow();
        w.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
        w.setStatusBarColor(Color.TRANSPARENT);
        w.setNavigationBarColor(Color.TRANSPARENT);
        w.setBackgroundDrawableResource(R.drawable.bg_gradient);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            w.setDecorFitsSystemWindows(false);
        } else {
            w.getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        }

        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0C0D12"));
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setTextZoom(100);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(false);

        web.setWebViewClient(new WebViewClient());
        web.addJavascriptInterface(new Bridge(), "Native");

        web.setOnApplyWindowInsetsListener(new View.OnApplyWindowInsetsListener() {
            @Override
            public WindowInsets onApplyWindowInsets(View v, WindowInsets insets) {
                readInsets(insets);
                if (web != null) {
                    web.evaluateJavascript("window.__applyInsets&&window.__applyInsets()", null);
                }
                return insets;
            }
        });

        setContentView(web);
        web.loadUrl("file:///android_asset/index.html");

        askForNotificationPermission();
    }

    private void askForNotificationPermission() {
        try {
            if (Build.VERSION.SDK_INT >= 33 &&
                    checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                            != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 11);
            }
        } catch (Throwable ignored) {
        }
    }

    private void readInsets(WindowInsets insets) {
        if (insets == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Insets i = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
            insetTop = i.top;
            insetBottom = i.bottom;
        } else {
            insetTop = insets.getSystemWindowInsetTop();
            insetBottom = insets.getSystemWindowInsetBottom();
        }
    }

    // ------------------------------------------------------------- the overlay

    private boolean canDraw() {
        try {
            return Build.VERSION.SDK_INT < 23 || Settings.canDrawOverlays(this);
        } catch (Throwable t) {
            return false;
        }
    }

    private boolean notifAccess() {
        try {
            String flat = Settings.Secure.getString(getContentResolver(), "enabled_notification_listeners");
            return flat != null && flat.contains(getPackageName());
        } catch (Throwable t) {
            return false;
        }
    }

    private void askForOverlay() {
        try {
            startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + getPackageName())));
        } catch (Throwable t) {
            try {
                startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION));
            } catch (Throwable ignored) {
            }
        }
    }

    private void askForNotifAccess() {
        try {
            startActivity(new Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS"));
        } catch (Throwable t) {
            try {
                startActivity(new Intent(Settings.ACTION_SETTINGS));
            } catch (Throwable ignored) {
            }
        }
    }

    private void startIsland() {
        if (!canDraw()) {
            askForOverlay();
            return;
        }
        try {
            Intent i = new Intent(this, IslandService.class).setAction(IslandService.ACTION_START);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(i);
            else startService(i);
        } catch (Throwable ignored) {
        }
    }

    private void stopIsland() {
        try {
            stopService(new Intent(this, IslandService.class));
        } catch (Throwable ignored) {
        }
    }

    private void pushSystemState() {
        if (web == null) return;
        String js = "window.__sysState&&window.__sysState("
                + canDraw() + "," + IslandService.RUNNING + "," + notifAccess() + ")";
        try {
            web.evaluateJavascript(js, null);
        } catch (Throwable ignored) {
        }
    }

    // ------------------------------------------------------------------ bridge

    public class Bridge {

        @JavascriptInterface
        public String insets() {
            return insetTop + "," + insetBottom;
        }

        @JavascriptInterface
        public int battery() {
            try {
                Intent i = registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
                if (i == null) return -1;
                int level = i.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
                int scale = i.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
                if (level < 0 || scale <= 0) return -1;
                return Math.round(level * 100f / scale);
            } catch (Exception e) {
                return -1;
            }
        }

        @JavascriptInterface
        public void haptic(String kind) {
            vibrate(MainActivity.this, kind);
        }

        @JavascriptInterface
        public boolean canDrawOverlays() {
            return canDraw();
        }

        @JavascriptInterface
        public boolean overlayRunning() {
            return IslandService.RUNNING;
        }

        @JavascriptInterface
        public boolean hasNotifAccess() {
            return notifAccess();
        }

        @JavascriptInterface
        public void requestOverlay() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    askForOverlay();
                }
            });
        }

        @JavascriptInterface
        public void requestNotifAccess() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    askForNotifAccess();
                }
            });
        }

        @JavascriptInterface
        public void startOverlay() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    startIsland();
                }
            });
        }

        @JavascriptInterface
        public void stopOverlay() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    stopIsland();
                }
            });
        }

        @JavascriptInterface
        public void setOverlayState(String state) {
            IslandService.setState(state);
        }

        @JavascriptInterface
        public void setOverlayConfig(float wm, float hm, float rm, float bounce) {
            IslandService.config(wm, hm, rm, bounce);
        }
    }

    // ------------------------------------------------------------------ static

    static void vibrate(Context ctx, String kind) {
        try {
            Vibrator v = (Vibrator) ctx.getSystemService(VIBRATOR_SERVICE);
            if (v == null || !v.hasVibrator()) return;
            boolean medium = "medium".equals(kind);
            int ms = medium ? 18 : 10;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                v.vibrate(VibrationEffect.createOneShot(ms, medium ? 150 : 90));
            } else {
                v.vibrate(ms);
            }
        } catch (Exception ignored) {
        }
    }

    // --------------------------------------------------------------- lifecycle

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) web.onResume();
        pushSystemState();
        web.postDelayed(new Runnable() {
            @Override
            public void run() {
                pushSystemState();
            }
        }, 400);
    }

    @Override
    public void onBackPressed() {
        if (web == null) {
            super.onBackPressed();
            return;
        }
        web.evaluateJavascript("(window.__onBack&&window.__onBack())?'1':'0'",
                new ValueCallback<String>() {
                    @Override
                    public void onReceiveValue(String value) {
                        if (!"\"1\"".equals(value)) {
                            MainActivity.super.onBackPressed();
                        }
                    }
                });
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (web != null) web.onPause();
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
