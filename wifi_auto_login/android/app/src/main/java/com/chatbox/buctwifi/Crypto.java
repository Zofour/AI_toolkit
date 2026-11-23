package com.chatbox.buctwifi;

import java.io.UnsupportedEncodingException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/**
 * 与 https://tree.buct.edu.cn Portal.js 完全一致的加密实现：
 *   - 自定义字母表 base64 + XXTEA(带长度字) + md5(token+password) + sha1 校验
 * 其中 str2long / xxtea 的位运算语义按 JS 的 int32 行为移植（Java int 天然 32 位溢出，等价）。
 */
public final class Crypto {

    private static final String STD_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    private static final String CUS_B64 = "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA";
    private static final int DELTA = 0x9E3779B9;

    private Crypto() {
    }

    public static String md5Hex(String s) {
        try {
            MessageDigest md = MessageDigest.getInstance("MD5");
            return toHex(md.digest(s.getBytes("UTF-8")));
        } catch (NoSuchAlgorithmException | UnsupportedEncodingException e) {
            throw new RuntimeException(e);
        }
    }

    public static String sha1Hex(String s) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-1");
            return toHex(md.digest(s.getBytes("UTF-8")));
        } catch (NoSuchAlgorithmException | UnsupportedEncodingException e) {
            throw new RuntimeException(e);
        }
    }

    private static String toHex(byte[] bytes) {
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            int i = b & 0xFF;
            if (i < 16) sb.append('0');
            sb.append(Integer.toHexString(i));
        }
        return sb.toString();
    }

    /** 等价于 Portal.js 的 s(a,b)：每 4 个 UTF-16 码元压进一个 int（低字节） */
    private static int[] str2long(String s, boolean withLen) {
        int c = s.length();
        int words = (c + 3) / 4;
        int[] v = new int[words + (withLen ? 1 : 0)];
        for (int i = 0; i < c; i++) {
            v[i >> 2] |= (s.charAt(i)) << ((i & 3) << 3);
        }
        if (withLen) v[words] = c;
        return v;
    }

    private static byte[] long2bytes(int[] v) {
        byte[] out = new byte[v.length * 4];
        for (int i = 0; i < v.length; i++) {
            int x = v[i];
            out[i * 4] = (byte) (x & 0xFF);
            out[i * 4 + 1] = (byte) ((x >>> 8) & 0xFF);
            out[i * 4 + 2] = (byte) ((x >>> 16) & 0xFF);
            out[i * 4 + 3] = (byte) ((x >>> 24) & 0xFF);
        }
        return out;
    }

    /** XXTEA 加密（srun 变体：密钥不做长度字，数据带长度字） */
    public static byte[] xxteaEncrypt(String data, String key) {
        int[] v = str2long(data, true);
        int[] k = str2long(key, false);
        if (k.length < 4) {
            int[] t = new int[4];
            System.arraycopy(k, 0, t, 0, k.length);
            k = t;
        }
        int n = v.length - 1;
        if (n < 1) return long2bytes(v);

        int z = v[n];
        int y = v[0];
        int d = 0;
        int q = 6 + 52 / (n + 1);
        while (q-- > 0) {
            d += DELTA;
            int e = (d >>> 2) & 3;
            for (int p = 0; p < n; p++) {
                y = v[p + 1];
                int m = (z >>> 5) ^ (y << 2);
                m += (y >>> 3) ^ (z << 4) ^ (d ^ y);
                m += k[(p & 3) ^ e] ^ z;
                z = v[p] = v[p] + m;
            }
            y = v[0];
            int m = (z >>> 5) ^ (y << 2);
            m += (y >>> 3) ^ (z << 4) ^ (d ^ y);
            m += k[(n & 3) ^ e] ^ z;
            z = v[n] = v[n] + m;
        }
        return long2bytes(v);
    }

    /** 标准 base64（自带实现，不依赖 Android，便于桌面 JDK 直接验证） */
    private static String b64Std(byte[] d) {
        StringBuilder sb = new StringBuilder((d.length + 2) / 3 * 4);
        int i = 0;
        for (; i + 2 < d.length; i += 3) {
            int n = ((d[i] & 0xFF) << 16) | ((d[i + 1] & 0xFF) << 8) | (d[i + 2] & 0xFF);
            sb.append(STD_B64.charAt((n >>> 18) & 63));
            sb.append(STD_B64.charAt((n >>> 12) & 63));
            sb.append(STD_B64.charAt((n >>> 6) & 63));
            sb.append(STD_B64.charAt(n & 63));
        }
        int rem = d.length - i;
        if (rem == 1) {
            int n = (d[i] & 0xFF) << 16;
            sb.append(STD_B64.charAt((n >>> 18) & 63));
            sb.append(STD_B64.charAt((n >>> 12) & 63));
            sb.append("==");
        } else if (rem == 2) {
            int n = ((d[i] & 0xFF) << 16) | ((d[i + 1] & 0xFF) << 8);
            sb.append(STD_B64.charAt((n >>> 18) & 63));
            sb.append(STD_B64.charAt((n >>> 12) & 63));
            sb.append(STD_B64.charAt((n >>> 6) & 63));
            sb.append('=');
        }
        return sb.toString();
    }

    /** 标准 base64 → 门户自定义字母表（保留 '=' 填充） */
    public static String b64Custom(byte[] data) {
        String std = b64Std(data);
        StringBuilder sb = new StringBuilder(std.length());
        for (int i = 0; i < std.length(); i++) {
            char ch = std.charAt(i);
            int idx = STD_B64.indexOf(ch);
            sb.append(idx >= 0 ? CUS_B64.charAt(idx) : ch);
        }
        return sb.toString();
    }

    /** info 字段：{SRBX1} + base64( XXTEA(JSON, token) )，字段顺序必须与门户一致 */
    public static String encodeInfo(String username, String password, String ip, String acid, String token) {
        String json = "{\"username\":\"" + esc(username) + "\""
                + ",\"password\":\"" + esc(password) + "\""
                + ",\"ip\":\"" + esc(ip) + "\""
                + ",\"acid\":\"" + esc(acid) + "\""
                + ",\"enc_ver\":\"srun_bx1\"}";
        return "{SRBX1}" + b64Custom(xxteaEncrypt(json, token));
    }

    /** JSON.stringify 等价的最小转义（非 ASCII 原样保留） */
    private static String esc(String s) {
        if (s == null) return "";
        StringBuilder sb = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                case '\b': sb.append("\\b"); break;
                case '\f': sb.append("\\f"); break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        return sb.toString();
    }
}
