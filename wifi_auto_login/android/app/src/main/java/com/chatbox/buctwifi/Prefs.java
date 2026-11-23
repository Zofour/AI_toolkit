package com.chatbox.buctwifi;

import android.content.Context;
import android.content.SharedPreferences;

/** 配置存取（SharedPreferences） */
public final class Prefs {

    private static final String NAME = "buct_wifi";

    public static final String K_USER = "username";
    public static final String K_PASS = "password";
    public static final String K_ACID = "ac_id";
    public static final String K_INTERVAL = "interval";
    public static final String K_ENABLED = "enabled";
    public static final String K_PORTAL = "portal";

    private Prefs() {
    }

    public static SharedPreferences sp(Context c) {
        return c.getApplicationContext().getSharedPreferences(NAME, Context.MODE_PRIVATE);
    }

    public static String username(Context c) {
        return sp(c).getString(K_USER, "");
    }

    public static String password(Context c) {
        return sp(c).getString(K_PASS, "");
    }

    public static String acId(Context c) {
        return sp(c).getString(K_ACID, "20");
    }

    public static String portal(Context c) {
        return sp(c).getString(K_PORTAL, SrunClient.DEFAULT_PORTAL);
    }

    public static int interval(Context c) {
        return sp(c).getInt(K_INTERVAL, 15);
    }

    public static boolean enabled(Context c) {
        return sp(c).getBoolean(K_ENABLED, false);
    }

    public static void setEnabled(Context c, boolean v) {
        sp(c).edit().putBoolean(K_ENABLED, v).apply();
    }

    public static void save(Context c, String user, String pass, String acid, int interval) {
        sp(c).edit()
                .putString(K_USER, user == null ? "" : user.trim())
                .putString(K_PASS, pass == null ? "" : pass)
                .putString(K_ACID, (acid == null || acid.trim().isEmpty()) ? "20" : acid.trim())
                .putInt(K_INTERVAL, interval)
                .apply();
    }

    public static boolean hasAccount(Context c) {
        return !username(c).isEmpty() && !password(c).isEmpty();
    }
}
