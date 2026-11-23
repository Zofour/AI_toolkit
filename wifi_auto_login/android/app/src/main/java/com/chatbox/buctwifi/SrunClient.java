package com.chatbox.buctwifi;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.security.cert.X509Certificate;

import javax.net.ssl.HostnameVerifier;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSession;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/** 深澜 srun 认证客户端（与桌面板 srun_autologin.py 同一套协议） */
public class SrunClient {

    public static final String DEFAULT_PORTAL = "https://tree.buct.edu.cn";
    public static final String FALLBACK_IP = "202.4.0.1";

    private static final String UA =
            "Mozilla/5.0 (Linux; Android 12; ALN-AL00) AppleWebKit/537.36 (KHTML, like Gecko) "
                    + "Chrome/126.0.0.0 Mobile Safari/537.36";

    public static class Status {
        public boolean online;
        public String error = "";
        public String clientIp = "";
        public String onlineIp = "";
        public String userName = "";
        public String productsName = "";
        public long bytes;

        @Override
        public String toString() {
            if (online) {
                return "在线  " + userName + "  IP=" + onlineIp + "  已用=" + (bytes / 1048576L) + " MB";
            }
            return "未认证  (" + error + ")  IP=" + clientIp;
        }
    }

    public static class LoginResult {
        public boolean ok;
        public String message = "";
        public Status status;
    }

    private final String portal;
    private final String username;
    private final String password;
    private final String acId;
    private final int timeoutMs;

    public SrunClient(String portal, String username, String password, String acId, int timeoutMs) {
        String p = (portal == null || portal.trim().isEmpty()) ? DEFAULT_PORTAL : portal.trim();
        while (p.endsWith("/")) p = p.substring(0, p.length() - 1);
        this.portal = p;
        this.username = username == null ? "" : username.trim();
        this.password = password == null ? "" : password;
        this.acId = (acId == null || acId.trim().isEmpty()) ? "20" : acId.trim();
        this.timeoutMs = timeoutMs <= 0 ? 8000 : timeoutMs;
    }

    // ------------------------------------------------------------------ HTTP

    private String httpGet(String url) throws IOException {
        try {
            return rawGet(url, false);
        } catch (java.net.UnknownHostException e) {
            String alt = url.replaceFirst("^https?://[^/]+", "https://" + FALLBACK_IP);
            return rawGet(alt, true);
        }
    }

