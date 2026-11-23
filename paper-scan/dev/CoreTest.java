import com.chatbox.paperscan.PaperScanCore;

import javax.imageio.ImageIO;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.File;

/** PC 端验证：读测试照片 -> 跑核心 -> 输出结果与对比图。 */
public class CoreTest {

    public static void main(String[] args) throws Exception {
        File dir = new File(args.length > 0 ? args[0] : "C:/chatbox_temp/paper-scan/dev/testdata");
        File outDir = new File(dir, "out");
        outDir.mkdirs();
        File[] files = dir.listFiles((d, n) -> n.toLowerCase().endsWith(".jpg"));
        if (files == null || files.length == 0) {
            System.out.println("no test images");
            return;
        }
        java.util.Arrays.sort(files);
        for (File f : files) {
            BufferedImage src = ImageIO.read(f);
            int w = src.getWidth(), h = src.getHeight();
            int[] px = src.getRGB(0, 0, w, h, null, 0, w);

            long t0 = System.nanoTime();
            PaperScanCore.Result r = PaperScanCore.process(px, w, h);
            long ms = (System.nanoTime() - t0) / 1_000_000;

            StringBuilder sb = new StringBuilder();
            sb.append(f.getName()).append("  ").append(w).append("x").append(h)
              .append(" -> ").append(r.width).append("x").append(r.height)
              .append("  detected=").append(r.detected)
              .append("  ").append(ms).append("ms");
            if (r.quad != null) {
                sb.append("  quad=");
                for (int i = 0; i < 4; i++) {
                    sb.append(String.format("(%.0f,%.0f)", r.quad[i * 2], r.quad[i * 2 + 1]));
                }
            }
            System.out.println(sb);

            BufferedImage out = new BufferedImage(r.width, r.height, BufferedImage.TYPE_INT_RGB);
            out.setRGB(0, 0, r.width, r.height, r.pixels, 0, r.width);

            // 调试图：在源图上画出检测到的四边形
            BufferedImage quadImg = scale(src, 900);
            float k = quadImg.getWidth() / (float) w;
            if (r.quad != null) {
                Graphics2D g2 = quadImg.createGraphics();
                g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
                g2.setColor(new java.awt.Color(255, 40, 40));
                g2.setStroke(new java.awt.BasicStroke(4f));
                for (int i = 0; i < 4; i++) {
                    int j = (i + 1) % 4;
                    g2.drawLine(Math.round(r.quad[i * 2] * k), Math.round(r.quad[i * 2 + 1] * k),
                            Math.round(r.quad[j * 2] * k), Math.round(r.quad[j * 2 + 1] * k));
                }
                g2.dispose();
            }


            // 对比图：原图（缩到 560 宽）+ 结果（缩到 560 宽）并排
            BufferedImage cmp = sideBySide(src, out, 620);
            String base = f.getName().replaceAll("\\.jpg$", "");
            ImageIO.write(out, "jpg", new File(outDir, base + "_out.jpg"));
            ImageIO.write(cmp, "jpg", new File(outDir, base + "_cmp.jpg"));
            ImageIO.write(quadImg, "jpg", new File(outDir, base + "_quad.jpg"));
        }
        System.out.println("done -> " + outDir.getAbsolutePath());
    }

    static BufferedImage sideBySide(BufferedImage a, BufferedImage b, int targetW) {
        BufferedImage sa = scale(a, targetW);
        BufferedImage sb = scaleToHeight(b, (int) (sa.getHeight() * 1.0));
        int h = Math.max(sa.getHeight(), sb.getHeight());
        BufferedImage cmp = new BufferedImage(sa.getWidth() + sb.getWidth() + 12, h, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = cmp.createGraphics();
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR);
        g.setColor(new java.awt.Color(240, 60, 60));
        g.fillRect(0, 0, cmp.getWidth(), h);
        g.drawImage(sa, 0, 0, null);
        g.drawImage(sb, sa.getWidth() + 12, 0, null);
        g.dispose();
        return cmp;
    }

    static BufferedImage scale(BufferedImage src, int w) {
        int h = Math.max(1, (int) Math.round(src.getHeight() * (w / (double) src.getWidth())));
        BufferedImage d = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = d.createGraphics();
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR);
        g.drawImage(src, 0, 0, w, h, null);
        g.dispose();
        return d;
    }

    static BufferedImage scaleToHeight(BufferedImage src, int h) {
        int w = Math.max(1, (int) Math.round(src.getWidth() * (h / (double) src.getHeight())));
        BufferedImage d = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = d.createGraphics();
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR);
        g.drawImage(src, 0, 0, w, h, null);
        g.dispose();
        return d;
    }
}
