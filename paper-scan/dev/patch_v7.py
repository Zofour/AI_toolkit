p = r'C:\chatbox_temp\paper-scan\android\app\src\main\java\com\chatbox\paperscan\DocDetect.java'
s = open(p, encoding='utf-8').read()

# ---------------- 1) 重写 detect()：候选统一收集，严格/宽松两遍 ----------------
d_start = s.index('    static float[] detect(int[] argb, int w, int h, boolean allowNearFull) {')
d_end = s.index('    // ================================================================= 路 D：行/列投影找四条边')

new_detect = '''    static float[] detect(int[] argb, int w, int h, boolean allowNearFull) {
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

'''
s = s[:d_start] + new_detect + s[d_end:]

# ---------------- 2) score 增加 lenient；补 per-edge 支持度 ----------------
sc_start = s.index('    static float score(S s, byte[] mask, float[] q) {')
sc_end = s.index('    /** 沿法线 ±3px 内是否存在掩膜的 0/1 跳变。 */')

new_score = '''    static float score(S s, byte[] mask, float[] q, boolean lenient) {
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

'''
s = s[:sc_start] + new_score + s[sc_end:]

# 常量
s = s.replace('    private static final float ACCEPT_SCORE = 0.55f;',
              '    private static final float ACCEPT_SCORE = 0.55f;\n    /** 严格判据失败后的宽松兜底阈值 */\n    private static final float LENIENT_SCORE = 0.52f;')

open(p, 'w', encoding='utf-8').write(s)
print('detect+score rewritten; LENIENT:', 'LENIENT_SCORE' in s)
