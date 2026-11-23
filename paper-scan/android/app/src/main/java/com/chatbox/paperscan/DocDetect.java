package com.chatbox.paperscan;

import java.util.ArrayList;
import java.util.List;

/**
 * 纸张四边形检测：两路候选 + 统一打分。
 *
 * 路 A：亮区掩膜（亮度 + 低饱和 → Otsu → 闭开运算 → 最大连通域 → 凸包 → 最大面积四边形）。
 *       对"纸比背景亮很多"的场景很准。
 * 路 B：Hough 直线。先找画面里的强直线，把"两对近似平行线"交成四边形。
 *       对"纸和桌面亮度接近、但纸边是很直的线"的真实拍照更可靠（这正是手机拍作业纸的典型情况）。
 *
 * 每条候选都要过 score()：沿四条边的梯度支持度、内部"白纸占比"、内外亮度差。
 * 分数不够就返回 null —— 宁可整图增强，也不乱裁。
 */
final class DocDetect {

    private static final int DET_W = 520;
    private static final float ACCEPT_SCORE = 0.55f;
    /** 严格判据失败后的宽松兜底阈值 */
    private static final float LENIENT_SCORE = 0.52f;

    /** 调试用：最近一次 score() 的分项 */
    static final float[] dbgParts = new float[6];

    private DocDetect() {
    }

    // ================================================================= 数据结构
    static final class S {
        int w, h;
        float[] gray;
        float[] sat;
        float[] grad;
        byte[] edge;
        float edgeThr;
    }

    // ================================================================= 入口
    static float[] detect(int[] argb, int w, int h) {
        return detect(argb, w, h, false);
    }

    static float[] detect(int[] argb, int w, int h, boolean allowNearFull) {
        if (w < 80 || h < 80) return null;
        S s = build(argb, w, h);
        if (s == null) return null;
        byte[] mask = paperMask(s);

        // 收集所有候选（细化后）
        java.util.List<float[]> ref = new ArrayList<>();
        float[] qa = maskQuad(s);
        if (qa != null) addRefined(s, ref, qa);
        float[] qb = projQuad(s);
        if (qb != null) addRefined(s, ref, qb);
        float[] qc = lineQuad(s, mask);
        if (qc != null) addRefined(s, ref, qc);
        int tried = 0;
        for (float[] c : houghQuads(s)) {
            if (++tried > 80) break;
            addRefined(s, ref, c);
        }
        if (ref.isEmpty()) return null;

        // 第一遍：严格判据
        float[] best = null;
        float bestScore = 0f;
        for (float[] q : ref) {
            float sc = score(s, mask, q, false);
            if (sc > bestScore) {
                bestScore = sc;
                best = q;
            }
        }
        // 第二遍：严格判据全军覆没时，用宽松判据兜底（纸几乎占满画面、边缘在阴影里）
        if (best == null || bestScore < ACCEPT_SCORE) {
            float[] best2 = null;
            float bs2 = 0f;
            for (float[] q : ref) {
                float sc = score(s, mask, q, true);
                if (sc > bs2) {
                    bs2 = sc;
                    best2 = q;
                }
            }
            if (best2 != null && bs2 >= LENIENT_SCORE) {
                best = best2;
                bestScore = bs2;
            } else {
                best = null;
            }
        }
        if (best == null) return null;

        float fx = w / (float) s.w;
        float fy = h / (float) s.h;
        float[] q = new float[8];
        for (int i = 0; i < 4; i++) {
            q[i * 2] = best[i * 2] * fx;
            q[i * 2 + 1] = best[i * 2 + 1] * fy;
        }
        double area = Math.abs(shoelace(q)) / 2.0;
        double frame = (double) w * h;
        if (area < frame * 0.10) return null;
        if (!allowNearFull && area > frame * 0.97) return null;   // 基本占满画面 -> 不必裁
        if (!isConvex(q)) return null;

        // 四角向中心内缩 0.2%，去掉纸边外溅的一丝背景
        float cx = (q[0] + q[2] + q[4] + q[6]) / 4f;
        float cy = (q[1] + q[3] + q[5] + q[7]) / 4f;
        for (int i = 0; i < 4; i++) {
            q[i * 2] = cx + (q[i * 2] - cx) * 0.998f;
            q[i * 2 + 1] = cy + (q[i * 2 + 1] - cy) * 0.998f;
        }
        return q;
    }

    private static void addRefined(S s, java.util.List<float[]> out, float[] q) {
        float[] r = refine(s, q);
        if (r != null && isConvex(r)) out.add(r);
    }

    // ================================================================= 路 D：行/列投影找四条边
    /**
     * 纸几乎占满画面时的最稳做法：把梯度沿行、列求平均（纸边是一条贯穿的直线，
     * 字迹不会形成贯穿峰），每条边取"从画面外侧往里扫到的第一个强峰"。
     */
    static float[] projQuad(S s) {
        int W = s.w, H = s.h;
        float[] colG = new float[W];
        float[] rowG = new float[H];
        int yy0 = Math.max(1, H / 12), yy1 = H - Math.max(1, H / 12);
        int xx0 = Math.max(1, W / 12), xx1 = W - Math.max(1, W / 12);

        for (int x = 0; x < W; x++) {
            float sum = 0;
            for (int y = yy0; y < yy1; y++) sum += s.grad[y * W + x];
            colG[x] = sum / Math.max(1, yy1 - yy0);
        }
        for (int y = 0; y < H; y++) {
            float sum = 0;
            for (int x = xx0; x < xx1; x++) sum += s.grad[y * W + x];
            rowG[y] = sum / Math.max(1, xx1 - xx0);
        }

        int left = outerPeak(colG, 0, (int) (W * 0.45f), 1);
        int right = outerPeak(colG, W - 1, (int) (W * 0.55f), -1);
        int top = outerPeak(rowG, 0, (int) (H * 0.45f), 1);
        int bottom = outerPeak(rowG, H - 1, (int) (H * 0.55f), -1);
        if (left < 0 || right < 0 || top < 0 || bottom < 0) return null;
        if (right - left < 0.30f * W || bottom - top < 0.30f * H) return null;

        return orderQuad(new float[]{left, top, right, top, right, bottom, left, bottom});
    }

