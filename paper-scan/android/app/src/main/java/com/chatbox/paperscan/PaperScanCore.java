package com.chatbox.paperscan;

/**
 * 文档扫描核心：纸张检测 -> 透视矫正 -> 去阴影/白平衡/提亮/锐化。
 *
 * 纯 Java 实现，不引用任何 android.* / 第三方库，
 * 因此可以在 PC 上直接用 javac 编译验证（见 dev/CoreTest.java）。
 */
public final class PaperScanCore {

    public static final class Result {
        public int[] pixels;   // ARGB 输出
        public int width;
        public int height;
        public float[] quad;   // 源图坐标系下的四角 TL,TR,BR,BL；未检出为 null
        public boolean detected;
    }

    private PaperScanCore() {
    }

    /** 完整流程。argb 为源图 ARGB_8888 像素。 */
    public static Result process(int[] argb, int w, int h) {
        Result r = new Result();
        float[] quad = detectQuad(argb, w, h);

        Warped wp = null;
        if (quad != null) {
            wp = warp(argb, w, h, quad);
        }
        if (wp == null) {
            wp = new Warped();
            wp.px = argb.clone();
            wp.w = w;
            wp.h = h;
            r.detected = false;
            r.quad = null;
        } else {
            r.detected = true;
            r.quad = quad;
            // 二次微调：纸已被拉正，在拉正后的图上再找一次边界；
            // 只接受"小幅内收"（面积 0.80~0.97），把检测误差带来的桌面碎边切掉
            float[] q2 = DocDetect.detect(wp.px, wp.w, wp.h, true);
            if (q2 != null) {
                double a2 = Math.abs(DocDetect.shoelace(q2)) / 2.0 / ((double) wp.w * wp.h);
                if (a2 > 0.80 && a2 < 0.996) {
                    Warped w2 = warp(wp.px, wp.w, wp.h, q2);
                    if (w2 != null) wp = w2;
                }
            }
        }
        enhance(wp.px, wp.w, wp.h);
        if (r.detected) {
            wp = snapBorders(wp);
            wp = trimPaperBorder(wp);
        }
        r.pixels = wp.px;
        r.width = wp.w;
        r.height = wp.h;
        return r;
    }

    /**
     * 白边微裁：增强后纸面几乎纯白，若最外圈若干行列的亮度/饱和度跟纸面明显不符
     * （检测误差带来的桌面碎边、阴影条），就切掉，最多各边 3%。
     */
    /**
     * 贴边吸附：拉正后纸边应当是横平竖直的，所以在最外圈 5% 里找梯度最强的那条
     * 水平/垂直线，把边吸附上去（能去掉顶上那条别的本子/桌面残余）。
     */
    private static Warped snapBorders(Warped wp) {
        int w = wp.w, h = wp.h;
        if (w < 40 || h < 40) return wp;
        int limY = Math.max(2, (int) (h * 0.05f));
        int limX = Math.max(2, (int) (w * 0.05f));

        float[] rowG = new float[h];
        float[] colG = new float[w];
        double rowSum = 0, colSum = 0;
        int[] lum = new int[w * h];
        for (int i = 0; i < lum.length; i++) {
            int p = wp.px[i];
            lum[i] = (((p >> 16) & 0xFF) * 77 + ((p >> 8) & 0xFF) * 151 + (p & 0xFF) * 28) >> 8;
        }
        for (int y = 1; y < h; y++) {
            int row = y * w, prev = row - w;
            long sum = 0;
            for (int x = 0; x < w; x++) sum += Math.abs(lum[row + x] - lum[prev + x]);
            rowG[y] = sum / (float) w;
            rowSum += rowG[y];
        }
        for (int x = 1; x < w; x++) {
            long sum = 0;
            for (int y = 0; y < h; y++) sum += Math.abs(lum[y * w + x] - lum[y * w + x - 1]);
            colG[x] = sum / (float) h;
            colSum += colG[x];
        }
        float rowThr = (float) (rowSum / Math.max(1, h - 1)) * 2.2f;
        float colThr = (float) (colSum / Math.max(1, w - 1)) * 2.2f;

        int top = snapIndex(rowG, 1, limY, rowThr);
        int bottom = snapIndex(rowG, h - 1, h - 1 - limY, rowThr);
        int left = snapIndex(colG, 1, limX, colThr);
        int right = snapIndex(colG, w - 1, w - 1 - limX, colThr);

        int y0 = top;
        int y1 = (bottom >= 0 && bottom < h) ? bottom : h;
        int x0 = left;
        int x1 = (right >= 0 && right < w) ? right : w;
        if (y1 - y0 < h * 0.6f || x1 - x0 < w * 0.6f) return wp;
        if (y0 == 0 && x0 == 0 && y1 == h && x1 == w) return wp;

        int nw = x1 - x0, nh = y1 - y0;
        int[] out = new int[nw * nh];
        for (int y = 0; y < nh; y++) {
            System.arraycopy(wp.px, (y + y0) * w + x0, out, y * nw, nw);
        }
        Warped nwp = new Warped();
        nwp.px = out;
        nwp.w = nw;
        nwp.h = nh;
        return nwp;
    }

