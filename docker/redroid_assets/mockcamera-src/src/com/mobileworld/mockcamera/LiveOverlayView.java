package com.mobileworld.mockcamera;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.util.AttributeSet;
import android.view.View;

/**
 * A lightweight, normal-RGBA animated overlay that makes the static viewfinder scene
 * read as a "live" camera feed: a softly drifting exposure highlight plus a focus
 * reticle and rule-of-thirds grid lines, all drawn through the standard view canvas
 * (which redroid's software GL composites and screencap captures, unlike a video/GL
 * texture).
 */
public class LiveOverlayView extends View {

    private final Paint gridPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint glowPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint reticlePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private long startTime;

    public LiveOverlayView(Context c) { super(c); init(); }
    public LiveOverlayView(Context c, AttributeSet a) { super(c, a); init(); }
    public LiveOverlayView(Context c, AttributeSet a, int s) { super(c, a, s); init(); }

    private void init() {
        startTime = System.currentTimeMillis();
        gridPaint.setColor(0x33FFFFFF);
        gridPaint.setStrokeWidth(2f);
        glowPaint.setColor(0x22FFFFFF);
        reticlePaint.setStyle(Paint.Style.STROKE);
        reticlePaint.setColor(0xCCFFFFFF);
        reticlePaint.setStrokeWidth(3f);
        setLayerType(LAYER_TYPE_HARDWARE, null);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        int w = getWidth(), h = getHeight();
        if (w == 0 || h == 0) return;
        float t = (System.currentTimeMillis() - startTime) / 1000f;

        // Rule-of-thirds grid (static, like a camera framing aid).
        canvas.drawLine(w / 3f, 0, w / 3f, h, gridPaint);
        canvas.drawLine(2 * w / 3f, 0, 2 * w / 3f, h, gridPaint);
        canvas.drawLine(0, h / 3f, w, h / 3f, gridPaint);
        canvas.drawLine(0, 2 * h / 3f, w, 2 * h / 3f, gridPaint);

        // Drifting soft exposure glow -> conveys "live" without a video texture.
        float cx = w * (0.5f + 0.28f * (float) Math.sin(t * 0.7));
        float cy = h * (0.42f + 0.18f * (float) Math.cos(t * 0.5));
        float r = Math.min(w, h) * (0.22f + 0.04f * (float) Math.sin(t * 1.3));
        canvas.drawCircle(cx, cy, r, glowPaint);
        canvas.drawCircle(cx, cy, r * 0.6f, glowPaint);

        // Center focus reticle (corner brackets), pulsing slightly.
        float pulse = 1f + 0.06f * (float) Math.sin(t * 2.5);
        float bx = w / 2f, by = h * 0.42f;
        float s = Math.min(w, h) * 0.13f * pulse;
        float arm = s * 0.35f;
        // top-left
        canvas.drawLine(bx - s, by - s, bx - s + arm, by - s, reticlePaint);
        canvas.drawLine(bx - s, by - s, bx - s, by - s + arm, reticlePaint);
        // top-right
        canvas.drawLine(bx + s, by - s, bx + s - arm, by - s, reticlePaint);
        canvas.drawLine(bx + s, by - s, bx + s, by - s + arm, reticlePaint);
        // bottom-left
        canvas.drawLine(bx - s, by + s, bx - s + arm, by + s, reticlePaint);
        canvas.drawLine(bx - s, by + s, bx - s, by + s - arm, reticlePaint);
        // bottom-right
        canvas.drawLine(bx + s, by + s, bx + s - arm, by + s, reticlePaint);
        canvas.drawLine(bx + s, by + s, bx + s, by + s - arm, reticlePaint);

        // ~20 fps animation.
        postInvalidateDelayed(50);
    }
}