    /** 从 start 向里扫，返回第一个"够强且是局部极大"的位置；没有则 -1。 */
    private static int outerPeak(float[] g, int start, int end, int dir) {
        int n = g.length;
        int from = Math.min(start, end), to = Math.max(start, end);
        float max = 0;
        for (int i = Math.max(1, from); i < Math.min(n - 1, to); i++) {
            if (g[i] > max) max = g[i];
        }
        if (max <= 0) return -1;
        float thr = max * 0.42f;
        for (int i = start; i != end; i += dir) {
            if (i < 2 || i > n - 3) continue;
            if (g[i] < thr) continue;
            if (g[i] >= g[i - 1] && g[i] >= g[i + 1]) return i;
        }
        return -1;
    }

    // ================================================================= 路 B：每条边一条直线
    /** side: 0=上 1=右 2=下 3=左 */
    static float[] lineQuad(S s, byte[] mask) {
        if (mask == null) return null;
        List<float[]> lines = houghLines(s);
        if (lines.size() < 4) return null;

        float[] chosen = new float[8];    // 每边 {theta, rho}
        for (int side = 0; side < 4; side++) {
            float bestSep = 0.22f;
            float[] bestLine = null;
            for (float[] l : lines) {
                float th = l[0];
                boolean horiz = th > 60 && th < 120;
                boolean vert = th < 30 || th > 150;
                if ((side == 0 || side == 2) && !horiz) continue;
                if ((side == 1 || side == 3) && !vert) continue;

                // 位置约束：上边在上半部、下边在下半部，左右同理
                float c = (float) Math.cos(Math.toRadians(th));
                float sn = (float) Math.sin(Math.toRadians(th));
                float rho = l[1];
                if (side == 0 || side == 2) {
                    float yc = (rho - c * (s.w * 0.5f)) / (Math.abs(sn) < 1e-3f ? 1e-3f : sn);
                    if (side == 0 && (yc < -0.06f * s.h || yc > 0.55f * s.h)) continue;
                    if (side == 2 && (yc < 0.45f * s.h || yc > 1.06f * s.h)) continue;
                } else {
                    float xc = (rho - sn * (s.h * 0.5f)) / (Math.abs(c) < 1e-3f ? 1e-3f : c);
                    if (side == 3 && (xc < -0.06f * s.w || xc > 0.55f * s.w)) continue;
                    if (side == 1 && (xc < 0.45f * s.w || xc > 1.06f * s.w)) continue;
                }
                float sep = separation(s, mask, th, rho);
                if (sep > bestSep) {
                    bestSep = sep;
                    bestLine = l;
                }
            }
            if (bestLine == null) return null;
            chosen[side * 2] = bestLine[0];
            chosen[side * 2 + 1] = bestLine[1];
        }

        float[] top = {chosen[0], chosen[1]};
        float[] right = {chosen[2], chosen[3]};
        float[] bottom = {chosen[4], chosen[5]};
        float[] left = {chosen[6], chosen[7]};
        float[] tl = intersect(top, left);
        float[] tr = intersect(top, right);
        float[] br = intersect(bottom, right);
        float[] bl = intersect(bottom, left);
        if (tl == null || tr == null || br == null || bl == null) return null;

        float[] q = orderQuad(new float[]{tl[0], tl[1], tr[0], tr[1], br[0], br[1], bl[0], bl[1]});
        if (q == null || !isConvex(q)) return null;
        float wq = (float) Math.hypot(q[2] - q[0], q[3] - q[1]);
        float hq = (float) Math.hypot(q[6] - q[0], q[7] - q[1]);
        if (wq < 0.2f * s.w || hq < 0.2f * s.h) return null;
        return q;
    }

    /** 一条直线两侧"纸占比"的差异（越大越像纸边）。 */
    private static float separation(S s, byte[] mask, float theta, float rho) {
        double a = Math.toRadians(theta);
        float c = (float) Math.cos(a), sn = (float) Math.sin(a);
        float nx = c, ny = sn;

        int samples = 40;
        int posPaper = 0, posTot = 0, negPaper = 0, negTot = 0;
        for (int k = 1; k < samples; k++) {
            float t = k / (float) samples;
            float px = -1, py = -1;
            // 沿直线方向走
            if (Math.abs(sn) > Math.abs(c)) {
                px = t * s.w;
                py = (rho - c * px) / sn;
            } else {
                py = t * s.h;
                px = (rho - sn * py) / c;
            }
            if (px < 2 || py < 2 || px > s.w - 3 || py > s.h - 3) continue;
            float sp = 0, snn = 0;
            int spN = 0, snN = 0;
            for (int off = 2; off <= 6; off++) {
                int xi = Math.round(px + nx * off), yi = Math.round(py + ny * off);
                if (xi >= 0 && yi >= 0 && xi < s.w && yi < s.h) {
                    sp += mask[yi * s.w + xi] != 0 ? 1 : 0;
                    spN++;
                }
                xi = Math.round(px - nx * off);
                yi = Math.round(py - ny * off);
                if (xi >= 0 && yi >= 0 && xi < s.w && yi < s.h) {
                    snn += mask[yi * s.w + xi] != 0 ? 1 : 0;
                    snN++;
                }
            }
            if (spN > 0) {
                posPaper += sp / spN > 0.55f ? 1 : 0;
                posTot++;
            }
            if (snN > 0) {
                negPaper += snn / snN > 0.55f ? 1 : 0;
                negTot++;
            }
        }
        if (posTot < 8 || negTot < 8) return 0f;
        float fp = posPaper / (float) posTot;
        float fn = negPaper / (float) negTot;
        return Math.abs(fp - fn);
    }

