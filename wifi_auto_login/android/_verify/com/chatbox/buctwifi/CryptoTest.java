package com.chatbox.buctwifi;

/** 桌面 JDK 校验：与门户 Portal.js / Python 版逐字节对齐 */
public class CryptoTest {
    public static void main(String[] args) {
        String token = "e3ae3733b4f01dcbcbf7d46e0d90be06cca99b72703648567eec4aa60ca5c103";
        String[][] cases = {
                {"2025000000", "Test@123", "10.0.0.1", "20"},
                {"2025000000", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "10.0.0.1", "20"},
                {"2025000000", "p@ss w/ 中文&符号", "10.0.0.1", "20"},
        };
        for (String[] c : cases) {
            String info = Crypto.encodeInfo(c[0], c[1], c[2], c[3], token);
            String hmd5 = Crypto.md5Hex(token + c[1]);
            String chk = token + c[0] + token + hmd5 + token + c[3] + token + c[2]
                    + token + "200" + token + "1" + token + info;
            String chksum = Crypto.sha1Hex(chk);
            System.out.println("PW=" + c[1]);
            System.out.println("  info=" + info);
            System.out.println("  hmd5=" + hmd5);
            System.out.println("  chksum=" + chksum);
        }
    }
}