    /**
     * 在 [from, to]（to 可小于 from）区间里找梯度最大且过阈值的下标；找不到返回原位。
     */
    private static int snapIndex(float[] g, int from, int to, float thr) {
        int step = to >= from ? 1 : -1;
        float best = 0;
        int bestI = -1;
        for (int i = from; i != to + step && i >= 0 && i < g.length; i += step) {
            if (g[i] > best) {
                best = g[i];
                bestI = i;
            }
        }
        if (bestI > 0 && best >= thr) return bestI;
        return from;
    }

    private static Warped trimPaperBorder(Warped wp) {
        int w = wp.w, h = wp.h;
        int maxY = Math.max(2, (int) (h * 0.03f));
        int maxX = Math.max(2, (int) (w * 0.03f));

        float[] rowLum = new float[h];
        float[] rowSat = new float[h];
        float[] colLum = new float[w];
        float[] colSat = new float[w];
        double lumAll = 0, satAll = 0;

        for (int y = 0; y < h; y++) {
            int row = y * w;
            double lum = 0, sat = 0;
            for (int x = 0; x < w; x++) {
                int p = wp.px[row + x];
                int r = (p >> 16) & 0xFF, g = (p >> 8) & 0xFF, b = p & 0xFF;
                int mx = Math.max(r, Math.max(g, b));
                int mn = Math.min(r, Math.min(g, b));
                lum += (r * 77 + g * 151 + b * 28) >> 8;
                sat += mx == 0 ? 0 : (mx - mn) / (float) mx;
            }
            rowLum[y] = (float) (lum / w);
            rowSat[y] = (float) (sat / w);
            lumAll += lum;
            satAll += sat;
        }
        for (int x = 0; x < w; x++) {
            double lum = 0, sat = 0;
            for (int y = 0; y < h; y++) {
                int p = wp.px[y * w + x];
                int r = (p >> 16) & 0xFF, g = (p >> 8) & 0xFF, b = p & 0xFF;
                int mx = Math.max(r, Math.max(g, b));
                int mn = Math.min(r, Math.min(g, b));
                lum += (r * 77 + g * 151 + b * 28) >> 8;
                sat += mx == 0 ? 0 : (mx - mn) / (float) mx;
            }
            colLum[x] = (float) (lum / h);
            colSat[x] = (float) (sat / h);
        }
        float lumAvg = (float) (lumAll / ((double) w * h));
        float satAvg = (float) (satAll / ((double) w * h));

        int top = 0;
        while (top < maxY && bad(rowLum[top], rowSat[top], lumAvg, satAvg)) top++;
        int bottom = 0;
        while (bottom < maxY && bad(rowLum[h - 1 - bottom], rowSat[h - 1 - bottom], lumAvg, satAvg)) bottom++;
        int left = 0;
        while (left < maxX && bad(colLum[left], colSat[left], lumAvg, satAvg)) left++;
        int right = 0;
        while (right < maxX && bad(colLum[w - 1 - right], colSat[w - 1 - right], lumAvg, satAvg)) right++;

        if (top + bottom + left + right == 0) return wp;
        int nw = w - left - right;
        int nh = h - top - bottom;
        if (nw < w * 0.6f || nh < h * 0.6f) return wp;

        int[] out = new int[nw * nh];
        for (int y = 0; y < nh; y++) {
            System.arraycopy(wp.px, (y + top) * w + left, out, y * nw, nw);
        }
        Warped nwp = new Warped();
        nwp.px = out;
        nwp.w = nw;
        nwp.h = nh;
        return nwp;
    }

