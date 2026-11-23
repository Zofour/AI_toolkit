package com.chatbox.paperscan;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.File;

/** 小工具：直接看某张图各路候选的分数与几何量。 */
public class DevCheck {

    static byte[] gMask;

    public static void main(String[] args) throws Exception {
        for (String path : args) {
            BufferedImage img = ImageIO.read(new File(path));
            int w = img.getWidth(), h = img.getHeight();
            int[] px = img.getRGB(0, 0, w, h, null, 0, w);
            DocDetect.S s = DocDetect.build(px, w, h);
            byte[] mask = DocDetect.paperMask(s);
            gMask = mask;
            double frame = (double) s.w * s.h;
            System.out.println("==== " + new File(path).getName() + "  small=" + s.w + "x" + s.h);

            float[] pq = DocDetect.projQuad(s);
            report("proj(raw)", s, pq, frame);
            report("proj(refined)", s, DocDetect.refine(s, pq), frame);

            report("mask(raw)", s, DocDetect.maskQuad(s), frame);
            report("line(raw)", s, DocDetect.lineQuad(s, mask), frame);

            float[] d = DocDetect.detect(px, w, h, false);
            System.out.println("  detect() = " + (d == null ? "null" : fmt(d)));
        }
    }

    static void report(String tag, DocDetect.S s, float[] q, double frame) {
        if (q == null) {
            System.out.println("  " + tag + " = null");
            return;
        }
        double area = Math.abs(DocDetect.shoelace(q)) / 2.0 / frame;
        float ew = (float) Math.hypot(q[2] - q[0], q[3] - q[1]);
        float eh = (float) Math.hypot(q[6] - q[0], q[7] - q[1]);
        float sc = DocDetect.score(s, gMask, q, false);
        System.out.println("  " + tag + " area=" + String.format("%.2f", area)
                + " ar=" + String.format("%.2f", ew / eh)
                + " score=" + String.format("%.3f", sc)
                + " [mask=" + String.format("%.2f", DocDetect.dbgParts[1])
                + " diff=" + String.format("%.2f", DocDetect.dbgParts[0])
                + " sup=" + String.format("%.2f", DocDetect.dbgParts[2])
                + " inP=" + String.format("%.2f", DocDetect.dbgParts[3])
                + " outP=" + String.format("%.2f", DocDetect.dbgParts[5]) + "] " + fmt(q));
    }

    static String fmt(float[] q) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 4; i++) sb.append(String.format("(%.0f,%.0f)", q[i * 2], q[i * 2 + 1]));
        return sb.toString();
    }
}
