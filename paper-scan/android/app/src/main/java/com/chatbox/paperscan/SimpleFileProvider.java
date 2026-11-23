package com.chatbox.paperscan;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileNotFoundException;

/**
 * 极简 FileProvider（不依赖 AndroidX）：把 cache/out 目录下的文件以 content:// 形式
 * 交给微信、PDF 阅读器等其它应用，避免 Android 7+ 的 FileUriExposedException。
 */
public class SimpleFileProvider extends ContentProvider {

    /** 统一的文件目录：cache/out。 */
    public static File outDir(Context c) {
        File d = new File(c.getCacheDir(), "out");
        if (!d.exists()) d.mkdirs();
        return d;
    }

    public static Uri uriFor(Context c, File f) {
        return new Uri.Builder()
                .scheme("content")
                .authority(c.getPackageName() + ".files")
                .appendPath(f.getName())
                .build();
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    private File resolve(Uri uri) {
        String name = uri.getLastPathSegment();
        if (name == null) return null;
        name = name.replace("/", "_").replace("\\", "_").replace("..", "_");
        return new File(outDir(getContext()), name);
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        // 注意：不能要求文件已存在——相机“保存照片”时会用 w 模式打开一个尚不存在的文件
        File f = resolve(uri);
        if (f == null) throw new FileNotFoundException(String.valueOf(uri));
        File parent = f.getParentFile();
        if (parent != null && !parent.exists()) parent.mkdirs();
        int m = ParcelFileDescriptor.parseMode(mode);
        boolean write = (m & ParcelFileDescriptor.MODE_WRITE_ONLY) != 0;
        if (!write && !f.exists()) throw new FileNotFoundException(f.getAbsolutePath());
        try {
            return ParcelFileDescriptor.open(f, m);
        } catch (FileNotFoundException e) {
            throw e;
        }
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection, String[] selectionArgs, String sortOrder) {
        File f = resolve(uri);
        if (f == null || !f.exists()) return null;
        String[] cols = projection != null ? projection
                : new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE};
        MatrixCursor cursor = new MatrixCursor(cols, 1);
        Object[] row = new Object[cols.length];
        for (int i = 0; i < cols.length; i++) {
            if (OpenableColumns.DISPLAY_NAME.equals(cols[i])) row[i] = f.getName();
            else if (OpenableColumns.SIZE.equals(cols[i])) row[i] = f.length();
            else row[i] = null;
        }
        cursor.addRow(row);
        return cursor;
    }

    @Override
    public String getType(Uri uri) {
        String n = uri.getLastPathSegment();
        if (n == null) return "application/octet-stream";
        String l = n.toLowerCase();
        if (l.endsWith(".pdf")) return "application/pdf";
        if (l.endsWith(".zip")) return "application/zip";
        if (l.endsWith(".jpg") || l.endsWith(".jpeg")) return "image/jpeg";
        if (l.endsWith(".png")) return "image/png";
        return "application/octet-stream";
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        return 0;
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        return 0;
    }
}
