package com.chatbox.paperscan;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.File;
import java.util.List;

/** 调试：导出掩膜 + 打印候选四边形打分。 */
public class DevDebug {

    public static void main(String[] args) throws Exception {
        for (String path : args) {
            BufferedImage img = ImageIO.read(new File(path));
            int w = img.getWidth(), h = img.getHeight();
            int[] px = img.getRGB(0, 0, w, h, null, 0, w);
            String name = new File(path).getName();
            System.out.println("==== " + name + "  " + w + "x" + h);

            DocDetect.S s = DocDetect.build(px, w, h);
            byte[] mask = DocDetect.paperMask(s);
            if (mask != null) {
                BufferedImage out = new BufferedImage(s.w, s.h, BufferedImage.TYPE_INT_RGB);
                for (int y = 0; y < s.h; y++) {
                    for (int x = 0; x < s.w; x++) {
                        int i = y * s.w + x;
                        int g = Math.min(255, (int) s.gray[i]) / 2 + 40;
                        boolean m = mask[i] != 0;
                        out.setRGB(x, y, m ? 0xFF2828 : (g << 16) | (g << 8) | g);
                    }
                }
                ImageIO.write(out, "png", new File(new File(path).getParentFile(),
                        name.replaceAll("\\.jpg$", "") + "_mask.png"));
            }

            double frame = (double) s.w * s.h;
            float[] mq = DocDetect.maskQuad(s);
            if (mq != null) {
                float[] rq = DocDetect.refine(s, mq);
                System.out.printf("  mask quad  area=%.2f  score=%.3f  %s%n",
                        Math.abs(DocDetect.shoelace(rq)) / 2 / frame, DocDetect.score(s, mask, rq), fmt(rq));
            } else {
                System.out.println("  mask quad  = null");
            }

            List<float[]> cands = DocDetect.houghQuads(s);
            System.out.println("  hough candidates: " + cands.size());
            int shown = 0;
            float bestSc = 0;
            float[] bestQ = null;
            for (float[] c : cands) {
                float[] rq = DocDetect.refine(s, c);
                float sc = DocDetect.score(s, mask, rq);
                if (sc > bestSc) {
                    bestSc = sc;
                    bestQ = rq;
                }
                if (sc > 0.4f && shown < 6) {
                    System.out.printf("    cand area=%.2f score=%.3f %s%n",
                            Math.abs(DocDetect.shoelace(rq)) / 2 / frame, sc, fmt(rq));
                    shown++;
                }
            }
            float[] pq = DocDetect.projQuad(s);
            if (pq != null) {
                float[] pr = DocDetect.refine(s, pq);
                float psc = DocDetect.score(s, mask, pr);
                System.out.println("  projQuad score=" + String.format("%.3f", psc)
                        + " parts[diff=" + String.format("%.2f", DocDetect.dbgParts[0])
                        + " area=" + String.format("%.2f", DocDetect.dbgParts[1])
                        + " sup=" + String.format("%.2f", DocDetect.dbgParts[2])
                        + " inP=" + String.format("%.2f", DocDetect.dbgParts[3])
                        + " outP=" + String.format("%.2f", DocDetect.dbgParts[5]) + "] " + fmt(pr));
            } else {
                System.out.println("  projQuad = null");
            }
            float[] lq = DocDetect.lineQuad(s, mask);
            if (lq != null) {
                float[] lr = DocDetect.refine(s, lq);
                float lsc = DocDetect.score(s, mask, lr);
                System.out.println("  lineQuad score=" + String.format("%.3f", lsc)
                        + " parts[diff=" + String.format("%.2f", DocDetect.dbgParts[0])
                        + " area=" + String.format("%.2f", DocDetect.dbgParts[1])
                        + " sup=" + String.format("%.2f", DocDetect.dbgParts[2])
                        + " con=" + String.format("%.2f", DocDetect.dbgParts[4])
                        + " out=" + String.format("%.2f", DocDetect.dbgParts[5]) + "] " + fmt(lr));
            } else {
                System.out.println("  lineQuad = null");
            }
            if (mq != null) {
                float[] r2 = DocDetect.refine(s, mq);
                DocDetect.score(s, mask, r2);
                System.out.println("  maskQuad parts[diff=" + String.format("%.2f", DocDetect.dbgParts[0])
                        + " area=" + String.format("%.2f", DocDetect.dbgParts[1])
                        + " sup=" + String.format("%.2f", DocDetect.dbgParts[2])
                        + " con=" + String.format("%.2f", DocDetect.dbgParts[4])
                        + " out=" + String.format("%.2f", DocDetect.dbgParts[5]) + "]");
            }
            if (bestQ != null) {
                System.out.printf("  best hough area=%.2f score=%.3f %s%n",
                        Math.abs(DocDetect.shoelace(bestQ)) / 2 / frame, bestSc, fmt(bestQ));
            }
        }
    }

    static String fmt(float[] q) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 4; i++) sb.append(String.format("(%.0f,%.0f)", q[i * 2], q[i * 2 + 1]));
        return sb.toString();
    }
}
