package com.chatbox.buctwifi;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

/** 主界面：填账号密码 → 一键启动守护 */
public class MainActivity extends Activity {

    private static final int REQ_NOTIF = 101;

    private EditText etUser, etPass, etAcid, etInterval;
    private TextView tvStatus, tvLog, tvPerm;
    private ScrollView scroll;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private String lastLog = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LogStore.init(this);
        buildUi();
        loadPrefs();
        handleIntent(getIntent());
        refreshPermissionText();
        ui.post(refresher);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
    }

    /**
     * 支持外部直接导入配置（方便用 adb / 其他 App 一键配置）：
     * adb shell am start -n com.chatbox.buctwifi/.MainActivity \
     *     --es user 2025000000 --es pass 你的密码 --es acid 20 --es interval 15
     */
    private void handleIntent(Intent it) {
        if (it == null) return;
        String u = it.getStringExtra("user");
        String p = it.getStringExtra("pass");
        String a = it.getStringExtra("acid");
        String iv = it.getStringExtra("interval");
        if (u == null && p == null) return;
        if (u != null) etUser.setText(u);
        if (p != null) etPass.setText(p);
        if (a != null) etAcid.setText(a);
        if (iv != null) etInterval.setText(iv);
        LogStore.log("从外部 Intent 导入配置");
        onSaveAndStart();
    }

    @Override
    protected void onDestroy() {
        ui.removeCallbacks(refresher);
        super.onDestroy();
    }

    // ------------------------------------------------------------------ UI

    private int dp(int v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }

    private TextView label(String s) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextColor(0xFFB8C0CE);
        t.setTextSize(13);
        t.setPadding(0, dp(10), 0, dp(4));
        return t;
    }

    private EditText field(String hint, int inputType) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setTextColor(0xFFEAF0FF);
        e.setHintTextColor(0xFF6B7688);
        e.setTextSize(16);
        e.setInputType(inputType);
        e.setSingleLine(true);
        return e;
    }

    private Button button(String text, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setTextSize(14);
        b.setOnClickListener(l);
        return b;
    }

    private void buildUi() {
        scroll = new ScrollView(this);
        scroll.setBackgroundColor(0xFF12141A);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(18), dp(18), dp(18), dp(24));
        scroll.addView(root, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        TextView title = new TextView(this);
        title.setText("北化校园网 · 自动登录");
        title.setTextColor(0xFFEAF0FF);
        title.setTextSize(22);
        title.setPadding(0, 0, 0, dp(2));
        root.addView(title);

        TextView sub = new TextView(this);
        sub.setText("掉线自动重连 · 开机自启 · 前台常驻");
        sub.setTextColor(0xFF6B7688);
        sub.setTextSize(12);
        sub.setPadding(0, 0, 0, dp(6));
        root.addView(sub);

        tvStatus = new TextView(this);
        tvStatus.setTextColor(0xFF7CE38B);
        tvStatus.setTextSize(14);
        tvStatus.setPadding(dp(10), dp(10), dp(10), dp(10));
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        sp.topMargin = dp(8);
        root.addView(tvStatus, sp);

        root.addView(label("账号（学号）"));
        etUser = field("例如 2025000000", InputType.TYPE_CLASS_TEXT);
        root.addView(etUser);

        root.addView(label("密码"));
        etPass = field("校园网密码", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        root.addView(etPass);

        root.addView(label("ac_id（门户地址里的 ac_id，默认 20）"));
        etAcid = field("20", InputType.TYPE_CLASS_NUMBER);
        root.addView(etAcid);

        root.addView(label("检测间隔（秒，默认 15）"));
        etInterval = field("15", InputType.TYPE_CLASS_NUMBER);
        root.addView(etInterval);

        LinearLayout row1 = new LinearLayout(this);
        row1.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams rp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        rp.topMargin = dp(16);
        Button bStart = button("保存并启动", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                onSaveAndStart();
            }
        });
        Button bStop = button("停止", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                onStopClicked();
            }
        });
        LinearLayout.LayoutParams half = new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        row1.addView(bStart, half);
        row1.addView(bStop, half);
        root.addView(row1, rp);

        LinearLayout row2 = new LinearLayout(this);
        row2.setOrientation(LinearLayout.HORIZONTAL);
        Button bCheck = button("立即检测", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                onCheckNow();
            }
        });
        Button bClear = button("清空日志", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                LogStore.clear();
                lastLog = "";
                refreshLog();
            }
        });
        row2.addView(bCheck, new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        row2.addView(bClear, new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        root.addView(row2);

        root.addView(label("权限（点一下去授权，建议全开）"));
        tvPerm = new TextView(this);
        tvPerm.setTextColor(0xFF9AA6B8);
        tvPerm.setTextSize(12);
        tvPerm.setPadding(0, 0, 0, dp(6));
        root.addView(tvPerm);

        LinearLayout row3 = new LinearLayout(this);
        row3.setOrientation(LinearLayout.HORIZONTAL);
        row3.addView(button("通知", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                requestNotif();
            }
        }), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        row3.addView(button("电池白名单", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                requestIgnoreBattery();
            }
        }), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        row3.addView(button("自启动设置", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                openAutoStart();
            }
        }), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        root.addView(row3);

        root.addView(label("运行日志"));
        tvLog = new TextView(this);
        tvLog.setTextColor(0xFF8FA0B5);
        tvLog.setTextSize(11);
        tvLog.setTypeface(android.graphics.Typeface.MONOSPACE);
        tvLog.setBackgroundColor(0xFF0C0E13);
        tvLog.setPadding(dp(10), dp(10), dp(10), dp(10));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(4);
        root.addView(tvLog, lp);

        setContentView(scroll);
    }

    private void loadPrefs() {
        etUser.setText(Prefs.username(this));
        etPass.setText(Prefs.password(this));
        etAcid.setText(Prefs.acId(this));
        etInterval.setText(String.valueOf(Prefs.interval(this)));
    }

    // ------------------------------------------------------------------ 动作

    private void onSaveAndStart() {
        String user = etUser.getText().toString().trim();
        String pass = etPass.getText().toString();
        String acid = etAcid.getText().toString().trim();
        String ivs = etInterval.getText().toString().trim();
        if (user.isEmpty() || pass.isEmpty()) {
            toast("请先填写账号和密码");
            return;
        }
        int interval = 15;
        try {
            interval = Integer.parseInt(ivs);
        } catch (Exception ignored) {
        }
        if (interval < 5) interval = 5;
        if (interval > 3600) interval = 3600;

        Prefs.save(this, user, pass, acid, interval);
        Prefs.setEnabled(this, true);
        LogStore.log("已保存配置，启动守护");
        startServiceCompat(AutoLoginService.ACTION_START);
        toast("已启动，后台每 " + interval + " 秒检测一次");
    }

    private void onStopClicked() {
        try {
            Intent i = new Intent(this, AutoLoginService.class);
            i.setAction(AutoLoginService.ACTION_STOP);
            startService(i);
        } catch (Throwable t) {
            toast("停止失败: " + t.getMessage());
        }
        Prefs.setEnabled(this, false);
        toast("已停止");
    }

    private void onCheckNow() {
        if (!Prefs.hasAccount(this)) {
            toast("请先保存账号密码");
            return;
        }
        startServiceCompat(AutoLoginService.ACTION_CHECK);
        toast("已触发一次检测");
    }

    private void startServiceCompat(String action) {
        Intent i = new Intent(this, AutoLoginService.class);
        i.setAction(action);
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(i);
        else startService(i);
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    // ------------------------------------------------------------------ 权限

    private void requestNotif() {
        if (Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQ_NOTIF);
                return;
            }
        }
        try {
            Intent i = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS);
            i.putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName());
            startActivity(i);
        } catch (Throwable t) {
            toast("通知已开启");
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        refreshPermissionText();
    }

    private void requestIgnoreBattery() {
        try {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            if (pm != null && pm.isIgnoringBatteryOptimizations(getPackageName())) {
                toast("已在电池白名单内");
            } else {
                Intent i = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                i.setData(Uri.parse("package:" + getPackageName()));
                startActivity(i);
            }
        } catch (Throwable t) {
            try {
                startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
            } catch (Throwable t2) {
                toast("请手动在系统设置里关闭电池优化");
            }
        }
    }

    /** 各家 ROM 的自启动管理页，逐个大；都打不开就退回应用详情页 */
    private void openAutoStart() {
        String[][] targets = new String[][]{
                {"com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity"},
                {"com.huawei.systemmanager", "com.huawei.systemmanager.optimize.process.ProtectActivity"},
                {"com.huawei.systemmanager", "com.huawei.systemmanager.appcontrol.activity.StartupAppControlActivity"},
                {"com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity"},
                {"com.coloros.safecenter", "com.coloros.safecenter.permission.startup.StartupAppListActivity"},
                {"com.coloros.safecenter", "com.coloros.safecenter.startupapp.StartupAppListActivity"},
                {"com.oppo.safe", "com.oppo.safe.permission.startup.StartupAppListActivity"},
                {"com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"},
                {"com.iqoo.secure", "com.iqoo.secure.ui.phoneoptimize.AddWhiteListActivity"},
                {"com.letv.android.letvsafe", "com.letv.android.letvsafe.AutobootManageActivity"},
                {"com.meizu.safe", "com.meizu.safe.permission.SmartBGActivity"}
        };
        for (String[] t : targets) {
            try {
                Intent i = new Intent();
                i.setClassName(t[0], t[1]);
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(i);
                return;
            } catch (Throwable ignored) {
            }
        }
        try {
            Intent i = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
            i.setData(Uri.parse("package:" + getPackageName()));
            startActivity(i);
            toast("请手动允许「自启动 / 后台运行」");
        } catch (Throwable t) {
            toast("请到系统设置里允许自启动");
        }
    }

    private boolean notifGranted() {
        if (Build.VERSION.SDK_INT >= 33) {
            return checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
        }
        return true;
    }

    private void refreshPermissionText() {
        if (tvPerm == null) return;
        boolean batt;
        try {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            batt = pm != null && pm.isIgnoringBatteryOptimizations(getPackageName());
        } catch (Throwable t) {
            batt = false;
        }
        tvPerm.setText("通知：" + (notifGranted() ? "已允许" : "未允许")
                + "　电池白名单：" + (batt ? "已加入" : "未加入")
                + "\n华为/小米等还需在系统里允许「自启动」，否则重启后不会自动运行。");
    }

    // ------------------------------------------------------------------ 刷新

    private void refreshLog() {
        String t = LogStore.text();
        if (t.equals(lastLog)) return;
        lastLog = t;
        String[] lines = t.split("\n");
        StringBuilder sb = new StringBuilder();
        int start = Math.max(0, lines.length - 150);
        for (int i = start; i < lines.length; i++) sb.append(lines[i]).append('\n');
        tvLog.setText(sb.toString());
        if (scroll != null) {
            scroll.post(new Runnable() {
                @Override
                public void run() {
                    scroll.fullScroll(View.FOCUS_DOWN);
                }
            });
        }
    }

    private final Runnable refresher = new Runnable() {
        @Override
        public void run() {
            tvStatus.setText((AutoLoginService.RUNNING ? "● 守护运行中" : "○ 未运行")
                    + "　" + AutoLoginService.LAST_STATUS);
            tvStatus.setTextColor(AutoLoginService.RUNNING ? 0xFF7CE38B : 0xFFE8B45C);
            refreshLog();
            refreshPermissionText();
            ui.postDelayed(this, 1000);
        }
    };
}