    // ================================================================= 预处理
    static S build(int[] argb, int w, int h) {
        int sw = Math.min(DET_W, w);
        int sh = Math.max(16, Math.round(h * (sw / (float) w)));
        int n = sw * sh;
        float[] ar = new float[n], ag = new float[n], ab = new float[n];
        int[] cnt = new int[n];
        for (int y = 0; y < h; y++) {
            int sy = (int) ((long) y * sh / h);
            int base = y * w;
            int sbase = sy * sw;
            for (int x = 0; x < w; x++) {
                int si = sbase + (int) ((long) x * sw / w);
                int p = argb[base + x];
                ar[si] += (p >> 16) & 0xFF;
                ag[si] += (p >> 8) & 0xFF;
                ab[si] += p & 0xFF;
                cnt[si]++;
            }
        }
        S s = new S();
        s.w = sw;
        s.h = sh;
        s.gray = new float[n];
        s.sat = new float[n];
        for (int i = 0; i < n; i++) {
            int c = cnt[i] == 0 ? 1 : cnt[i];
            float r = ar[i] / c, g = ag[i] / c, b = ab[i] / c;
            s.gray[i] = 0.299f * r + 0.587f * g + 0.114f * b;
            float mx = Math.max(r, Math.max(g, b));
            float mn = Math.min(r, Math.min(g, b));
            s.sat[i] = mx <= 1f ? 0f : (mx - mn) / mx;
        }
        blur3(s.gray, sw, sh);
        blur3(s.gray, sw, sh);

        // Sobel 梯度
        s.grad = new float[n];
        float maxG = 1f;
        for (int y = 1; y < sh - 1; y++) {
            int row = y * sw;
            for (int x = 1; x < sw - 1; x++) {
                float l0 = s.gray[row - sw + x - 1], l1 = s.gray[row - sw + x], l2 = s.gray[row - sw + x + 1];
                float m0 = s.gray[row + x - 1], m2 = s.gray[row + x + 1];
                float n0 = s.gray[row + sw + x - 1], n1 = s.gray[row + sw + x], n2 = s.gray[row + sw + x + 1];
                float gx = (l2 + 2 * m2 + n2) - (l0 + 2 * m0 + n0);
                float gy = (n0 + 2 * n1 + n2) - (l0 + 2 * l1 + l2);
                float g = (float) Math.sqrt(gx * gx + gy * gy) * 0.25f;
                s.grad[row + x] = g;
                if (g > maxG) maxG = g;
            }
        }

        // 自适应边缘阈值：梯度分布的高分位
        float p88 = percentile(s.grad, 0.88f);
        s.edgeThr = Math.max(6f, p88 * 0.55f);
        s.edge = new byte[n];
        for (int i = 0; i < n; i++) {
            s.edge[i] = (byte) (s.grad[i] >= Math.max(p88, 8f) ? 1 : 0);
        }
        return s;
    }

    private static float percentile(float[] a, float p) {
        int[] hist = new int[512];
        float max = 1f;
        for (float v : a) if (v > max) max = v;
        float k = 511f / max;
        for (float v : a) hist[(int) (v * k)]++;
        int need = (int) (a.length * p);
        int acc = 0;
        for (int i = 0; i < 512; i++) {
            acc += hist[i];
            if (acc >= need) return i / k;
        }
        return max;
    }

    private static void blur3(float[] g, int w, int h) {
        float[] tmp = new float[g.length];
        for (int y = 0; y < h; y++) {
            int row = y * w;
            for (int x = 0; x < w; x++) {
                int l = x > 0 ? row + x - 1 : row + x;
                int r = x < w - 1 ? row + x + 1 : row + x;
                tmp[row + x] = (g[l] + 2f * g[row + x] + g[r]) * 0.25f;
            }
        }
        for (int y = 0; y < h; y++) {
            int row = y * w;
            int up = y > 0 ? row - w : row;
            int dn = y < h - 1 ? row + w : row;
            for (int x = 0; x < w; x++) {
                g[row + x] = (tmp[up + x] + 2f * tmp[row + x] + tmp[dn + x]) * 0.25f;
            }
        }
    }

    private static float sampleGrad(S s, float x, float y) {
        int xi = Math.round(x), yi = Math.round(y);
        if (xi < 0 || yi < 0 || xi >= s.w || yi >= s.h) return 0f;
        return s.grad[yi * s.w + xi];
    }

    // ================================================================= 路 A：亮区掩膜
    /** 生成"白纸"掩膜（小图分辨率）。 */
    static byte[] paperMask(S s) {
        int w = s.w, h = s.h, n = w * h;

        // 局部亮度归一化（去掉阴影/光照梯度），再乘"低饱和"得到白纸度
        int r = Math.max(8, w / 24);
        float[] bg = boxBlurF(s.gray, w, h, r);
        float[] score = new float[n];
        for (int i = 0; i < n; i++) {
            float whiteness = s.gray[i] / Math.max(20f, bg[i]);       // 局部亮度：纸面≈1.0
            if (whiteness > 1.3f) whiteness = 1.3f;
            // 再乘全局亮度（暗背景不会被"归一化"成纸）和低饱和（木色桌面被压低）
            score[i] = whiteness * (1f - 0.85f * s.sat[i])
                    * (float) Math.sqrt(s.gray[i] / 255.0) * 100f;
        }
        blur3(score, w, h);
        int t = (int) otsu(score);
        if (t < 55) t = 55;

        byte[] mask = new byte[n];
        for (int i = 0; i < n; i++) {
            mask[i] = (byte) (score[i] > t && s.gray[i] > 55 ? 1 : 0);
        }
        for (int k = 0; k < 2; k++) {
            dilate(mask, w, h);
            erode(mask, w, h);
        }
        erode(mask, w, h);
        dilate(mask, w, h);
        if (largestComponent(mask, w, h) <= 0) return null;
        dilate(mask, w, h);
        return mask;
    }

