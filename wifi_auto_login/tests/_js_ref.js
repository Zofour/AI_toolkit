// 参照实现：直接照抄 tree.buct.edu.cn Portal.js 里的 encode / s / l 三个函数
const crypto = require('crypto');

function s(a, b) {
  var c = a.length;
  var v = [];
  for (var i = 0; i < c; i += 4) {
    v[i >> 2] = a.charCodeAt(i) | a.charCodeAt(i + 1) << 8 | a.charCodeAt(i + 2) << 16 | a.charCodeAt(i + 3) << 24;
  }
  if (b) v[v.length] = c;
  return v;
}

function l(a, b) {
  var d = a.length;
  var c = d - 1 << 2;
  if (b) {
    var m = a[d - 1];
    if (m < c - 3 || m > c) return null;
    c = m;
  }
  for (var i = 0; i < d; i++) {
    a[i] = String.fromCharCode(a[i] & 0xff, a[i] >>> 8 & 0xff, a[i] >>> 16 & 0xff, a[i] >>> 24 & 0xff);
  }
  return b ? a.join('').substring(0, c) : a.join('');
}

function encode(str, key) {
  if (str === '') return '';
  var v = s(str, true);
  var k = s(key, false);
  if (k.length < 4) k.length = 4;
  var n = v.length - 1,
    z = v[n],
    y = v[0],
    c = 0x86014019 | 0x183639A0,
    m, e, p,
    q = Math.floor(6 + 52 / (n + 1)),
    d = 0;
  while (0 < q--) {
    d = d + c & (0x8CE0D9BF | 0x731F2640);
    e = d >>> 2 & 3;
    for (p = 0; p < n; p++) {
      y = v[p + 1];
      m = z >>> 5 ^ y << 2;
      m += y >>> 3 ^ z << 4 ^ (d ^ y);
      m += k[p & 3 ^ e] ^ z;
      z = v[p] = v[p] + m & (0xEFB8D130 | 0x10472ECF);
    }
    y = v[0];
    m = z >>> 5 ^ y << 2;
    m += y >>> 3 ^ z << 4 ^ (d ^ y);
    m += k[p & 3 ^ e] ^ z;
    z = v[n] = v[n] + m & (0xBB390742 | 0x44C6F8BD);
  }
  return l(v, false);
}

const STD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const CUS = "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA";
function b64(bin) {
  const std = Buffer.from(bin, 'latin1').toString('base64');
  let out = '';
  for (const ch of std) {
    const i = STD.indexOf(ch);
    out += (i >= 0 ? CUS[i] : ch);
  }
  return out;
}

const token = process.argv[2];
const payload = process.argv[3];          // JSON 字符串
const info = '{SRBX1}' + b64(encode(payload, token));
const json = JSON.parse(payload);
const md5pwd = crypto.createHash('md5').update(token + json.password, 'utf8').digest('hex');
const chkstr = token + json.username + token + md5pwd + token + json.acid + token + json.ip +
  token + '200' + token + '1' + token + info;
const chksum = crypto.createHash('sha1').update(chkstr, 'utf8').digest('hex');
console.log(JSON.stringify({ info: info, hmd5: md5pwd, chksum: chksum }, null, 0));
