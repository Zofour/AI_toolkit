p = r'C:\chatbox_temp\paper-scan\android\app\src\main\java\com\chatbox\paperscan\DocDetect.java'
s = open(p, encoding='utf-8').read()

# ---------- 1) score 增加 mask 参数，并重写判据 ----------
start = s.index('    static float score(S s, float[] q) {')
end = s.index('    /** 该点是否像白纸（用小图灰度/饱和度判断）。 */')
new_score = '''    static float score(S s, byte[] mask, float[] q) {
        if (q == null || !isConvex(q)) return 0f;
        double area = Math.abs(shoelace(q)) / 2.0;
        double frame = (double) s.w * s.h;
        float areaRatio = (float) (area / frame);
        if (areaRatio < 0.10 || areaRatio > 0.997) return 0f;

        // 长宽比校验：纸张/票据的合理范围，极端窄条多半是误检
        float ew = (float) Math.hypot(q[2] - q[0], q[3] - q[1]);
        float eh = (float) Math.hypot(q[6] - q[0], q[7] - q[1]);
        if (ew < 8f || eh < 8f) return 0f;
        float ar = ew / eh;
        if (ar < 0.35f || ar > 2.8f) return 0f;

        int hit = 0, tot = 0, pos = 0, neg = 0;
        float inPaperSum = 0, outPaperSum = 0;
        float inGraySum = 0;
        int maskHit = 0;

        for (int e = 0; e < 4; e++) {
            float x0 = q[e * 2], y0 = q[e * 2 + 1];
            float x1 = q[((e + 1) % 4) * 2], y1 = q[((e + 1) % 4) * 2 + 1];
            float dx = x1 - x0, dy = y1 - y0;
            float len = (float) Math.sqrt(dx * dx + dy * dy);
            if (len < 10) return 0f;
            float nx = -dy / len, ny = dx / len;   // 内法线

            for (int k = 1; k <= 36; k++) {
                float t = k / 37f;
                float px = x0 + dx * t, py = y0 + dy * t;

                // 台阶支持度
                float g = sampleGrad(s, px, py);
                float gIn = 0, gOut = 0;
                for (int off = 2; off <= 5; off++) {
                    gIn += sampleGray(s, px + nx * off, py + ny * off);
                    gOut += sampleGray(s, px - nx * off, py - ny * off);
                }
                tot++;
                float step = gIn / 4f - gOut / 4f;
                if (Math.abs(step) >= 8f && g >= s.edgeThr * 0.65f) {
                    hit++;
                    if (step > 0) pos++;
                    else neg++;
                }

                // 紧贴内侧 / 外侧的"纸"占比
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

                // 这条边是不是正好压在"纸/非纸"掩膜的分界上
                if (mask != null && maskTransition(s, mask, px, py, nx, ny)) maskHit++;
            }
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
        dbgParts[4] = consist;
        dbgParts[5] = outPaper;

        if (support < 0.36f) return 0f;
        // 内侧得大体是纸；允许偏暗/偏色（阴影/冷暖光）
        if (inPaper < 0.45f) return 0f;

        float brightBonus = Math.max(0f, Math.min(1f, (inMean - 90f) / 90f));
        float areaPref = Math.min(1f, areaRatio / 0.72f);

        return 0.28f * maskAgree
                + 0.26f * paperDiff
                + 0.16f * support
                + 0.14f * areaPref
                + 0.08f * brightBonus
                + 0.08f * Math.min(1f, Math.max(0f, (consist - 0.55f) / 0.45f));
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

'''
s = s[:start] + new_score + s[end:]

# ---------- 2) 更新调用点 ----------
s = s.replace('float sc = score(s, r);', 'float sc = score(s, mask, r);')
s = s.replace('float sc = score(s, rq);', 'float sc = score(s, mask, rq);')

open(p, 'w', encoding='utf-8').write(s)
print('score mask-aware; calls:', s.count('score(s, mask,'))