    static float[] maskQuad(S s) {
        byte[] mask = paperMask(s);
        if (mask == null) return null;
        int w = s.w, h = s.h, n = w * h;
        int[] xs = new int[n], ys = new int[n];
        int m = 0;
        for (int y = 0; y < h; y++) {
            int row = y * w;
            for (int x = 0; x < w; x++) {
                int i = row + x;
                if (mask[i] == 0) continue;
                boolean edge = x == 0 || y == 0 || x == w - 1 || y == h - 1
                        || mask[i - 1] == 0 || mask[i + 1] == 0
                        || mask[i - w] == 0 || mask[i + w] == 0;
                if (edge && m < n) {
                    xs[m] = x;
                    ys[m] = y;
                    m++;
                }
            }
        }
        if (m < 6) return null;
        float[] hull = convexHull(xs, ys, m);
        if (hull == null || hull.length < 8) return null;
        return reduceToQuad(hull);
    }

    /** 大半径盒式模糊（可分离，O(n)）。 */
    private static float[] boxBlurF(float[] a, int w, int h, int r) {
        float[] tmp = new float[a.length];
        float[] out = new float[a.length];
        float norm = 1f / (2 * r + 1);
        for (int y = 0; y < h; y++) {
            int row = y * w;
            float sum = 0;
            for (int x = -r; x <= r; x++) sum += a[row + Math.min(w - 1, Math.max(0, x))];
            for (int x = 0; x < w; x++) {
                tmp[row + x] = sum * norm;
                int add = Math.min(w - 1, x + r + 1);
                int sub = Math.max(0, x - r);
                sum += a[row + add] - a[row + sub];
            }
        }
        for (int x = 0; x < w; x++) {
            float sum = 0;
            for (int y = -r; y <= r; y++) sum += tmp[Math.min(h - 1, Math.max(0, y)) * w + x];
            for (int y = 0; y < h; y++) {
                out[y * w + x] = sum * norm;
                int add = Math.min(h - 1, y + r + 1);
                int sub = Math.max(0, y - r);
                sum += tmp[add * w + x] - tmp[sub * w + x];
            }
        }
        return out;
    }

    // ================================================================= 路 B：Hough 直线
    private static List<float[]> houghLines(S s) {
        int W = s.w, H = s.h;
        int diag = (int) Math.ceil(Math.sqrt((double) W * W + (double) H * H));
        int nRho = 2 * diag + 1;
        final int nTheta = 180;
        float[] cosT = new float[nTheta], sinT = new float[nTheta];
        for (int t = 0; t < nTheta; t++) {
            double a = Math.toRadians(t * 1.0);
            cosT[t] = (float) Math.cos(a);
            sinT[t] = (float) Math.sin(a);
        }
        int[] acc = new int[nTheta * nRho];
        int points = 0;
        for (int y = 0; y < H; y++) {
            int row = y * W;
            for (int x = 0; x < W; x++) {
                if (s.edge[row + x] == 0) continue;
                points++;
                for (int t = 0; t < nTheta; t++) {
                    int r = (int) (x * cosT[t] + y * sinT[t]) + diag;
                    if (r >= 0 && r < nRho) acc[t * nRho + r]++;
                }
            }
        }
        if (points < 40) return new ArrayList<>();

        int maxV = 0;
        for (int v : acc) if (v > maxV) maxV = v;
        int minV = Math.max(18, (int) (maxV * 0.32f));

        // 收集候选峰并按票数排序
        List<int[]> peaks = new ArrayList<>();
        for (int t = 0; t < nTheta; t++) {
            int base = t * nRho;
            for (int r = 1; r < nRho - 1; r++) {
                int v = acc[base + r];
                if (v < minV) continue;
                // 局部极大
                if (acc[base + r - 1] > v || acc[base + r + 1] > v) continue;
                peaks.add(new int[]{t, r, v});
            }
        }
        peaks.sort((a, b) -> Integer.compare(b[2], a[2]));

        List<float[]> lines = new ArrayList<>();   // {theta, rho, votes}
        for (int[] p : peaks) {
            int t = p[0];
            float rho = p[1] - diag;
            boolean dup = false;
            for (float[] l : lines) {
                int dt = Math.abs((int) l[0] - t);
                if (dt > 90) dt = 180 - dt;
                if (dt <= 5 && Math.abs(l[1] - rho) <= 12) {
                    dup = true;
                    break;
                }
            }
            if (dup) continue;
            lines.add(new float[]{t, rho, p[2]});
            if (lines.size() >= 20) break;
        }
        return lines;
    }

    static List<float[]> houghQuads(S s) {
        List<float[]> out = new ArrayList<>();
        List<float[]> lines = houghLines(s);
        int n = lines.size();
        if (n < 4) return out;

        // 平行线对
        List<int[]> pairs = new ArrayList<>();
        float minGap = 0.18f * Math.min(s.w, s.h);
        for (int i = 0; i < n; i++) {
            for (int j = i + 1; j < n; j++) {
                float d = Math.abs(lines.get(i)[0] - lines.get(j)[0]);
                if (d > 90) d = 180 - d;
                if (d > 13) continue;
                if (Math.abs(lines.get(i)[1] - lines.get(j)[1]) < minGap) continue;
                pairs.add(new int[]{i, j});
            }
        }
        if (pairs.size() < 2) return out;

        int limit = 240;
        for (int a = 0; a < pairs.size(); a++) {
            for (int b = a + 1; b < pairs.size(); b++) {
                int[] pa = pairs.get(a), pb = pairs.get(b);
                // 两组线不能共用同一条
                if (pa[0] == pb[0] || pa[0] == pb[1] || pa[1] == pb[0] || pa[1] == pb[1]) continue;
                float ta = (lines.get(pa[0])[0] + lines.get(pa[1])[0]) * 0.5f;
                float tb = (lines.get(pb[0])[0] + lines.get(pb[1])[0]) * 0.5f;
                float dd = Math.abs(ta - tb);
                if (dd > 90) dd = 180 - dd;
                if (dd < 55) continue;   // 要近似垂直
                float[] q = quadFrom(lines.get(pa[0]), lines.get(pa[1]), lines.get(pb[0]), lines.get(pb[1]));
                if (q == null) continue;
                if (!isConvex(q)) continue;
                double area = Math.abs(shoelace(q)) / 2.0;
                if (area < s.w * (double) s.h * 0.12) continue;
                out.add(q);
                if (out.size() >= limit) return out;
            }
        }
        return out;
    }

