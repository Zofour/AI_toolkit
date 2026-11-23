package com.chatbox.paperscan;

import android.app.Activity;
import android.content.ClipData;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.pdf.PdfDocument;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.List;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** 导出（PDF / ZIP）与分享（微信等）。 */
final class ExportUtil {

    private ExportUtil() {
    }

    static File outDir(Context c) {
        return SimpleFileProvider.outDir(c);
    }

    // ---------------------------------------------------------------- PDF
    static File exportPdf(Context ctx, List<File> files, String baseName) throws IOException {
        PdfDocument doc = new PdfDocument();
        int page = 1;
        for (File f : files) {
            Bitmap bmp = decodeForPdf(f);
            if (bmp == null) continue;
            int w = bmp.getWidth(), h = bmp.getHeight();
            float longSide = 842f;   // A4 长边（pt）
            int pw, ph;
            if (w >= h) {
                pw = Math.round(longSide);
                ph = Math.max(1, Math.round(longSide * h / (float) w));
            } else {
                ph = Math.round(longSide);
                pw = Math.max(1, Math.round(longSide * w / (float) h));
            }
            PdfDocument.PageInfo info = new PdfDocument.PageInfo.Builder(pw, ph, page).create();
            PdfDocument.Page p = doc.startPage(info);
            Paint paint = new Paint(Paint.FILTER_BITMAP_FLAG | Paint.ANTI_ALIAS_FLAG);
            p.getCanvas().drawBitmap(bmp, null, new Rect(0, 0, pw, ph), paint);
            doc.finishPage(p);
            bmp.recycle();
            page++;
        }
        if (page == 1) {
            doc.close();
            throw new IOException("没有可导出的页面");
        }
        File out = new File(outDir(ctx), baseName + ".pdf");
        FileOutputStream fos = new FileOutputStream(out);
        doc.writeTo(fos);
        fos.flush();
        fos.close();
        doc.close();
        return out;
    }

    private static Bitmap decodeForPdf(File f) {
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(f.getAbsolutePath(), o);
        if (o.outWidth <= 0) return null;
        int sample = 1;
        while (Math.max(o.outWidth, o.outHeight) / sample > 2000) sample *= 2;
        BitmapFactory.Options o2 = new BitmapFactory.Options();
        o2.inSampleSize = sample;
        o2.inPreferredConfig = Bitmap.Config.ARGB_8888;
        return BitmapFactory.decodeFile(f.getAbsolutePath(), o2);
    }

    // ---------------------------------------------------------------- ZIP
    static File exportZip(Context ctx, List<File> files, String baseName) throws IOException {
        File out = new File(outDir(ctx), baseName + ".zip");
        ZipOutputStream zos = new ZipOutputStream(new FileOutputStream(out));
        byte[] buf = new byte[64 * 1024];
        int i = 1;
        for (File f : files) {
            String name = String.format(Locale.US, "扫描_%03d.jpg", i++);
            zos.putNextEntry(new ZipEntry(name));
            InputStream is = new FileInputStream(f);
            int n;
            while ((n = is.read(buf)) > 0) zos.write(buf, 0, n);
            is.close();
            zos.closeEntry();
        }
        zos.close();
        return out;
    }

    // ---------------------------------------------------------------- 分享
    static boolean shareToWeChat(Activity a, File f) {
        // 1) 直达微信「发送给朋友」
        if (send(a, f, "com.tencent.mm", "com.tencent.mm.ui.tools.ShareImgUI")) return true;
        // 2) 只限定微信（换版本/改动时的兼容方案）
        return send(a, f, "com.tencent.mm", null);
    }

    static boolean shareTo(Activity a, File f, String pkg) {
        return send(a, f, pkg, null);
    }

    private static boolean send(Activity a, File f, String pkg, String cls) {
        if (f == null || !f.exists()) return false;
        Uri u = SimpleFileProvider.uriFor(a, f);
        Intent i = new Intent(Intent.ACTION_SEND);
        i.setType(mimeOf(f));
        i.putExtra(Intent.EXTRA_STREAM, u);
        i.putExtra(Intent.EXTRA_SUBJECT, f.getName());
        i.setClipData(ClipData.newUri(a.getContentResolver(), f.getName(), u));
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        if (pkg != null && cls != null) {
            i.setComponent(new android.content.ComponentName(pkg, cls));
        } else if (pkg != null) {
            i.setPackage(pkg);
        }
        try {
            a.startActivity(i);
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    static void shareChooser(Activity a, File f) {
        Uri u = SimpleFileProvider.uriFor(a, f);
        Intent i = new Intent(Intent.ACTION_SEND);
        i.setType(mimeOf(f));
        i.putExtra(Intent.EXTRA_STREAM, u);
        i.setClipData(ClipData.newUri(a.getContentResolver(), f.getName(), u));
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            a.startActivity(Intent.createChooser(i, "分享到"));
        } catch (Throwable t) {
            // ignore
        }
    }

    static void open(Activity a, File f) {
        Uri u = SimpleFileProvider.uriFor(a, f);
        Intent i = new Intent(Intent.ACTION_VIEW);
        i.setDataAndType(u, mimeOf(f));
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            a.startActivity(i);
        } catch (Throwable t) {
            // ignore
        }
    }

    static String mimeOf(File f) {
        String n = f.getName().toLowerCase(Locale.US);
        if (n.endsWith(".pdf")) return "application/pdf";
        if (n.endsWith(".zip")) return "application/zip";
        return "image/jpeg";
    }

    // ---------------------------------------------------------------- 保存到下载目录
    static String saveToDownloads(Context c, File f, String displayName) throws IOException {
        if (Build.VERSION.SDK_INT >= 29) {
            ContentValues v = new ContentValues();
            v.put(MediaStore.MediaColumns.DISPLAY_NAME, displayName);
            v.put(MediaStore.MediaColumns.MIME_TYPE, mimeOf(f));
            v.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/文档扫描");
            Uri uri = c.getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
            if (uri == null) throw new IOException("无法创建下载文件");
            OutputStream os = c.getContentResolver().openOutputStream(uri);
            if (os == null) throw new IOException("无法写入下载文件");
            copy(f, os);
            return "下载/文档扫描/" + displayName;
        }
        File dir = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "文档扫描");
        if (!dir.exists()) dir.mkdirs();
        File dst = new File(dir, displayName);
        FileOutputStream os = new FileOutputStream(dst);
        copy(f, os);
        return dst.getAbsolutePath();
    }

    private static void copy(File src, OutputStream os) throws IOException {
        InputStream is = new FileInputStream(src);
        byte[] buf = new byte[64 * 1024];
        int n;
        try {
            while ((n = is.read(buf)) > 0) os.write(buf, 0, n);
            os.flush();
        } finally {
            try {
                is.close();
            } catch (IOException ignored) {
            }
            try {
                os.close();
            } catch (IOException ignored) {
            }
        }
    }
}
