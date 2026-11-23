package com.chatbox.buctwifi;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.Build;
import android.os.IBinder;

/** 常驻前台服务：定时检测是否掉线，掉线自动登录 */
public class AutoLoginService extends Service {

    public static final String ACTION_START = "com.chatbox.buctwifi.action.START";
    public static final String ACTION_STOP = "com.chatbox.buctwifi.action.STOP";
    public static final String ACTION_CHECK = "com.chatbox.buctwifi.action.CHECK";

    private static final String CHANNEL_ID = "buct_auto_login";
    private static final int NOTIF_ID = 1001;

    /** 供界面读取的运行时状态 */
    public static volatile String LAST_STATUS = "未启动";
    public static volatile boolean RUNNING = false;

    private volatile boolean running = false;
    private volatile boolean wake = false;
    private Thread worker;
    private String notifText = "";

    private String lastLogged = "";
    private long lastLoggedAt = 0;

    @Override
    public void onCreate() {
        super.onCreate();
        LogStore.init(this);
        createChannel();
        AutoLoginService.RUNNING = false;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? ACTION_START : intent.getAction();
        if (ACTION_STOP.equals(action)) {
            Prefs.setEnabled(this, false);
            LogStore.log("已手动停止守护");
            stopSelf();
            return START_NOT_STICKY;
        }
        if (ACTION_CHECK.equals(action)) {
            wake = true;
        }
        Prefs.setEnabled(this, true);
        startForegroundCompat();
        if (!running) startWorker();
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        running = false;
        RUNNING = false;
        if (worker != null) {
            worker.interrupt();
            worker = null;
        }
        LAST_STATUS = "已停止";
        try {
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) nm.cancel(NOTIF_ID);
        } catch (Throwable ignored) {
        }
        LogStore.log("守护进程已停止");
        super.onDestroy();
    }

    // ------------------------------------------------------------------ 通知

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm == null) return;
            NotificationChannel ch = new NotificationChannel(CHANNEL_ID, "校园网自动登录",
                    NotificationManager.IMPORTANCE_LOW);
            ch.setDescription("断网自动登录守护进程状态");
            ch.setShowBadge(false);
            nm.createNotificationChannel(ch);
        }
    }

    private Notification buildNotification(String text) {
        Intent open = new Intent(this, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        int piFlags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= 23) piFlags |= PendingIntent.FLAG_IMMUTABLE;
        PendingIntent pi = PendingIntent.getActivity(this, 0, open, piFlags);

        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= 26) {
            b = new Notification.Builder(this, CHANNEL_ID);
        } else {
            b = new Notification.Builder(this);
        }
        b.setContentTitle("校园网自动登录")
                .setContentText(text)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentIntent(pi)
                .setOngoing(true)
                .setOnlyAlertOnce(true);
        if (Build.VERSION.SDK_INT >= 21) b.setShowWhen(false);
        return b.build();
    }

    private void startForegroundCompat() {
        Notification n = buildNotification(notifText.isEmpty() ? "正在启动…" : notifText);
        try {
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            } else if (Build.VERSION.SDK_INT >= 29) {
                startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
            } else {
                startForeground(NOTIF_ID, n);
            }
        } catch (Throwable t) {
            // 极端情况下（如类型不受支持）退回普通前台通知
            try {
                startForeground(NOTIF_ID, n);
            } catch (Throwable ignored) {
            }
        }
    }

    private void updateNotification(String text) {
        LAST_STATUS = text;
        if (text.equals(notifText)) return;
        notifText = text;
        try {
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) nm.notify(NOTIF_ID, buildNotification(text));
        } catch (Throwable ignored) {
        }
    }

    // ------------------------------------------------------------------ 主循环

    private void startWorker() {
        running = true;
        RUNNING = true;
        worker = new Thread(new Runnable() {
            @Override
            public void run() {
                LogStore.log("守护启动：账号=" + Prefs.username(AutoLoginService.this)
                        + "  ac_id=" + Prefs.acId(AutoLoginService.this)
                        + "  间隔=" + Prefs.interval(AutoLoginService.this) + "s");
                while (running) {
                    try {
                        tick();
                    } catch (Throwable t) {
                        LogStore.log("异常: " + t.getClass().getSimpleName() + " " + t.getMessage());
                    }
                    int interval = Math.max(5, Prefs.interval(AutoLoginService.this));
                    long end = System.currentTimeMillis() + interval * 1000L;
                    wake = false;
                    while (running && !wake && System.currentTimeMillis() < end) {
                        try {
                            Thread.sleep(500);
                        } catch (InterruptedException e) {
                            return;
                        }
                    }
                }
            }
        }, "buct-autologin");
        worker.start();
    }

    /** 同一句话 5 分钟内不重复写日志，避免每 15 秒刷屏 */
    private void logThrottled(String msg) {
        long now = System.currentTimeMillis();
        if (msg.equals(lastLogged) && now - lastLoggedAt < 5 * 60 * 1000L) return;
        lastLogged = msg;
        lastLoggedAt = now;
        LogStore.log(msg);
    }

    private boolean hasNetwork() {
        try {
            ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
            if (cm == null) return true;
            if (Build.VERSION.SDK_INT >= 23) {
                Network n = cm.getActiveNetwork();
                if (n == null) return false;
                NetworkCapabilities caps = cm.getNetworkCapabilities(n);
                return caps != null && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
            }
            return cm.getActiveNetworkInfo() != null && cm.getActiveNetworkInfo().isConnected();
        } catch (Throwable t) {
            return true;
        }
    }

    private void tick() {
        if (!Prefs.hasAccount(this)) {
            updateNotification("未配置账号");
            logThrottled("未配置账号，请在 App 里填写账号密码");
            return;
        }
        if (!hasNetwork()) {
            updateNotification("无网络连接，等待中…");
            logThrottled("当前没有可用网络，等待连接…");
            return;
        }
        SrunClient client = new SrunClient(Prefs.portal(this), Prefs.username(this),
                Prefs.password(this), Prefs.acId(this), 9000);
        try {
            SrunClient.Status st = client.status();
            if (st.online) {
                updateNotification(st.toString());
                return;
            }
            LogStore.log("检测到未认证（ip=" + st.clientIp + "），开始登录…");
            SrunClient.LoginResult r = client.login();
            if (r.ok) {
                LogStore.log(r.message);
                updateNotification(r.status != null ? r.status.toString() : "已登录");
            } else {
                LogStore.log(r.message);
                updateNotification("登录失败，稍后重试");
            }
        } catch (Throwable e) {
            String m = "检测失败: " + e.getClass().getSimpleName()
                    + (e.getMessage() == null ? "" : (" " + e.getMessage()));
            updateNotification("网络探测失败");
            logThrottled(m);
        }
    }
}