    /** 该行/列是否明显不像纸面（偏暗或偏色）。 */
    private static boolean bad(float lum, float sat, float lumAvg, float satAvg) {
        return lum < lumAvg - 6f || sat > satAvg + 0.05f;
    }

    /** 用指定四边形直接做矫正 + 增强（手动框选用）。quad 为 null 时整图增强。 */
    public static Result processQuad(int[] argb, int w, int h, float[] quad) {
        Result r = new Result();
        Warped wp = quad == null ? null : warp(argb, w, h, quad);
        if (wp == null) {
            wp = new Warped();
            wp.px = argb.clone();
            wp.w = w;
            wp.h = h;
            r.detected = false;
            r.quad = null;
        } else {
            r.detected = true;
            r.quad = quad;
        }
        enhance(wp.px, wp.w, wp.h);
        if (r.detected) {
            wp = snapBorders(wp);
            wp = trimPaperBorder(wp);
        }
        r.pixels = wp.px;
        r.width = wp.w;
        r.height = wp.h;
        return r;
    }

    /** 不做纸张检测，整图直接增强（手工兑底用）。 */
    public static Result processNoCrop(int[] argb, int w, int h) {
        int[] px = argb.clone();
        enhance(px, w, h);
        Result r = new Result();
        r.pixels = px;
        r.width = w;
        r.height = h;
        r.detected = false;
        r.quad = null;
        return r;
    }

    // =====================================================================
    // 1. 纸张检测（实现见 DocDetect：亮区掩膜 + Hough 直线 + 边缘支持度打分）
    // =====================================================================

    public static float[] detectQuad(int[] argb, int w, int h) {
        return DocDetect.detect(argb, w, h);
    }

    // =====================================================================
    // 2. 透视矫正
    // =====================================================================

    static final class Warped {
        int[] px;
        int w;
        int h;
    }

    private static double[] homography(double[] dst, float[] src) {
        double[][] a = new double[8][9];
        for (int i = 0; i < 4; i++) {
            double X = dst[i * 2], Y = dst[i * 2 + 1];
            double x = src[i * 2], y = src[i * 2 + 1];
            a[2 * i][0] = X; a[2 * i][1] = Y; a[2 * i][2] = 1;
            a[2 * i][6] = -X * x; a[2 * i][7] = -Y * x; a[2 * i][8] = x;
            a[2 * i + 1][3] = X; a[2 * i + 1][4] = Y; a[2 * i + 1][5] = 1;
            a[2 * i + 1][6] = -X * y; a[2 * i + 1][7] = -Y * y; a[2 * i + 1][8] = y;
        }
        for (int c = 0; c < 8; c++) {
            int piv = c;
            double best = Math.abs(a[c][c]);
            for (int r = c + 1; r < 8; r++) {
                double v = Math.abs(a[r][c]);
                if (v > best) { best = v; piv = r; }
            }
            if (best < 1e-12) return null;
            if (piv != c) { double[] t = a[piv]; a[piv] = a[c]; a[c] = t; }
            double pv = a[c][c];
            for (int k = c; k < 9; k++) a[c][k] /= pv;
            for (int r = 0; r < 8; r++) {
                if (r == c) continue;
                double f = a[r][c];
                if (f == 0) continue;
                for (int k = c; k < 9; k++) a[r][k] -= f * a[c][k];
            }
        }
        double[] out = new double[8];
        for (int i = 0; i < 8; i++) out[i] = a[i][8];
        return out;
    }

