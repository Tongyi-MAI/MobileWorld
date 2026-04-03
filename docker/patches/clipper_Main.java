package ca.zgrs.clipper;

import android.app.Activity;
import android.os.Bundle;

/**
 * Minimal launchable activity.
 *
 * Patched for MobileWorld: removed setContentView (avoids resource compilation)
 * and removed ClipboardService start (not needed — app is launched to foreground
 * before every clipboard operation).
 */
public class Main extends Activity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
    }
}
