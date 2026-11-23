package com.chatbox.buctwifi;

import android.content.Context;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.text.SimpleDateFormat;
import java.util.ArrayDeque;
import java.util.Date;
import java.util.Locale;

/** 内存 + 文件日志（界面显示与排查用） */
public final class LogStore {

    private static final int MAX_LINES = 400;
    private static final ArrayDeque<String> LINES = new ArrayDeque<>();
    private static final SimpleDateFormat TS = new SimpleDateFormat("MM-dd HH:mm:ss", Locale.CHINA);
    private static Context app;

    private LogStore() {
    }

    public static void init(Context c) {
        if (app == null && c != null) app = c.getApplicationContext();
    }

    public static synchronized void log(String msg) {
        String line = TS.format(new Date()) + "  " + msg;
        LINES.addLast(line);
        while (LINES.size() > MAX_LINES) LINES.removeFirst();
        if (app != null) {
            try {
                File f = new File(app.getFilesDir(), "autologin.log");
                if (f.length() > 512 * 1024) {
                    File old = new File(app.getFilesDir(), "autologin.old.log");
                    if (old.exists()) old.delete();
                    f.renameTo(old);
                }
                FileOutputStream fos = new FileOutputStream(f, true);
                OutputStreamWriter w = new OutputStreamWriter(fos, "UTF-8");
                w.write(line + "\n");
                w.close();
            } catch (Throwable ignored) {
            }
        }
    }

    public static synchronized String text() {
        StringBuilder sb = new StringBuilder();
        for (String s : LINES) sb.append(s).append('\n');
        return sb.toString();
    }

    public static synchronized void clear() {
        LINES.clear();
    }
}