    private static float dist(float x0, float y0, float x1, float y1) {
        float dx = x1 - x0, dy = y1 - y0;
        return (float) Math.sqrt(dx * dx + dy * dy);
    }

    private static Warped warp(int[] src, int sw, int sh, float[] q) {
        float topLen = dist(q[0], q[1], q[2], q[3]);
        float botLen = dist(q[6], q[7], q[4], q[5]);
        float leftLen = dist(q[0], q[1], q[6], q[7]);
        float rightLen = dist(q[2], q[3], q[4], q[5]);
        float ow = Math.max(topLen, botLen);
        float oh = Math.max(leftLen, rightLen);
        if (ow < 16 || oh < 16) return null;
        float cap = 2400f;
        float scale = Math.min(1f, cap / Math.max(ow, oh));
        int W = Math.max(16, Math.round(ow * scale));
        int H = Math.max(16, Math.round(oh * scale));

        double[] dst = new double[]{0, 0, W, 0, W, H, 0, H};
        double[] hh = homography(dst, q);
        if (hh == null) return null;

        int[] out = new int[W * H];
        for (int y = 0; y < H; y++) {
            double vy = y + 0.5;
            int row = y * W;
            for (int x = 0; x < W; x++) {
                double ux = x + 0.5;
                double den = hh[6] * ux + hh[7] * vy + 1.0;
                if (Math.abs(den) < 1e-9) { out[row + x] = 0xFFFFFFFF; continue; }
                double sx = (hh[0] * ux + hh[1] * vy + hh[2]) / den;
                double sy = (hh[3] * ux + hh[4] * vy + hh[5]) / den;
                out[row + x] = bilinear(src, sw, sh, sx, sy);
            }
        }
        Warped wp = new Warped();
        wp.px = out;
        wp.w = W;
        wp.h = H;
        return wp;
    }

    private static int bilinear(int[] src, int w, int h, double fx, double fy) {
        if (fx < 0) fx = 0;
        if (fy < 0) fy = 0;
        if (fx > w - 1) fx = w - 1;
        if (fy > h - 1) fy = h - 1;
        int x0 = (int) fx, y0 = (int) fy;
        int x1 = x0 + 1 < w ? x0 + 1 : x0;
        int y1 = y0 + 1 < h ? y0 + 1 : y0;
        float ax = (float) (fx - x0), ay = (float) (fy - y0);
        int p00 = src[y0 * w + x0], p10 = src[y0 * w + x1];
        int p01 = src[y1 * w + x0], p11 = src[y1 * w + x1];
        int r = blend((p00 >> 16) & 0xFF, (p10 >> 16) & 0xFF, (p01 >> 16) & 0xFF, (p11 >> 16) & 0xFF, ax, ay);
        int g = blend((p00 >> 8) & 0xFF, (p10 >> 8) & 0xFF, (p01 >> 8) & 0xFF, (p11 >> 8) & 0xFF, ax, ay);
        int b = blend(p00 & 0xFF, p10 & 0xFF, p01 & 0xFF, p11 & 0xFF, ax, ay);
        return 0xFF000000 | (r << 16) | (g << 8) | b;
    }

    private static int blend(int c00, int c10, int c01, int c11, float ax, float ay) {
        float top = c00 + (c10 - c00) * ax;
        float bot = c01 + (c11 - c01) * ax;
        float v = top + (bot - top) * ay;
        int iv = (int) (v + 0.5f);
        return iv < 0 ? 0 : (iv > 255 ? 255 : iv);
    }