    /** 四条直线（两对）求交得到四边形，顺序 TL,TR,BR,BL。 */
    private static float[] quadFrom(float[] l1, float[] l2, float[] l3, float[] l4) {
        float[] p1 = intersect(l1, l3);
        float[] p2 = intersect(l1, l4);
        float[] p3 = intersect(l2, l4);
        float[] p4 = intersect(l2, l3);
        if (p1 == null || p2 == null || p3 == null || p4 == null) return null;
        return orderQuad(new float[]{p1[0], p1[1], p2[0], p2[1], p3[0], p3[1], p4[0], p4[1]});
    }

    private static float[] intersect(float[] l1, float[] l2) {
        double a1 = Math.toRadians(l1[0]), a2 = Math.toRadians(l2[0]);
        double c1 = Math.cos(a1), s1 = Math.sin(a1);
        double c2 = Math.cos(a2), s2 = Math.sin(a2);
        double det = c1 * s2 - s1 * c2;
        if (Math.abs(det) < 1e-3) return null;
        double x = (l1[1] * s2 - s1 * l2[1]) / det;
        double y = (c1 * l2[1] - l1[1] * c2) / det;
        if (Double.isNaN(x) || Double.isNaN(y) || Double.isInfinite(x) || Double.isInfinite(y)) return null;
        return new float[]{(float) x, (float) y};
    }

    // ================================================================= 细化：用真实边缘像素重新拟合四条边
    static float[] refine(S s, float[] q) {
        if (q == null) return null;
        float[][] lines = new float[4][];
        for (int e = 0; e < 4; e++) {
            float x0 = q[e * 2], y0 = q[e * 2 + 1];
            float x1 = q[((e + 1) % 4) * 2], y1 = q[((e + 1) % 4) * 2 + 1];
            float dx = x1 - x0, dy = y1 - y0;
            float len = (float) Math.sqrt(dx * dx + dy * dy);
            if (len < 12) return q;
            float ux = dx / len, uy = dy / len;
            float nx = -uy, ny = ux;

            // 沿边采样，找最近的边缘像素
            int samples = Math.max(24, Math.round(len / 3f));
            double sumT = 0, sumT2 = 0, sumOff = 0, sumTOff = 0;
            int used = 0;
            for (int k = 1; k < samples; k++) {
                float t = (k / (float) samples) * len;
                if (t < 0.06f * len || t > 0.94f * len) continue;
                float px = x0 + ux * t, py = y0 + uy * t;
                float bestOff = 0, bestG = 0;
                for (float off = -3.5f; off <= 3.5f; off += 0.5f) {
                    float g = sampleGrad(s, px + nx * off, py + ny * off);
                    if (g > bestG) {
                        bestG = g;
                        bestOff = off;
                    }
                }
                if (bestG < s.edgeThr) continue;
                sumT += t;
                sumT2 += t * t;
                sumOff += bestOff;
                sumTOff += t * bestOff;
                used++;
            }
            if (used < 10) {
                lines[e] = new float[]{(float) Math.toDegrees(Math.atan2(uy, ux)), -(x0 * nx + y0 * ny) * -1f, x0, y0, len, nx, ny};
            } else {
                // 直线拟合 offset = a*t + b
                double det = used * sumT2 - sumT * sumT;
                double a = 0, b = sumOff / used;
                if (Math.abs(det) > 1e-6) {
                    a = (used * sumTOff - sumT * sumOff) / det;
                    b = (sumOff - a * sumT) / used;
                }
                // 用拟合后的边：点 (x0 + ux*t + nx*(a*t+b), ...)
                // 方向向量 = ux + nx*a , uy + ny*a ；过点 x0 + nx*b, y0 + ny*b
                float dx2 = ux + nx * (float) a, dy2 = uy + ny * (float) a;
                float l2 = (float) Math.sqrt(dx2 * dx2 + dy2 * dy2);
                dx2 /= l2;
                dy2 /= l2;
                float ox = x0 + nx * (float) b, oy = y0 + ny * (float) b;
                // 法线形式：theta = atan2(dy2, dx2) + 90°
                float th = (float) (Math.toDegrees(Math.atan2(dy2, dx2)) + 90.0);
                if (th < 0) th += 180;
                if (th >= 180) th -= 180;
                double c = Math.cos(Math.toRadians(th)), sn = Math.sin(Math.toRadians(th));
                float rho = (float) (ox * c + oy * sn);
                lines[e] = new float[]{th, rho, ox, oy, len, nx, ny};
            }
        }
        float[] p0 = intersect(lines[0], lines[3]);
        float[] p1 = intersect(lines[0], lines[1]);
        float[] p2 = intersect(lines[1], lines[2]);
        float[] p3 = intersect(lines[2], lines[3]);
        if (p0 == null || p1 == null || p2 == null || p3 == null) return q;
        float[] out = orderQuad(new float[]{p0[0], p0[1], p1[0], p1[1], p2[0], p2[1], p3[0], p3[1]});
        if (out == null || !isConvex(out)) return q;
        // 细化不能偏离太远
        for (int i = 0; i < 8; i++) {
            float d = Math.abs(out[i] - q[i]);
            if (d > 0.22f * Math.max(s.w, s.h)) return q;
        }
        return out;
    }