    private String rawGet(String urlStr, boolean insecure) throws IOException {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(urlStr).openConnection();
            c.setConnectTimeout(timeoutMs);
            c.setReadTimeout(timeoutMs);
            c.setInstanceFollowRedirects(true);
            c.setRequestProperty("User-Agent", UA);
            c.setRequestProperty("Accept", "*/*");
            c.setRequestProperty("Referer", portal + "/srun_portal_pc?ac_id=" + acId + "&theme=pro");
            if (insecure && c instanceof HttpsURLConnection) {
                HttpsURLConnection h = (HttpsURLConnection) c;
                h.setSSLSocketFactory(trustAllContext().getSocketFactory());
                h.setHostnameVerifier(new HostnameVerifier() {
                    @Override
                    public boolean verify(String hostname, SSLSession session) {
                        return true;
                    }
                });
            }
            int code = c.getResponseCode();
            InputStream is = (code >= 400) ? c.getErrorStream() : c.getInputStream();
            if (is == null) return "";
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = is.read(buf)) > 0) bos.write(buf, 0, n);
            is.close();
            return new String(bos.toByteArray(), "UTF-8");
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private static SSLContext sTrustAll;

    private static synchronized SSLContext trustAllContext() {
        if (sTrustAll == null) {
            try {
                TrustManager[] tm = new TrustManager[]{new X509TrustManager() {
                    @Override
                    public void checkClientTrusted(X509Certificate[] chain, String authType) {
                    }

                    @Override
                    public void checkServerTrusted(X509Certificate[] chain, String authType) {
                    }

                    @Override
                    public X509Certificate[] getAcceptedIssuers() {
                        return new X509Certificate[0];
                    }
                }};
                SSLContext ctx = SSLContext.getInstance("TLS");
                ctx.init(null, tm, new java.security.SecureRandom());
                sTrustAll = ctx;
            } catch (Exception e) {
                throw new RuntimeException(e);
            }
        }
        return sTrustAll;
    }

    private static JSONObject parseJsonp(String text) {
        if (text == null) return null;
        String t = text.trim();
        if (!t.startsWith("{")) {
            int i = t.indexOf('(');
            int j = t.lastIndexOf(')');
            if (i >= 0 && j > i) t = t.substring(i + 1, j).trim();
        }
        if (!t.startsWith("{")) return null;
        try {
            return new JSONObject(t);
        } catch (Exception e) {
            return null;
        }
    }

    private static String enc(String s) {
        try {
            return URLEncoder.encode(s == null ? "" : s, "UTF-8");
        } catch (Exception e) {
            return "";
        }
    }

    // ------------------------------------------------------------------ API

    public Status status() throws IOException {
        long ts = System.currentTimeMillis();
        String url = portal + "/cgi-bin/rad_user_info?callback=jsonp_" + ts + "&_=" + ts;
        String body = httpGet(url);
        Status s = new Status();
        JSONObject o = parseJsonp(body);
        if (o == null) {
            s.error = "状态响应无法解析";
            return s;
        }
        s.online = "ok".equals(o.optString("error"));
        s.error = o.optString("error");
        s.clientIp = o.optString("client_ip", "");
        s.onlineIp = o.optString("online_ip", "");
        s.userName = o.optString("user_name", "");
        s.productsName = o.optString("products_name", "");
        s.bytes = o.optLong("all_bytes", 0L);
        return s;
    }

    public LoginResult login() {
        LoginResult r = new LoginResult();
        if (username.isEmpty() || password.isEmpty()) {
            r.message = "账号或密码未填写";
            return r;
        }
        try {
            Status st = status();
            r.status = st;
            if (st.online) {
                r.ok = true;
                r.message = "已在线，无需登录";
                return r;
            }
            String ip = st.clientIp == null ? "" : st.clientIp;
            long ts = System.currentTimeMillis();
            String chUrl = portal + "/cgi-bin/get_challenge?callback=jsonp_" + ts
                    + "&username=" + enc(username) + "&ip=" + enc(ip) + "&_=" + ts;
            JSONObject ch = parseJsonp(httpGet(chUrl));
            if (ch == null) {
                r.message = "获取 token 失败（响应无法解析）";
                return r;
            }
            String token = ch.optString("challenge", "");
            if (token.isEmpty()) {
                r.message = "获取 token 失败：" + ch.optString("error_msg", ch.optString("error", "unknown"));
                return r;
            }
            if (ip.isEmpty()) ip = ch.optString("client_ip", "");

            String hmd5 = Crypto.md5Hex(token + password);
            String info = Crypto.encodeInfo(username, password, ip, acId, token);
            String chk = token + username
                    + token + hmd5
                    + token + acId
                    + token + ip
                    + token + "200"
                    + token + "1"
                    + token + info;
            String chksum = Crypto.sha1Hex(chk);

            long ts2 = System.currentTimeMillis();
            String loginUrl = portal + "/cgi-bin/srun_portal?callback=jsonp_" + ts2
                    + "&action=login"
                    + "&username=" + enc(username)
                    + "&password=" + enc("{MD5}" + hmd5)
                    + "&os=" + enc("Android 12")
                    + "&name=" + enc("Android")
                    + "&double_stack=0"
                    + "&chksum=" + enc(chksum)
                    + "&info=" + enc(info)
                    + "&ac_id=" + enc(acId)
                    + "&ip=" + enc(ip)
                    + "&n=200&type=1&_=" + ts2;

            JSONObject resp = parseJsonp(httpGet(loginUrl));
            if (resp == null) {
                r.message = "登录响应无法解析";
                return r;
            }
            String err = resp.optString("error", "");
            String suc = resp.optString("suc_msg", "");
            String emsg = resp.optString("error_msg", "");
            if ("ok".equals(err) || "login_ok".equals(suc) || "ip_already_online_error".equals(suc)
                    || "ip_already_online_error".equals(emsg)) {
                r.ok = true;
                r.message = "登录成功 (ip=" + ip + ")";
                try {
                    r.status = status();
                } catch (IOException ignored) {
                }
                return r;
            }
            r.ok = false;
            r.message = "登录失败: " + (emsg.isEmpty() ? (err.isEmpty() ? resp.toString() : err) : emsg);
            return r;
        } catch (Exception e) {
            r.ok = false;
            r.message = "异常: " + e.getClass().getSimpleName() + " " + e.getMessage();
            return r;
        }
    }

    public LoginResult logout() {
        LoginResult r = new LoginResult();
        try {
            Status st = status();
            long ts = System.currentTimeMillis() / 1000;
            String sign = Crypto.sha1Hex(ts + username + st.clientIp + "" + ts);
            String url = portal + "/cgi-bin/srun_portal?callback=jsonp_" + ts
                    + "&action=logout&username=" + enc(username)
                    + "&ip=" + enc(st.clientIp)
                    + "&ac_id=" + enc(acId)
                    + "&time=" + ts
                    + "&sign=" + sign
                    + "&_=" + System.currentTimeMillis();
            JSONObject resp = parseJsonp(httpGet(url));
            r.ok = resp != null && "ok".equals(resp.optString("error"));
            r.message = r.ok ? "已注销" : "注销失败: " + (resp == null ? "无响应" : resp.optString("error"));
            return r;
        } catch (Exception e) {
            r.message = "注销异常: " + e.getMessage();
            return r;
        }
    }
}
