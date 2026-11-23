package com.chatbox.aigenstudio;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.text.InputType;
import android.view.Gravity;
import android.view.ViewGroup;
import android.view.Window;
import android.webkit.DownloadListener;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;

public class MainActivity extends Activity {

    private static final String PREFS = "aigen";
    private static final String KEY_URL = "server_url";
    private static final String DEFAULT_URL = "http://100.64.0.1:8848";
    private static final String SAVE_SCHEME = "aigensave";
    private static final String SAVE_DIR = "电脑";
    private static final int REQ_FILE = 1001;
    private static final int REQ_WRITE = 1003;

    private WebView web;
    private TextView status;
    private SharedPreferences prefs;
    private ValueCallback<Uri[]> fileCallback;
    private Uri cameraUri;
    private String serverUrl;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        buildUi();
        serverUrl = prefs.getString(KEY_URL, "");
        if (serverUrl == null || serverUrl.isEmpty()) {
            askUrl(true);
        } else {
            loadServer(false);
        }
        if (Build.VERSION.SDK_INT < 29
                && checkSelfPermission(android.Manifest.permission.WRITE_EXTERNAL_STORAGE)
                   != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{android.Manifest.permission.WRITE_EXTERNAL_STORAGE}, REQ_WRITE);
        }
    }

    // ------------------------------------------------------------ UI
    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#12141A"));

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(Color.parseColor("#1B1E27"));
        bar.setPadding(dp(8), 0, dp(2), 0);

        status = new TextView(this);
        status.setTextColor(Color.parseColor("#8B93A7"));
        status.setTextSize(10);
        status.setSingleLine(true);
        status.setText("未连接");
        bar.addView(status, new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        Button gear = new Button(this);
        gear.setText("⚙ 菜单");
        gear.setTextSize(11);
        gear.setAllCaps(false);
        gear.setMinWidth(0);
        gear.setMinimumWidth(0);
        gear.setBackgroundColor(Color.TRANSPARENT);
        gear.setTextColor(Color.parseColor("#E6E9F2"));
        gear.setOnClickListener(v -> menu());
        bar.addView(gear, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, dp(28)));

        root.addView(bar, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(28)));

        web = new WebView(this);
        root.addView(web, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(root);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setUserAgentString(s.getUserAgentString() + " AIGenStudioApp/1.0");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                return handleUrl(r.getUrl().toString());
            }

            @Override
            @SuppressWarnings("deprecation")
            public boolean shouldOverrideUrlLoading(WebView v, String url) {
                return handleUrl(url);
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                status.setText("● " + hostOf(url) + (web.canGoBack() ? "  ·  可后退" : ""));
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb,
                                             FileChooserParams params) {
                if (fileCallback != null) {
                    fileCallback.onReceiveValue(null);
                }
                fileCallback = cb;
                cameraUri = null;

                Intent gallery = new Intent(Intent.ACTION_GET_CONTENT);
                gallery.setType("image/*");
                gallery.addCategory(Intent.CATEGORY_OPENABLE);
                Intent chooser = Intent.createChooser(gallery, "选择图片");

                try {
                    Intent capture = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                    ContentValues cv = new ContentValues();
                    cv.put(MediaStore.Images.Media.DISPLAY_NAME,
                            "aigen_" + System.currentTimeMillis() + ".jpg");
                    cv.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
                    cameraUri = getContentResolver()
                            .insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cv);
                    if (cameraUri != null) {
                        capture.putExtra(MediaStore.EXTRA_OUTPUT, cameraUri);
                        chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{capture});
                    }
                } catch (Exception ignore) {
                    cameraUri = null;
                }
                try {
                    startActivityForResult(chooser, REQ_FILE);
                } catch (Exception e) {
                    if (fileCallback != null) {
                        fileCallback.onReceiveValue(null);
                        fileCallback = null;
                    }
                    toast("打不开选择器: " + e.getMessage());
                }
                return true;
            }
        });

        // 兜底：页面里若用 <a download> 也能接住
        web.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String ua, String cd, String mime, long len) {
                String name;
                if (url.contains("/__aigendownload")) {
                    name = safeName(Uri.parse(url).getQueryParameter("name"));
                } else {
                    name = guessName(url, cd);
                }
                saveRemote(url, name, mime);
            }
        });
    }

    private String baseUrl() {
        return serverUrl.endsWith("/")
                ? serverUrl.substring(0, serverUrl.length() - 1) : serverUrl;
    }

    private String hostOf(String url) {
        try {
            String a = Uri.parse(url).getAuthority();
            return a == null ? url : a;
        } catch (Exception e) {
            return url;
        }
    }

    // ------------------------------------------------------------ 链接
    private boolean handleUrl(String url) {
        if (url == null) {
            return false;
        }
        if (url.contains("/__aigendownload")) {
            Uri u = Uri.parse(url);
            String name = u.getQueryParameter("name");
            if (name == null || name.isEmpty()) {
                toast("文件名缺失");
                return true;
            }
            try {
                String du = baseUrl() + "/api/tempfile?name="
                        + URLEncoder.encode(name, "UTF-8");
                saveRemote(du, safeName(name), "image/png");
            } catch (Exception e) {
                toast("保存失败: " + e.getMessage());
            }
            return true;
        }
        if (url.startsWith(SAVE_SCHEME + "://")) {
            Uri u = Uri.parse(url);
            String name = u.getQueryParameter("name");
            if (name == null || name.isEmpty()) {
                toast("文件名缺失");
                return true;
            }
            String base = serverUrl.endsWith("/")
                    ? serverUrl.substring(0, serverUrl.length() - 1) : serverUrl;
            try {
                String du = base + "/api/tempfile?name=" + URLEncoder.encode(name, "UTF-8");
                saveRemote(du, safeName(name), "image/png");
            } catch (Exception e) {
                toast("保存失败: " + e.getMessage());
            }
            return true;
        }
        if (url.startsWith("http://") || url.startsWith("https://")) {
            return false; // 留在 WebView 里
        }
        // 其它 scheme（电话/邮件等）交给系统
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Exception ignore) {
        }
        return true;
    }

    // ------------------------------------------------------------ 保存到手机
    private String safeName(String name) {
        String n = name == null ? "image.png" : name;
        n = n.replace("/", "_").replace("\\", "_").replace(":", "_");
        if (n.length() > 120) {
            int dot = n.lastIndexOf('.');
            if (dot > 0) {
                n = n.substring(0, 100) + n.substring(dot);
            } else {
                n = n.substring(0, 120);
            }
        }
        return n;
    }

    private String guessName(String url, String contentDisposition) {
        if (contentDisposition != null) {
            int i = contentDisposition.indexOf("filename*=");
            if (i >= 0) {
                String v = contentDisposition.substring(i + 10).trim();
                int q = v.indexOf("''");
                if (q >= 0) {
                    v = v.substring(q + 2);
                }
                v = v.replace("\"", "").trim();
                try {
                    v = java.net.URLDecoder.decode(v, "UTF-8");
                } catch (Exception ignore) {
                }
                if (!v.isEmpty()) {
                    return safeName(v);
                }
            }
            i = contentDisposition.indexOf("filename=");
            if (i >= 0) {
                String v = contentDisposition.substring(i + 9).replace("\"", "").trim();
                if (!v.isEmpty()) {
                    return safeName(v);
                }
            }
        }
        try {
            String path = Uri.parse(url).getPath();
            if (path != null && path.contains("/")) {
                return safeName(path.substring(path.lastIndexOf('/') + 1));
            }
        } catch (Exception ignore) {
        }
        return "aigen_" + System.currentTimeMillis() + ".png";
    }

    private void saveRemote(final String url, final String filename, final String mime) {
        toast("正在保存到 相册/" + SAVE_DIR + " …");
        new Thread(() -> {
            HttpURLConnection c = null;
            InputStream in = null;
            try {
                c = (HttpURLConnection) new URL(url).openConnection();
                c.setConnectTimeout(15000);
                c.setReadTimeout(180000);
                c.connect();
                in = c.getInputStream();

                ContentValues cv = new ContentValues();
                cv.put(MediaStore.MediaColumns.DISPLAY_NAME, filename);
                cv.put(MediaStore.MediaColumns.MIME_TYPE,
                        (mime == null || mime.isEmpty()) ? "image/png" : mime);

                Uri out;
                if (Build.VERSION.SDK_INT >= 29) {
                    cv.put(MediaStore.MediaColumns.RELATIVE_PATH, "Pictures/" + SAVE_DIR);
                    out = getContentResolver()
                            .insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cv);
                } else {
                    File dir = new File(Environment
                            .getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES),
                            SAVE_DIR);
                    if (!dir.exists()) {
                        dir.mkdirs();
                    }
                    cv.put(MediaStore.MediaColumns.DATA, new File(dir, filename).getAbsolutePath());
                    out = getContentResolver()
                            .insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cv);
                }
                if (out == null) {
                    throw new Exception("写入相册失败");
                }
                OutputStream os = getContentResolver().openOutputStream(out);
                byte[] buf = new byte[16384];
                int n;
                long total = 0;
                while ((n = in.read(buf)) > 0) {
                    os.write(buf, 0, n);
                    total += n;
                }
                os.flush();
                os.close();
                in.close();
                final long t = total;
                runOnUiThread(() -> toast("已保存 " + filename + "（" + (t / 1024) + " KB）"));
            } catch (Exception e) {
                runOnUiThread(() -> toast("保存失败: " + e));
            } finally {
                try {
                    if (c != null) {
                        c.disconnect();
                    }
                } catch (Exception ignore) {
                }
            }
        }).start();
    }

    // ------------------------------------------------------------ 菜单 / 地址
    private void menu() {
        final String[] items = {"重新设置电脑地址", "清缓存并重新加载", "返回上一页", "当前地址: " + serverUrl};
        new AlertDialog.Builder(this)
                .setTitle("菜单")
                .setItems(items, (d, i) -> {
                    if (i == 0) {
                        askUrl(false);
                    } else if (i == 1) {
                        web.clearCache(true);
                        loadServer(false);
                    } else if (i == 2) {
                        if (web.canGoBack()) {
                            web.goBack();
                        } else {
                            toast("没有上一页了");
                        }
                    }
                })
                .show();
    }

    private void askUrl(final boolean firstRun) {
        final EditText et = new EditText(this);
        et.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        et.setText((serverUrl == null || serverUrl.isEmpty()) ? DEFAULT_URL : serverUrl);
        et.setSelectAllOnFocus(true);
        et.setPadding(dp(12), dp(8), dp(12), dp(8));
        LinearLayout wrap = new LinearLayout(this);
        wrap.setPadding(dp(16), dp(4), dp(16), 0);
        wrap.addView(et, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        AlertDialog.Builder b = new AlertDialog.Builder(this)
                .setTitle(firstRun ? "设置电脑地址" : "修改电脑地址")
                .setMessage("填电脑上『AI Gen Studio 远程.bat』启动后打印的地址，例如 " + DEFAULT_URL)
                .setView(wrap)
                .setCancelable(!firstRun)
                .setPositiveButton("保存并连接", (d, w) -> {
                    String v = et.getText().toString().trim();
                    if (!v.startsWith("http")) {
                        v = "http://" + v;
                    }
                    while (v.endsWith("/")) {
                        v = v.substring(0, v.length() - 1);
                    }
                    serverUrl = v;
                    prefs.edit().putString(KEY_URL, v).apply();
                    loadServer(false);
                });
        if (!firstRun) {
            b.setNegativeButton("取消", null);
        }
        b.show();
    }

    private void loadServer(boolean clearCache) {
        if (clearCache) {
            web.clearCache(true);
        }
        String u = serverUrl.contains("?") ? serverUrl + "&app=1" : serverUrl + "?app=1";
        status.setText("● " + hostOf(serverUrl) + "  连接中…");
        web.loadUrl(u);
    }

    private void toast(String m) {
        runOnUiThread(() -> Toast.makeText(this, m, Toast.LENGTH_SHORT).show());
    }

    // ------------------------------------------------------------ 生命周期
    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == REQ_FILE) {
            Uri[] out = null;
            if (resultCode == RESULT_OK) {
                if (data != null && data.getData() != null) {
                    out = new Uri[]{data.getData()};
                } else if (cameraUri != null) {
                    out = new Uri[]{cameraUri};
                }
            } else if (cameraUri != null) {
                try {
                    getContentResolver().delete(cameraUri, null, null);
                } catch (Exception ignore) {
                }
            }
            cameraUri = null;
            if (fileCallback != null) {
                fileCallback.onReceiveValue(out);
                fileCallback = null;
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.destroy();
        }
        super.onDestroy();
    }
}
