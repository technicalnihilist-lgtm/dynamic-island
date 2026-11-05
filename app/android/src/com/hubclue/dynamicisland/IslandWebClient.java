package com.hubclue.dynamicisland;

import android.annotation.TargetApi;
import android.os.Build;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * The client both of the app's WebViews use, so that a page which cannot be
 * drawn is reported instead of being drawn as nothing.
 *
 * Two failures are handled here, and both used to be invisible:
 *
 * A page that never loads — a missing asset, a corrupt WebView package, a
 * renderer that refuses to start — fired no callback at all, so the window came
 * up empty and the app went on saying "Live over your other apps". The load
 * error is now passed back, and the caller can put it in front of the user.
 *
 * A renderer that Android kills — which is what Android does to a WebView when
 * memory runs short, and an always-on overlay over every app is exactly the
 * thing it picks on — is announced to {@link WebViewClient#onRenderProcessGone}.
 * The base class answers that with `false`, and the framework then kills the
 * whole process: the island disappears with no message, no crash dialog and no
 * way to know it was ever there. The subclass that overrides it, on the API
 * levels that have that callback at all, answers `true` so the death is ours to
 * deal with, and hands it back to the caller to rebuild. Before API 26 the
 * framework did not kill the process over this, so there is nothing to handle.
 */
public class IslandWebClient extends WebViewClient {

    /** what the owner of the WebView has to do about a failure */
    public interface Failure {
        /** the main frame could not be loaded; the window will stay empty */
        void onLoadFailed(String reason);

        /** the renderer process died under us; this WebView is no longer usable */
        void onRendererGone();
    }

    private final Failure failure;

    protected IslandWebClient(Failure failure) {
        this.failure = failure;
    }

    /** the client to install: renderer-death aware where the platform has it */
    public static WebViewClient create(Failure failure) {
        if (Build.VERSION.SDK_INT >= 26) return new RendererSafe(failure);
        return new IslandWebClient(failure);
    }

    protected void reportLoad(String reason) {
        if (failure != null) {
            try {
                failure.onLoadFailed(reason);
            } catch (Throwable ignored) {
            }
        }
    }

    protected void reportRendererGone() {
        if (failure != null) {
            try {
                failure.onRendererGone();
            } catch (Throwable ignored) {
            }
        }
    }

    @Override
    public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
        /* sub-resource failures are normal (an image that is not there) and do
           not stop the page; only the main frame not loading does */
        if (request == null || !request.isForMainFrame()) return;
        reportLoad("load:" + (error == null ? "?" : String.valueOf(error.getErrorCode())));
    }

    @TargetApi(26)
    private static final class RendererSafe extends IslandWebClient {

        RendererSafe(Failure failure) {
            super(failure);
        }

        @Override
        public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
            /* true: the process is ours to keep. The WebView is dead either way,
               so the caller tears it down and builds a new one. */
            reportRendererGone();
            return true;
        }
    }
}
