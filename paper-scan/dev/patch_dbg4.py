p = r'C:\chatbox_temp\paper-scan\android\app\src\main\java\com\chatbox\paperscan\DocDetect.java'
s = open(p, encoding='utf-8').read()

# 1) 去掉放在 consist 之前的调试块
bad = '''        dbgParts[0] = paperDiff;
        dbgParts[1] = Math.min(1f, areaRatio / 0.72f);
        dbgParts[2] = support;
        dbgParts[3] = inPaper;
        dbgParts[4] = consist;
        dbgParts[5] = outPaper;

        // 门槛：纸边内侧必须是纸
        if (inPaper < 0.72f) return 0f;'''
good = '''        // 门槛：纸边内侧必须是纸
        if (inPaper < 0.72f) return 0f;'''
if bad in s:
    s = s.replace(bad, good, 1)

# 2) 在 consist 之后、所有正式计算之前写调试变量
old2 = '''        float consist = hit == 0 ? 0f : Math.max(pos, neg) / (float) hit;'''
new2 = '''        float consist = hit == 0 ? 0f : Math.max(pos, neg) / (float) hit;

        dbgParts[0] = paperDiff;
        dbgParts[1] = Math.min(1f, areaRatio / 0.72f);
        dbgParts[2] = support;
        dbgParts[3] = inPaper;
        dbgParts[4] = consist;
        dbgParts[5] = outPaper;'''
if new2 not in s:
    s = s.replace(old2, new2, 1)

open(p, 'w', encoding='utf-8').write(s)
print('dbg fixed')
