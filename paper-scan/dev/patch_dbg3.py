p = r'C:\chatbox_temp\paper-scan\android\app\src\main\java\com\chatbox\paperscan\DocDetect.java'
s = open(p, encoding='utf-8').read()

old = '''        // 门槛：纸边内侧必须是纸
        if (inPaper < 0.72f) return 0f;'''
new = '''        dbgParts[0] = paperDiff;
        dbgParts[1] = Math.min(1f, areaRatio / 0.72f);
        dbgParts[2] = support;
        dbgParts[3] = inPaper;
        dbgParts[4] = consist;
        dbgParts[5] = outPaper;

        // 门槛：纸边内侧必须是纸
        if (inPaper < 0.72f) return 0f;'''
if old not in s:
    raise SystemExit('gate anchor missing')
s = s.replace(old, new, 1)
open(p, 'w', encoding='utf-8').write(s)
print('dbg before gates')
