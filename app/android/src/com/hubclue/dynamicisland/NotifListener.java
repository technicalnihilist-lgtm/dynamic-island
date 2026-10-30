package com.hubclue.dynamicisland;

import android.app.Notification;
import android.app.PendingIntent;
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

            String title = ex == null ? null : text(ex.getCharSequence(Notification.EXTRA_TITLE));
            String body = ex == null ? null : text(ex.getCharSequence(Notification.EXTRA_TEXT));
            if (body == null && ex != null) body = text(ex.getCharSequence(Notification.EXTRA_BIG_TEXT));
            if (body == null && ex != null) body = text(ex.getCharSequence(Notification.EXTRA_SUB_TEXT));

            // A ringing call gets the island's incoming-call state, with the same
            // green and red buttons as the demo - wired to the phone's own actions.
            if (Notification.CATEGORY_CALL.equals(n.category)) {
                PendingIntent answer = null, decline = null;
                Notification.Action[] acts = n.actions;
                if (acts != null) {
                    for (Notification.Action a : acts) {
                        if (a == null || a.actionIntent == null) continue;
                        String t = a.title == null ? "" : a.title.toString().toLowerCase();
                        if (answer == null && looksAnswer(t)) answer = a.actionIntent;
                        else if (decline == null && looksDecline(t)) decline = a.actionIntent;
                    }
                    if (answer == null && decline == null && acts.length >= 2) {
                        answer = acts[0].actionIntent;
                        decline = acts[1].actionIntent;
                    }
                }
                IslandService.showCall(title != null ? title : appLabel(pkg),
                        body != null ? body : "Incoming call",
                        answer, decline, n.contentIntent);
                return;
            }

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

    @Override
    public void onNotificationRemoved(StatusBarNotification sbn) {
        try {
            if (sbn == null) return;
            Notification n = sbn.getNotification();
            if (n != null && Notification.CATEGORY_CALL.equals(n.category)) {
                IslandService.endCall();
            }
        } catch (Throwable ignored) {
        }
    }

    private static boolean looksAnswer(String t) {
        String[] keys = {"answer", "accept", "pick up", "attend", "répondre", "उत्तर", "स्वीकार", "जवाब", "接听"};
        for (String k : keys) if (t.contains(k)) return true;
        return false;
    }

    private static boolean looksDecline(String t) {
        String[] keys = {"decline", "reject", "end call", "hang up", "ignore", "काट", "अस्वीकार", "रद्द", "拒绝", "拒接"};
        for (String k : keys) if (t.contains(k)) return true;
        return false;
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
