p = r'C:\chatbox_temp\paper-scan\dev\DevDebug.java'
s = open(p, encoding='utf-8').read()
old = '''+ " sup=" + String.format("%.2f", DocDetect.dbgParts[2]) + "] " + fmt(pr));'''
new = '''+ " sup=" + String.format("%.2f", DocDetect.dbgParts[2])
                        + " inP=" + String.format("%.2f", DocDetect.dbgParts[3])
                        + " outP=" + String.format("%.2f", DocDetect.dbgParts[5]) + "] " + fmt(pr));'''
if old in s:
    s = s.replace(old, new, 1)
    open(p, 'w', encoding='utf-8').write(s)
    print('DevDebug inP added')
else:
    print('anchor missing')
