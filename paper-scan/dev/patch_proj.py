p = r'C:\chatbox_temp\paper-scan\android\app\src\main\java\com\chatbox\paperscan\DocDetect.java'
s = open(p, encoding='utf-8').read()

# 1) 新增 projQuad（插在 "路 B" 之前）
anchor = '    // ================================================================= 路 B：每条边一条直线'
add = '''    // ================================================================= 路 D：行/列投影找四条边
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

'''
s = s.replace(anchor, add + anchor, 1)

# 2) detect() 里加一路
old_call = '''        // 路 C：Hough 组合（兜底，处理纸不在画面正中/多张纸的情况）'''
new_call = '''        // 路 D：行/列投影（纸几乎占满画面时最稳）
        float[] qd = projQuad(s);
        if (qd != null) {
            float[] r = refine(s, qd);
            float sc = score(s, r);
            if (sc > bestScore) {
                bestScore = sc;
                best = r;
            }
        }

        // 路 C：Hough 组合（兜底，处理纸不在画面正中/多张纸的情况）'''
s = s.replace(old_call, new_call, 1)

open(p, 'w', encoding='utf-8').write(s)
print('projQuad added')
