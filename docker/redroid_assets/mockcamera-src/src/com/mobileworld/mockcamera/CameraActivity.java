package com.mobileworld.mockcamera;

import android.app.Activity;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.media.MediaScannerConnection;
import android.provider.MediaStore;
import android.util.Log;
import android.view.View;
import android.view.animation.AlphaAnimation;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

public class CameraActivity extends Activity {

    private static final String TAG = "MockCamera";
    private ImageView viewfinderImage;
    private View liveOverlay;
    private ImageView thumbnail;
    private View flash;
    private boolean frontCamera = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_camera);

        viewfinderImage = findViewById(R.id.viewfinderImage);
        liveOverlay = findViewById(R.id.liveOverlay);
        thumbnail = findViewById(R.id.thumbnail);
        flash = findViewById(R.id.flash);
        ImageButton shutter = findViewById(R.id.shutter);
        ImageButton flip = findViewById(R.id.flipCamera);

        shutter.setOnClickListener(v -> onShutter());
        flip.setOnClickListener(v -> {
            frontCamera = !frontCamera;
            // Subtle mirror flip to imply a different camera, still plain RGBA.
            float sx = viewfinderImage.getScaleX();
            viewfinderImage.setScaleX(-sx);
            Toast.makeText(this, frontCamera ? "Front camera" : "Back camera", Toast.LENGTH_SHORT).show();
        });
    }

    private boolean isImageCaptureIntent() {
        String action = getIntent() != null ? getIntent().getAction() : null;
        return MediaStore.ACTION_IMAGE_CAPTURE.equals(action)
                || "android.media.action.IMAGE_CAPTURE_SECURE".equals(action)
                || MediaStore.ACTION_VIDEO_CAPTURE.equals(action);
    }

    private void onShutter() {
        flashEffect();
        byte[] jpeg = renderStillJpeg();
        String filename = "IMG_" + new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(new Date()) + ".jpg";

        if (isImageCaptureIntent()) {
            Uri output = getIntent().getParcelableExtra(MediaStore.EXTRA_OUTPUT);
            boolean wrote = false;
            if (output != null) {
                wrote = writeToUri(output, jpeg);
            }
            Uri saved = saveToGallery(filename, jpeg);
            updateThumbnail(jpeg);
            Intent result = new Intent();
            if (!wrote && saved != null) {
                result.setData(saved);
            } else if (jpeg != null) {
                Bitmap bmp = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length);
                if (bmp != null) result.putExtra("data", bmp);
            }
            setResult(Activity.RESULT_OK, result);
            Toast.makeText(this, "Photo captured", Toast.LENGTH_SHORT).show();
            new Handler(Looper.getMainLooper()).postDelayed(this::finish, 600);
            return;
        }

        Uri saved = saveToGallery(filename, jpeg);
        updateThumbnail(jpeg);
        Toast.makeText(this, saved != null ? "Saved to gallery" : "Save failed", Toast.LENGTH_SHORT).show();
    }

    /** Capture the current viewfinder by drawing the live views into a bitmap. */
    private byte[] renderStillJpeg() {
        try {
            int w = viewfinderImage.getWidth();
            int h = viewfinderImage.getHeight();
            if (w > 0 && h > 0) {
                Bitmap bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
                Canvas c = new Canvas(bmp);
                viewfinderImage.draw(c);
                if (liveOverlay != null) liveOverlay.draw(c);
                java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
                bmp.compress(Bitmap.CompressFormat.JPEG, 92, bos);
                byte[] data = bos.toByteArray();
                if (data.length > 0) return data;
            }
        } catch (Exception e) {
            Log.w(TAG, "renderStillJpeg from views failed: " + e);
        }
        // Fallback: encode the bundled scene drawable.
        try {
            Bitmap bmp = BitmapFactory.decodeResource(getResources(), R.drawable.viewfinder_scene);
            if (bmp != null) {
                java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
                bmp.compress(Bitmap.CompressFormat.JPEG, 92, bos);
                return bos.toByteArray();
            }
        } catch (Exception e) {
            Log.w(TAG, "renderStillJpeg from drawable failed: " + e);
        }
        Bitmap bmp = Bitmap.createBitmap(1080, 1920, Bitmap.Config.ARGB_8888);
        bmp.eraseColor(0xFF335577);
        java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
        bmp.compress(Bitmap.CompressFormat.JPEG, 90, bos);
        return bos.toByteArray();
    }

    private Uri saveToGallery(String filename, byte[] jpeg) {
        ContentResolver resolver = getContentResolver();
        long nowSec = System.currentTimeMillis() / 1000L;

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ContentValues values = new ContentValues();
            values.put(MediaStore.Images.Media.DISPLAY_NAME, filename);
            values.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
            values.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES);
            values.put(MediaStore.Images.Media.DATE_ADDED, nowSec);
            values.put(MediaStore.Images.Media.DATE_MODIFIED, nowSec);
            values.put(MediaStore.Images.Media.IS_PENDING, 1);

            Uri collection = MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY);
            Uri item = resolver.insert(collection, values);
            if (item == null) {
                Log.w(TAG, "MediaStore insert returned null");
                return saveLegacy(filename, jpeg);
            }
            try (OutputStream os = resolver.openOutputStream(item)) {
                if (os != null) { os.write(jpeg); os.flush(); }
            } catch (Exception e) {
                Log.w(TAG, "Write to MediaStore uri failed: " + e);
                return saveLegacy(filename, jpeg);
            }
            ContentValues done = new ContentValues();
            done.put(MediaStore.Images.Media.IS_PENDING, 0);
            done.put(MediaStore.Images.Media.DATE_ADDED, nowSec);
            done.put(MediaStore.Images.Media.DATE_MODIFIED, nowSec);
            resolver.update(item, done, null, null);
            Log.i(TAG, "Saved via MediaStore: " + item + " (" + filename + ")");
            return item;
        } else {
            return saveLegacy(filename, jpeg);
        }
    }

    private Uri saveLegacy(String filename, byte[] jpeg) {
        try {
            File dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES);
            if (!dir.exists()) dir.mkdirs();
            File out = new File(dir, filename);
            try (FileOutputStream fos = new FileOutputStream(out)) { fos.write(jpeg); fos.flush(); }
            MediaScannerConnection.scanFile(this, new String[]{out.getAbsolutePath()},
                    new String[]{"image/jpeg"}, null);
            Log.i(TAG, "Saved legacy: " + out.getAbsolutePath());
            return Uri.fromFile(out);
        } catch (Exception e) {
            Log.e(TAG, "saveLegacy failed: " + e);
            return null;
        }
    }

    private boolean writeToUri(Uri uri, byte[] jpeg) {
        try {
            if ("file".equals(uri.getScheme())) {
                File f = new File(uri.getPath());
                File parent = f.getParentFile();
                if (parent != null && !parent.exists()) parent.mkdirs();
                try (FileOutputStream fos = new FileOutputStream(f)) { fos.write(jpeg); fos.flush(); }
                return true;
            }
            ParcelFileDescriptor pfd = getContentResolver().openFileDescriptor(uri, "w");
            if (pfd != null) {
                try (FileOutputStream fos = new FileOutputStream(pfd.getFileDescriptor())) {
                    fos.write(jpeg); fos.flush();
                }
                pfd.close();
                return true;
            }
        } catch (Exception e) {
            Log.w(TAG, "writeToUri failed: " + e);
        }
        return false;
    }

    private void updateThumbnail(byte[] jpeg) {
        try {
            Bitmap bmp = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length);
            if (bmp != null && thumbnail != null) thumbnail.setImageBitmap(bmp);
        } catch (Exception ignored) {}
    }

    private void flashEffect() {
        if (flash == null) return;
        flash.setVisibility(View.VISIBLE);
        AlphaAnimation anim = new AlphaAnimation(0.9f, 0f);
        anim.setDuration(350);
        flash.startAnimation(anim);
        new Handler(Looper.getMainLooper()).postDelayed(() -> flash.setVisibility(View.GONE), 360);
    }
}
