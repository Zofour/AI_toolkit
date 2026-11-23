p = r'C:\chatbox_temp\paper-scan\dev\DevDebug.java'
s = open(p, encoding='utf-8').read()
add = '''            float[] pq = DocDetect.projQuad(s);
            if (pq != null) {
                float[] pr = DocDetect.refine(s, pq);
                float psc = DocDetect.score(s, pr);
                System.out.println("  projQuad score=" + String.format("%.3f", psc)
                        + " parts[diff=" + String.format("%.2f", DocDetect.dbgParts[0])
                        + " area=" + String.format("%.2f", DocDetect.dbgParts[1])
                        + " sup=" + String.format("%.2f", DocDetect.dbgParts[2]) + "] " + fmt(pr));
            } else {
                System.out.println("  projQuad = null");
            }
            float[] lq = DocDetect.lineQuad(s, mask);'''

if 'projQuad score=' not in s:
    s = s.replace('            float[] lq = DocDetect.lineQuad(s, mask);', add, 1)
    open(p, 'w', encoding='utf-8').write(s)
    print('DevDebug: projQuad added')
else:
    print('already')