    // ================================================================= 打分
    /**
     * 判据（沿四条边逐点检查，而不是只看整块区域）：
     *   每条边紧贴的内侧必须是纸、紧贴的外侧必须不是纸；
     *   再加台阶支持度作门槛、面积作偏好。
     */
    static float score(S s, byte[] mask, float[] q, boolean lenient) {
        if (q == null || !isConvex(q)) return 0f;
        double area = Math.abs(shoelace(q)) / 2.0;
        double frame = (double) s.w * s.h;
        float areaRatio = (float) (area / frame);
        if (areaRatio < 0.10 || areaRatio > 0.997) return 0f;

        float ew = (float) Math.hypot(q[2] - q[0], q[3] - q[1]);
        float eh = (float) Math.hypot(q[6] - q[0], q[7] - q[1]);
        if (ew < 8f || eh < 8f) return 0f;
        float ar = ew / eh;
        if (ar < 0.35f || ar > 2.8f) return 0f;

        int hit = 0, tot = 0, pos = 0, neg = 0;
        float inPaperSum = 0, outPaperSum = 0;
        float inGraySum = 0;
        int maskHit = 0;
        float minEdgeSup = 1f;

        for (int e = 0; e < 4; e++) {
            float x0 = q[e * 2], y0 = q[e * 2 + 1];
            float x1 = q[((e + 1) % 4) * 2], y1 = q[((e + 1) % 4) * 2 + 1];
            float dx = x1 - x0, dy = y1 - y0;
            float len = (float) Math.sqrt(dx * dx + dy * dy);
            if (len < 10) return 0f;
            float nx = -dy / len, ny = dx / len;

            int eHit = 0, eTot = 0;
            for (int k = 1; k <= 36; k++) {
                float t = k / 37f;
                float px = x0 + dx * t, py = y0 + dy * t;

                float g = sampleGrad(s, px, py);
                float gIn = 0, gOut = 0;
                for (int off = 2; off <= 5; off++) {
                    gIn += sampleGray(s, px + nx * off, py + ny * off);
                    gOut += sampleGray(s, px - nx * off, py - ny * off);
                }
                tot++;
                eTot++;
                float step = gIn / 4f - gOut / 4f;
                if (Math.abs(step) >= 8f && g >= s.edgeThr * 0.65f) {
                    hit++;
                    eHit++;
                    if (step > 0) pos++;
                    else neg++;
                }

                int inP = 0;
                for (int off = 2; off <= 5; off++) {
                    if (isPaperAt(s, px + nx * off, py + ny * off)) inP++;
                }
                int outP = 0;
                for (int off = 2; off <= 5; off++) {
                    if (isPaperAt(s, px - nx * off, py - ny * off)) outP++;
                }
                inPaperSum += inP / 4f;
                outPaperSum += outP / 4f;
                inGraySum += sampleGray(s, px + nx * 3f, py + ny * 3f);

                if (mask != null && maskTransition(s, mask, px, py, nx, ny)) maskHit++;
            }
            float es = eHit / (float) Math.max(1, eTot);
            if (es < minEdgeSup) minEdgeSup = es;
        }
        if (tot == 0) return 0f;
        float support = hit / (float) tot;
        float inPaper = inPaperSum / tot;
        float outPaper = outPaperSum / tot;
        float paperDiff = Math.max(0f, Math.min(1f, inPaper - outPaper));
        float maskAgree = maskHit / (float) tot;
        float inMean = inGraySum / tot;
        float consist = hit == 0 ? 0f : Math.max(pos, neg) / (float) hit;

        dbgParts[0] = paperDiff;
        dbgParts[1] = maskAgree;
        dbgParts[2] = support;
        dbgParts[3] = inPaper;
        dbgParts[4] = minEdgeSup;
        dbgParts[5] = outPaper;

        float brightBonus = Math.max(0f, Math.min(1f, (inMean - 90f) / 90f));
        float areaPref = Math.min(1f, areaRatio / 0.72f);

        if (!lenient) {
            if (support < 0.36f) return 0f;
            if (minEdgeSup < 0.20f) return 0f;
            if (inPaper < 0.45f) return 0f;
            return 0.28f * maskAgree
                    + 0.26f * paperDiff
                    + 0.16f * support
                    + 0.14f * areaPref
                    + 0.08f * brightBonus
                    + 0.08f * Math.min(1f, Math.max(0f, (consist - 0.55f) / 0.45f));
        }

        // 宽松：只要四条边都有真实的强弱过渡、内部大体是纸、面积像纸就接受
        if (support < 0.30f) return 0f;
        if (minEdgeSup < 0.13f) return 0f;
        if (inPaper < 0.30f) return 0f;
        if (areaRatio < 0.28f) return 0f;
        return 0.34f * support
                + 0.22f * paperDiff
                + 0.20f * areaPref
                + 0.14f * maskAgree
                + 0.10f * Math.min(1f, Math.max(0f, (consist - 0.5f) / 0.5f));
    }

    /** 沿法线 ±3px 内是否存在掩膜的 0/1 跳变。 */
    private static boolean maskTransition(S s, byte[] mask, float px, float py, float nx, float ny) {
        int prev = -1;
        for (int off = -3; off <= 3; off++) {
            int xi = Math.round(px + nx * off), yi = Math.round(py + ny * off);
            if (xi < 0 || yi < 0 || xi >= s.w || yi >= s.h) continue;
            int cur = mask[yi * s.w + xi] != 0 ? 1 : 0;
            if (prev >= 0 && cur != prev) return true;
            prev = cur;
        }
        return false;
    }

    /** 该点是否像白纸（用小图灰度/饱和度判断）。 */
    private static boolean isPaperAt(S s, float x, float y) {
        int xi = Math.round(x), yi = Math.round(y);
        if (xi < 0 || yi < 0 || xi >= s.w || yi >= s.h) return false;
        int idx = yi * s.w + xi;
        return s.gray[idx] > 95f && s.sat[idx] < 0.22f;
    }