    // =====================================================================
    // 3. 增强：去阴影 / 白平衡 / 白化 / 锐化
    // =====================================================================

    public static void enhance(int[] px, int w, int h) {
        int ds = 12;
        int gw = Math.max(2, (w + ds - 1) / ds);
        int gh = Math.max(2, (h + ds - 1) / ds);
        int gn = gw * gh;
        float[] br = new float[gn], bg = new float[gn], bb = new float[gn];
        int[] cnt = new int[gn];

        for (int y = 0; y < h; y++) {
            int gy = y / ds;
            int base = y * w;
            for (int x = 0; x < w; x++) {
                int gi = gy * gw + x / ds;
                int p = px[base + x];
                br[gi] += (p >> 16) & 0xFF;
                bg[gi] += (p >> 8) & 0xFF;
                bb[gi] += p & 0xFF;
                cnt[gi]++;
            }
        }
        for (int i = 0; i < gn; i++) {
            int c = cnt[i] == 0 ? 1 : cnt[i];
            br[i] /= c;
            bg[i] /= c;
            bb[i] /= c;
        }
        // 闭运算：把纸面上的深色字迹"抹掉"，得到纸面亮度版图
        br = morphClose(br, gw, gh, 2);
        bg = morphClose(bg, gw, gh, 2);
        bb = morphClose(bb, gw, gh, 2);
        br = blurSmall(br, gw, gh, 3);
        bg = blurSmall(bg, gw, gh, 3);
        bb = blurSmall(bb, gw, gh, 3);

        // 单一亮度背景（三个通道共用，避免逐通道相除产生彩色伪影）
        float[] bgl = new float[gn];
        float maxL = 1f;
        for (int i = 0; i < gn; i++) {
            bgl[i] = 0.299f * br[i] + 0.587f * bg[i] + 0.114f * bb[i];
            if (bgl[i] > maxL) maxL = bgl[i];
        }

        // 全局白平衡：拿最亮的那批"纸面"格子算通道增益
        float sumR = 0, sumG = 0, sumB = 0;
        int nWB = 0;
        float wbCut = maxL * 0.82f;
        for (int i = 0; i < gn; i++) {
            if (bgl[i] >= wbCut) {
                sumR += br[i];
                sumG += bg[i];
                sumB += bb[i];
                nWB++;
            }
        }
        float gainR = 1f, gainG = 1f, gainB = 1f;
        if (nWB > 4) {
            float mr = sumR / nWB, mg = sumG / nWB, mb = sumB / nWB;
            float target = (mr + mg + mb) / 3f;
            if (mr > 8) gainR = clampF(target / mr, 0.8f, 1.3f);
            if (mg > 8) gainG = clampF(target / mg, 0.8f, 1.3f);
            if (mb > 8) gainB = clampF(target / mb, 0.8f, 1.3f);
        }

        // 色阶曲线：中间调基本保持（保住浅灰细线），只把接近白的背景拉到纯白
        int[] lut = new int[256];
        for (int i = 0; i < 256; i++) {
            double t = i / 255.0;
            double v;
            if (t > 0.88) {
                v = 0.88 + (t - 0.88) * 2.6;
            } else {
                v = Math.pow(t, 1.06) * 0.995;
            }
            if (v > 1.0) v = 1.0;
            lut[i] = (int) Math.round(v * 255);
        }

        for (int y = 0; y < h; y++) {
            float fy = (y + 0.5f) / ds - 0.5f;
            int base = y * w;
            for (int x = 0; x < w; x++) {
                float fx = (x + 0.5f) / ds - 0.5f;
                float el = sampleF(bgl, gw, gh, fx, fy);
                int p = px[base + x];
                int r = (p >> 16) & 0xFF, g = (p >> 8) & 0xFF, b = p & 0xFF;

                float gain = 255f / (el < 25f ? 25f : el);
                if (gain > 5.5f) gain = 5.5f;
                float gr = gain * gainR, gg = gain * gainG, gb = gain * gainB;
                r = lut[clamp255((int) (r * gr + 0.5f))];
                g = lut[clamp255((int) (g * gg + 0.5f))];
                b = lut[clamp255((int) (b * gb + 0.5f))];

                // 越亮的像素越往中性白靠，去掉纸面上的暖/冷色偏
                int lum = (r * 77 + g * 151 + b * 28) >> 8;
                if (lum > 190) {
                    float tt = (lum - 190) / 65f;
                    if (tt > 1f) tt = 1f;
                    float k = tt * 0.85f;
                    r = (int) (r + (lum - r) * k);
                    g = (int) (g + (lum - g) * k);
                    b = (int) (b + (lum - b) * k);
                }
                px[base + x] = 0xFF000000 | (r << 16) | (g << 8) | b;
            }
        }

        sharpen(px, w, h, 0.55f);
        whitenPaper(px, w, h);
    }

