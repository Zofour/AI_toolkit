package com.chatbox.buctwifi;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

/** 开机自启：收到开机/应用更新广播后自动拉起前台服务 */
public class BootReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        try {
            LogStore.init(context);
            String action = intent == null ? "" : String.valueOf(intent.getAction());
            if (!Prefs.enabled(context)) {
                return;
            }
            Intent svc = new Intent(context, AutoLoginService.class);
            svc.setAction(AutoLoginService.ACTION_START);
            if (Build.VERSION.SDK_INT >= 26) {
                context.startForegroundService(svc);
            } else {
                context.startService(svc);
            }
            LogStore.log("开机自启：已拉起守护（" + action + "）");
        } catch (Throwable t) {
            LogStore.log("开机自启失败: " + t);
        }
    }
}