    private static float sampleGray(S s, float x, float y) {
        int xi = Math.round(x), yi = Math.round(y);
        if (xi < 0 || yi < 0 || xi >= s.w || yi >= s.h) return 0f;
        return s.gray[yi * s.w + xi];
    }

    private static boolean insideConvex(float[] q, float x, float y) {
        int sign = 0;
        for (int i = 0; i < 4; i++) {
            int j = (i + 1) % 4;
            float cr = (q[j * 2] - q[i * 2]) * (y - q[i * 2 + 1]) - (q[j * 2 + 1] - q[i * 2 + 1]) * (x - q[i * 2]);
            int sgn = cr > 0 ? 1 : (cr < 0 ? -1 : 0);
            if (sgn == 0) continue;
            if (sign == 0) sign = sgn;
            else if (sgn != sign) return false;
        }
        return true;
    }

    private static float distToQuad(float[] q, float x, float y) {
        float best = Float.MAX_VALUE;
        for (int i = 0; i < 4; i++) {
            int j = (i + 1) % 4;
            float x0 = q[i * 2], y0 = q[i * 2 + 1], x1 = q[j * 2], y1 = q[j * 2 + 1];
            float dx = x1 - x0, dy = y1 - y0;
            float len2 = dx * dx + dy * dy;
            float t = len2 <= 0 ? 0 : ((x - x0) * dx + (y - y0) * dy) / len2;
            if (t < 0) t = 0;
            if (t > 1) t = 1;
            float px = x0 + dx * t, py = y0 + dy * t;
            float d = (float) Math.sqrt((x - px) * (x - px) + (y - py) * (y - py));
            if (d < best) best = d;
        }
        return best;
    }

    // ================================================================= 几何小工具
    static float[] orderQuad(float[] p) {
        float cx = (p[0] + p[2] + p[4] + p[6]) / 4f;
        float cy = (p[1] + p[3] + p[5] + p[7]) / 4f;
        final float[] q = p.clone();
        final float ccx = cx, ccy = cy;
        Integer[] idx = new Integer[]{0, 1, 2, 3};
        java.util.Arrays.sort(idx, new java.util.Comparator<Integer>() {
            @Override
            public int compare(Integer a, Integer b) {
                double aa = Math.atan2(q[a * 2 + 1] - ccy, q[a * 2] - ccx);
                double bb = Math.atan2(q[b * 2 + 1] - ccy, q[b * 2] - ccx);
                return Double.compare(aa, bb);
            }
        });
        int start = 0;
        float bestSum = Float.MAX_VALUE;
        for (int i = 0; i < 4; i++) {
            int k = idx[i];
            float sum = q[k * 2] + q[k * 2 + 1];
            if (sum < bestSum) {
                bestSum = sum;
                start = i;
            }
        }
        float[] out = new float[8];
        for (int i = 0; i < 4; i++) {
            int k = idx[(start + i) % 4];
            out[i * 2] = q[k * 2];
            out[i * 2 + 1] = q[k * 2 + 1];
        }
        if (shoelace(out) < 0) {
            return new float[]{out[0], out[1], out[6], out[7], out[4], out[5], out[2], out[3]};
        }
        return out;
    }

    static double shoelace(float[] q) {
        double s = 0;
        for (int i = 0; i < 4; i++) {
            int j = (i + 1) % 4;
            s += (double) q[i * 2] * q[j * 2 + 1] - (double) q[j * 2] * q[i * 2 + 1];
        }
        return s;
    }

    static boolean isConvex(float[] q) {
        double sign = 0;
        for (int i = 0; i < 4; i++) {
            int j = (i + 1) % 4;
            int k = (i + 2) % 4;
            double c = ((q[j * 2] - q[i * 2]) * (q[k * 2 + 1] - q[i * 2 + 1])
                    - (q[j * 2 + 1] - q[i * 2 + 1]) * (q[k * 2] - q[i * 2])) * 0.5;
            if (Math.abs(c) < 1e-6) continue;
            if (sign == 0) sign = c;
            else if (c * sign < 0) return false;
        }
        return true;
    }

    // ================================================================= 掩膜路用到的形态学/连通域/凸包
    private static int otsu(float[] g) {
        int[] hist = new int[256];
        for (float v : g) {
            int b = (int) v;
            if (b < 0) b = 0;
            if (b > 255) b = 255;
            hist[b]++;
        }
        int total = g.length;
        double sum = 0;
        for (int i = 0; i < 256; i++) sum += (double) i * hist[i];
        double sumB = 0;
        int wB = 0;
        double best = -1;
        int bestT = 128;
        for (int t = 0; t < 256; t++) {
            wB += hist[t];
            if (wB == 0) continue;
            int wF = total - wB;
            if (wF == 0) break;
            sumB += (double) t * hist[t];
            double mB = sumB / wB;
            double mF = (sum - sumB) / wF;
            double between = (double) wB * wF * (mB - mF) * (mB - mF);
            if (between > best) {
                best = between;
                bestT = t;
            }
        }
        return bestT;
    }