    /** 白点归一：把纸面整体亮度拉到 255，越接近白的地方越纯白。 */
    private static void whitenPaper(int[] px, int w, int h) {
        int[] hist = new int[256];
        int n = px.length;
        for (int i = 0; i < n; i++) {
            int p = px[i];
            int r = (p >> 16) & 0xFF, g = (p >> 8) & 0xFF, b = p & 0xFF;
            int lum = (r * 77 + g * 151 + b * 28) >> 8;
            hist[lum]++;
        }
        int need = (int) (n * 0.92);
        int acc = 0, p92 = 255;
        for (int i = 0; i < 256; i++) {
            acc += hist[i];
            if (acc >= need) { p92 = i; break; }
        }
        if (p92 < 120) return;              // 画面里本来就没有亮区，别硬拉
        float f = 255f / Math.max(200, p92);
        if (p92 > 236) f = 1f;              // 已经很白
        if (f > 1.35f) f = 1.35f;
        if (f <= 1.02f) return;
        int[] lut = new int[256];
        for (int i = 0; i < 256; i++) {
            int v = (int) (i * f + 0.5f);
            if (v > 250) v = 255;
            lut[i] = v > 255 ? 255 : v;
        }
        for (int i = 0; i < n; i++) {
            int p = px[i];
            int r = lut[(p >> 16) & 0xFF];
            int g = lut[(p >> 8) & 0xFF];
            int b = lut[p & 0xFF];
            px[i] = 0xFF000000 | (r << 16) | (g << 8) | b;
        }
    }

    private static float clampF(float v, float lo, float hi) {
        return v < lo ? lo : (v > hi ? hi : v);
    }

    private static float sampleF(float[] a, int w, int h, float fx, float fy) {
        if (fx < 0) fx = 0;
        if (fy < 0) fy = 0;
        if (fx > w - 1) fx = w - 1;
        if (fy > h - 1) fy = h - 1;
        int x0 = (int) fx, y0 = (int) fy;
        int x1 = x0 + 1 < w ? x0 + 1 : x0;
        int y1 = y0 + 1 < h ? y0 + 1 : y0;
        float ax = fx - x0, ay = fy - y0;
        float t = a[y0 * w + x0] + (a[y0 * w + x1] - a[y0 * w + x0]) * ax;
        float u = a[y1 * w + x0] + (a[y1 * w + x1] - a[y1 * w + x0]) * ax;
        return t + (u - t) * ay;
    }

    private static float[] morphClose(float[] a, int w, int h, int r) {
        float[] mx = maxFilter(a, w, h, r);
        return minFilter(mx, w, h, r);
    }

