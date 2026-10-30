package com.hubclue.dynamicisland;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Color;
import android.graphics.Insets;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Bundle;
import android.os.VibrationEffect;
import android.os.Vibrator;
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
 * Dynamic Island - a single-activity WebView shell around assets/index.html.
 * The shell only adds what a browser cannot: real system insets, real battery
 * level, real haptics and a sensible hardware back button.
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

    /** Bridge exposed to the page as window.Native */
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
            try {
                Vibrator v = (Vibrator) getSystemService(VIBRATOR_SERVICE);
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
    protected void onResume() {
        super.onResume();
        if (web != null) web.onResume();
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
