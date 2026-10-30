package com.hubclue.dynamicisland;

import android.app.Notification;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

/**
 * Mirrors real notifications into the floating island. Completely optional: if
 * the user never grants notification access the listener is simply never bound,
 * and the island still works on its own.
 */
public class NotifListener extends NotificationListenerService {

    private static final long MIN_GAP_MS = 900;
    private long lastAt = 0;

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        try {
            if (sbn == null || !IslandService.RUNNING) return;
            String pkg = sbn.getPackageName();
            if (pkg == null || pkg.equals(getPackageName())) return;

            Notification n = sbn.getNotification();
            if (n == null) return;
            Bundle ex = n.extras;
            if (ex == null) return;

            String title = text(ex.getCharSequence(Notification.EXTRA_TITLE));
            String body = text(ex.getCharSequence(Notification.EXTRA_TEXT));
            if (body == null) body = text(ex.getCharSequence(Notification.EXTRA_BIG_TEXT));
            if (body == null) body = text(ex.getCharSequence(Notification.EXTRA_SUB_TEXT));
            if (title == null && body == null) return;
            if (title == null) title = appLabel(pkg);
            if (body == null) body = "";

            long now = System.currentTimeMillis();
            if (now - lastAt < MIN_GAP_MS) return;
            lastAt = now;

            IslandService.showNotification(appLabel(pkg), title, body);
        } catch (Throwable ignored) {
        }
    }

    private static String text(CharSequence cs) {
        if (cs == null) return null;
        String s = cs.toString().trim();
        if (s.isEmpty()) return null;
        if (s.length() > 90) s = s.substring(0, 88) + "…";
        return s;
    }

    private String appLabel(String pkg) {
        try {
            PackageManager pm = getPackageManager();
            ApplicationInfo ai = pm.getApplicationInfo(pkg, 0);
            CharSequence l = pm.getApplicationLabel(ai);
            if (l != null && l.length() > 0) return l.toString();
        } catch (Throwable ignored) {
        }
        return pkg;
    }
}
