package com.mobileworld.smsnotifier;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

/**
 * Posts a persistent SMS-style notification when broadcast with action
 * com.mobileworld.smsnotifier.SHOW and string extras "sender" + "body".
 * A real-app notification survives the process exit (a shell `cmd notification
 * post` does not), so it stays in the shade for the agent to read.
 */
public class NotifyReceiver extends BroadcastReceiver {
    private static final String CHANNEL_ID = "sms";

    @Override
    public void onReceive(Context ctx, Intent intent) {
        String sender = intent.getStringExtra("sender");
        String body = intent.getStringExtra("body");
        if (sender == null || sender.isEmpty()) sender = "Message";
        if (body == null) body = "";

        NotificationManager nm =
                (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(
                    CHANNEL_ID, "SMS", NotificationManager.IMPORTANCE_HIGH);
            ch.setDescription("Incoming text messages");
            nm.createNotificationChannel(ch);
        }

        Notification.Builder b = (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                ? new Notification.Builder(ctx, CHANNEL_ID)
                : new Notification.Builder(ctx);
        b.setSmallIcon(android.R.drawable.stat_notify_chat)
                .setContentTitle(sender)
                .setContentText(body)
                .setStyle(new Notification.BigTextStyle().bigText(body))
                .setAutoCancel(true);

        // unique id per message so multiple SMS stack instead of replacing
        int id = (int) (System.currentTimeMillis() & 0x7fffffff);
        nm.notify("smsnotifier", id, b.build());
    }
}
