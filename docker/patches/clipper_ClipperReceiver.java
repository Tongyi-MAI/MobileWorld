package ca.zgrs.clipper;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

/**
 * Receives broadcast commands and controls clipboard accordingly.
 *
 * Patched for MobileWorld: uses android.content.ClipboardManager + ClipData
 * instead of deprecated android.text.ClipboardManager.
 */
public class ClipperReceiver extends BroadcastReceiver {
    private static final String TAG = "ClipboardReceiver";

    public static final String ACTION_GET = "clipper.get";
    public static final String ACTION_GET_SHORT = "get";
    public static final String ACTION_SET = "clipper.set";
    public static final String ACTION_SET_SHORT = "set";
    public static final String EXTRA_TEXT = "text";

    public static boolean isActionGet(final String action) {
        return ACTION_GET.equals(action) || ACTION_GET_SHORT.equals(action);
    }

    public static boolean isActionSet(final String action) {
        return ACTION_SET.equals(action) || ACTION_SET_SHORT.equals(action);
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        ClipboardManager cb = (ClipboardManager) context.getSystemService(Context.CLIPBOARD_SERVICE);
        if (isActionSet(intent.getAction())) {
            Log.d(TAG, "Setting text into clipboard");
            String text = intent.getStringExtra(EXTRA_TEXT);
            if (text != null) {
                cb.setPrimaryClip(ClipData.newPlainText("clipper", text));
                setResultCode(Activity.RESULT_OK);
                setResultData("Text is copied into clipboard.");
            } else {
                setResultCode(Activity.RESULT_CANCELED);
                setResultData("No text is provided. Use -e text \"text to be pasted\"");
            }
        } else if (isActionGet(intent.getAction())) {
            Log.d(TAG, "Getting text from clipboard");
            ClipData clip = cb.getPrimaryClip();
            if (clip != null && clip.getItemCount() > 0) {
                CharSequence text = clip.getItemAt(0).getText();
                Log.d(TAG, String.format("Clipboard text: %s", text));
                setResultCode(Activity.RESULT_OK);
                setResultData(text != null ? text.toString() : "");
            } else {
                setResultCode(Activity.RESULT_CANCELED);
                setResultData("");
            }
        }
    }
}