    private static float[] maxFilter(float[] a, int w, int h, int r) {
        float[] out = new float[a.length];
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                float v = 0;
                for (int dy = -r; dy <= r; dy++) {
                    int yy = y + dy;
                    if (yy < 0 || yy >= h) continue;
                    int row = yy * w;
                    for (int dx = -r; dx <= r; dx++) {
                        int xx = x + dx;
                        if (xx < 0 || xx >= w) continue;
                        if (a[row + xx] > v) v = a[row + xx];
                    }
                }
                out[y * w + x] = v;
            }
        }
        return out;
    }

    private static float[] minFilter(float[] a, int w, int h, int r) {
        float[] out = new float[a.length];
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                float v = 255;
                for (int dy = -r; dy <= r; dy++) {
                    int yy = y + dy;
                    if (yy < 0 || yy >= h) continue;
                    int row = yy * w;
                    for (int dx = -r; dx <= r; dx++) {
                        int xx = x + dx;
                        if (xx < 0 || xx >= w) continue;
                        if (a[row + xx] < v) v = a[row + xx];
                    }
                }
                out[y * w + x] = v;
            }
        }
        return out;
    }

    private static float[] blurSmall(float[] a, int w, int h, int r) {
        float[] tmp = new float[a.length];
        float[] out = new float[a.length];
        float norm = 1f / (2 * r + 1);
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                float s = 0;
                for (int dx = -r; dx <= r; dx++) {
                    int xx = Math.min(w - 1, Math.max(0, x + dx));
                    s += a[y * w + xx];
                }
                tmp[y * w + x] = s * norm;
            }
        }
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                float s = 0;
                for (int dy = -r; dy <= r; dy++) {
                    int yy = Math.min(h - 1, Math.max(0, y + dy));
                    s += tmp[yy * w + x];
                }
                out[y * w + x] = s * norm;
            }
        }
        return out;
    }

    /** 反锐化掩模，让文字边缘更"实"。 */
    private static void sharpen(int[] px, int w, int h, float amount) {
        int[] tmp = new int[px.length];
        // 横向 [1,2,1]
        for (int y = 0; y < h; y++) {
            int row = y * w;
            for (int x = 0; x < w; x++) {
                int l = row + (x > 0 ? x - 1 : x);
                int r = row + (x < w - 1 ? x + 1 : x);
                int p = px[row + x];
                int pl = px[l], pr = px[r];
                int rr = (((p >> 16) & 0xFF) * 2 + ((pl >> 16) & 0xFF) + ((pr >> 16) & 0xFF)) >> 2;
                int gg = (((p >> 8) & 0xFF) * 2 + ((pl >> 8) & 0xFF) + ((pr >> 8) & 0xFF)) >> 2;
                int bb = ((p & 0xFF) * 2 + (pl & 0xFF) + (pr & 0xFF)) >> 2;
                tmp[row + x] = 0xFF000000 | (rr << 16) | (gg << 8) | bb;
            }
        }
        for (int y = 0; y < h; y++) {
            int row = y * w;
            int up = y > 0 ? row - w : row;
            int dn = y < h - 1 ? row + w : row;
            for (int x = 0; x < w; x++) {
                int c = tmp[row + x];
                int u = tmp[up + x], d = tmp[dn + x];
                int br = (((c >> 16) & 0xFF) * 2 + ((u >> 16) & 0xFF) + ((d >> 16) & 0xFF)) >> 2;
                int bg = (((c >> 8) & 0xFF) * 2 + ((u >> 8) & 0xFF) + ((d >> 8) & 0xFF)) >> 2;
                int bb2 = ((c & 0xFF) * 2 + (u & 0xFF) + (d & 0xFF)) >> 2;

                int p = px[row + x];
                int r = (p >> 16) & 0xFF, g = (p >> 8) & 0xFF, b = p & 0xFF;
                r = clamp255((int) (r + amount * (r - br)));
                g = clamp255((int) (g + amount * (g - bg)));
                b = clamp255((int) (b + amount * (b - bb2)));
                px[row + x] = 0xFF000000 | (r << 16) | (g << 8) | b;
            }
        }
    }

    private static int clamp255(int v) {
        return v < 0 ? 0 : (v > 255 ? 255 : v);
    }
}