    private static void dilate(byte[] m, int w, int h) {
        byte[] out = new byte[m.length];
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                byte v = 0;
                for (int dy = -1; dy <= 1 && v == 0; dy++) {
                    int yy = y + dy;
                    if (yy < 0 || yy >= h) continue;
                    int row = yy * w;
                    for (int dx = -1; dx <= 1; dx++) {
                        int xx = x + dx;
                        if (xx < 0 || xx >= w) continue;
                        if (m[row + xx] != 0) {
                            v = 1;
                            break;
                        }
                    }
                }
                out[y * w + x] = v;
            }
        }
        System.arraycopy(out, 0, m, 0, m.length);
    }

    private static void erode(byte[] m, int w, int h) {
        byte[] out = new byte[m.length];
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                byte v = 1;
                for (int dy = -1; dy <= 1 && v == 1; dy++) {
                    int yy = y + dy;
                    if (yy < 0 || yy >= h) continue;
                    int row = yy * w;
                    for (int dx = -1; dx <= 1; dx++) {
                        int xx = x + dx;
                        if (xx < 0 || xx >= w) continue;
                        if (m[row + xx] == 0) {
                            v = 0;
                            break;
                        }
                    }
                }
                out[y * w + x] = v;
            }
        }
        System.arraycopy(out, 0, m, 0, m.length);
    }

    private static int largestComponent(byte[] m, int w, int h) {
        int[] label = new int[m.length];
        int[] stack = new int[m.length];
        int bestLabel = 0;
        int bestArea = 0;
        int cur = 1;
        for (int i = 0; i < m.length; i++) {
            if (m[i] == 0 || label[i] != 0) continue;
            int sp = 0;
            stack[sp++] = i;
            label[i] = cur;
            int area = 0;
            while (sp > 0) {
                int p = stack[--sp];
                area++;
                int x = p % w, y = p / w;
                if (x > 0 && m[p - 1] != 0 && label[p - 1] == 0) { label[p - 1] = cur; stack[sp++] = p - 1; }
                if (x < w - 1 && m[p + 1] != 0 && label[p + 1] == 0) { label[p + 1] = cur; stack[sp++] = p + 1; }
                if (y > 0 && m[p - w] != 0 && label[p - w] == 0) { label[p - w] = cur; stack[sp++] = p - w; }
                if (y < h - 1 && m[p + w] != 0 && label[p + w] == 0) { label[p + w] = cur; stack[sp++] = p + w; }
            }
            if (area > bestArea) {
                bestArea = area;
                bestLabel = cur;
            }
            cur++;
        }
        if (bestLabel == 0) return 0;
        for (int i = 0; i < m.length; i++) m[i] = (byte) (label[i] == bestLabel ? 1 : 0);
        return bestLabel;
    }

    private static float[] convexHull(int[] xs, int[] ys, int m) {
        Integer[] idx = new Integer[m];
        for (int i = 0; i < m; i++) idx[i] = i;
        final int[] fx = xs, fy = ys;
        java.util.Arrays.sort(idx, new java.util.Comparator<Integer>() {
            @Override
            public int compare(Integer a, Integer b) {
                int c = Integer.compare(fx[a], fx[b]);
                return c != 0 ? c : Integer.compare(fy[a], fy[b]);
            }
        });
        int[] hull = new int[2 * m + 2];
        int k = 0;
        for (int i = 0; i < m; i++) {
            int p = idx[i];
            while (k >= 2 && cross(fx[hull[k - 2]], fy[hull[k - 2]], fx[hull[k - 1]], fy[hull[k - 1]], fx[p], fy[p]) <= 0) k--;
            hull[k++] = p;
        }
        int lower = k + 1;
        for (int i = m - 2; i >= 0; i--) {
            int p = idx[i];
            while (k >= lower && cross(fx[hull[k - 2]], fy[hull[k - 2]], fx[hull[k - 1]], fy[hull[k - 1]], fx[p], fy[p]) <= 0) k--;
            hull[k++] = p;
        }
        int hn = k - 1;
        if (hn < 4) return null;
        float[] out = new float[hn * 2];
        for (int i = 0; i < hn; i++) {
            out[i * 2] = fx[hull[i]];
            out[i * 2 + 1] = fy[hull[i]];
        }
        return out;
    }

    private static long cross(int ax, int ay, int bx, int by, int cx, int cy) {
        return (long) (bx - ax) * (cy - ay) - (long) (by - ay) * (cx - ax);
    }

    private static float[] reduceToQuad(float[] hull) {
        int n = hull.length / 2;
        float[] px = new float[n], py = new float[n];
        for (int i = 0; i < n; i++) {
            px[i] = hull[i * 2];
            py[i] = hull[i * 2 + 1];
        }
        boolean[] alive = new boolean[n];
        for (int i = 0; i < n; i++) alive[i] = true;
        int aliveCount = n;
        while (aliveCount > 12) {
            int worst = -1;
            double worstArea = Double.MAX_VALUE;
            int prev = -1;
            for (int i = 0; i < n; i++) {
                if (!alive[i]) continue;
                if (prev >= 0) {
                    int next = nextAlive(alive, i);
                    if (next >= 0) {
                        double a = Math.abs(triArea(px[prev], py[prev], px[i], py[i], px[next], py[next]));
                        if (a < worstArea) {
                            worstArea = a;
                            worst = i;
                        }
                    }
                }
                prev = i;
            }
            if (worst < 0) break;
            alive[worst] = false;
            aliveCount--;
        }
        int m = aliveCount;
        if (m < 4) return null;
        float[] cx = new float[m], cy = new float[m];
        int k = 0;
        for (int i = 0; i < n; i++) {
            if (alive[i]) {
                cx[k] = px[i];
                cy[k] = py[i];
                k++;
            }
        }
        double best = -1;
        float[] bestQ = null;
        for (int a = 0; a < m - 3; a++)
            for (int b = a + 1; b < m - 2; b++)
                for (int c = b + 1; c < m - 1; c++)
                    for (int d = c + 1; d < m; d++) {
                        float[] o = orderQuad(new float[]{cx[a], cy[a], cx[b], cy[b], cx[c], cy[c], cx[d], cy[d]});
                        if (o == null) continue;
                        double area = Math.abs(shoelace(o)) * 0.5;
                        if (area > best) {
                            best = area;
                            bestQ = o;
                        }
                    }
        return bestQ;
    }

    private static int nextAlive(boolean[] alive, int i) {
        int n = alive.length;
        for (int k = 1; k <= n; k++) {
            int j = (i + k) % n;
            if (alive[j]) return j;
        }
        return -1;
    }

    private static double triArea(float ax, float ay, float bx, float by, float cx, float cy) {
        return ((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) * 0.5;
    }
}
