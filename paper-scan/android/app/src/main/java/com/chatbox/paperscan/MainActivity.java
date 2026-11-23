package com.chatbox.paperscan;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Dialog;
import android.content.ClipData;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.widget.FrameLayout;
import android.widget.GridLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.List;
import java.util.Locale;

public class MainActivity extends Activity {

    private static final int REQ_PICK = 1001;
    private static final int REQ_CAPTURE = 1002;
    private static final int MAX_SIDE = 2400;

    private static class Item {
        File file;      // 处理成品（JPG）
        File orig;      // 原图副本，用于重做/手动框选
        Bitmap thumb;
        boolean cropped;
        float[] quad;   // 源图坐标系下的四角（TL,TR,BR,BL），无则 null

        Item(File f, File o, Bitmap t, boolean c, float[] q) {
            file = f;
            orig = o;
            thumb = t;
            cropped = c;
            quad = q;
        }
    }

    private final List<Item> items = new ArrayList<>();
    private final Handler ui = new Handler(Looper.getMainLooper());

    private GridLayout grid;
    private View emptyView;
    private TextView btnAdd, btnExport, btnCamera;
    private View overlay;
    private TextView overlayText;
    private File workDir;
    private File cameraFile;
    private Uri cameraUri;
    private boolean busy;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        workDir = new File(getCacheDir(), "work");
        workDir.mkdirs();
        SimpleFileProvider.outDir(this);
        clearDir(workDir);
        clearDir(SimpleFileProvider.outDir(this));

        grid = findViewById(R.id.grid);
        emptyView = findViewById(R.id.emptyView);
        btnAdd = findViewById(R.id.btnAdd);
        btnExport = findViewById(R.id.btnExport);
        btnCamera = findViewById(R.id.btnCamera);
        overlay = findViewById(R.id.overlay);
        overlayText = findViewById(R.id.overlayText);

        btnAdd.setOnClickListener(v -> pickImages());
        btnExport.setOnClickListener(v -> {
            if (busy || items.isEmpty()) return;
            showExportSheet();
        });
        btnCamera.setOnClickListener(v -> takePhoto());

        refreshUi();
        handleIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleIntent(intent);
    }

    private void handleIntent(Intent it) {
        if (it == null) return;
        String act = it.getAction();
        if (Intent.ACTION_SEND.equals(act)) {
            Uri u = it.getParcelableExtra(Intent.EXTRA_STREAM);
            if (u != null) addUris(Collections.singletonList(u));
        } else if (Intent.ACTION_SEND_MULTIPLE.equals(act)) {
            ArrayList<Uri> list = it.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (list != null && !list.isEmpty()) addUris(list);
        }
    }

    // ------------------------------------------------------------ 取图

    private void pickImages() {
        if (busy) return;
        Intent i = new Intent(Intent.ACTION_GET_CONTENT);
        i.setType("image/*");
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        try {
            startActivityForResult(Intent.createChooser(i, "选择要扫描的照片"), REQ_PICK);
        } catch (Throwable t) {
            toast("无法打开相册：" + t.getMessage());
        }
    }

    private void takePhoto() {
        if (busy) return;
        try {
            File f = new File(ExportUtil.outDir(this), "cap_" + System.currentTimeMillis() + ".jpg");
            cameraFile = f;
            cameraUri = SimpleFileProvider.uriFor(this, f);
            Intent i = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            i.putExtra(MediaStore.EXTRA_OUTPUT, cameraUri);
            i.setClipData(ClipData.newRawUri("out", cameraUri));
            i.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivityForResult(i, REQ_CAPTURE);
        } catch (Throwable t) {
            toast("无法打开相机：" + t.getMessage());
        }
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req == REQ_PICK) {
            if (res != RESULT_OK || data == null) return;
            List<Uri> uris = new ArrayList<>();
            ClipData cd = data.getClipData();
            if (cd != null) {
                for (int i = 0; i < cd.getItemCount(); i++) uris.add(cd.getItemAt(i).getUri());
            } else if (data.getData() != null) {
                uris.add(data.getData());
            }
            addUris(uris);
        } else if (req == REQ_CAPTURE) {
            if (res == RESULT_OK && cameraUri != null) {
                if (cameraFile != null && cameraFile.exists() && cameraFile.length() > 1024) {
                    addUris(Collections.singletonList(cameraUri));
                } else {
                    toast("相机没有保存成功，请改用「添加照片」");
                    if (cameraFile != null) cameraFile.delete();
                }
            }
        }
    }

    // ------------------------------------------------------------ 处理

    private void addUris(final List<Uri> uris) {
        if (uris == null || uris.isEmpty()) return;
        busy = true;
        refreshUi();
        showOverlay("正在识别纸张…");
        new Thread(() -> {
            int idx = 0;
            for (final Uri u : uris) {
                idx++;
                final int cur = idx, total = uris.size();
                ui.post(() -> overlayText.setText("正在处理  " + cur + " / " + total));
                try {
                    Item it = processUri(u, idx);
                    if (it != null) ui.post(() -> {
                        items.add(it);
                        refreshUi();
                    });
                } catch (Throwable t) {
                    final String msg = t.getClass().getSimpleName() + ": " + t.getMessage();
                    ui.post(() -> toast("有一张没处理成功：" + msg));
                }
            }
            ui.post(() -> {
                busy = false;
                hideOverlay();
                refreshUi();
            });
        }).start();
    }

    private Item processUri(Uri u, int idx) throws Exception {
        Bitmap src = decodeUri(u, MAX_SIDE);
        if (src == null) return null;
        int w = src.getWidth(), h = src.getHeight();

        // 存一份原图副本（用于"整图重做"）
        File orig = new File(workDir, "orig_" + System.currentTimeMillis() + "_" + idx + ".jpg");
        FileOutputStream fos = new FileOutputStream(orig);
        src.compress(Bitmap.CompressFormat.JPEG, 92, fos);
        fos.close();

        int[] px = new int[w * h];
        src.getPixels(px, 0, w, 0, 0, w, h);
        src.recycle();

        PaperScanCore.Result r = PaperScanCore.process(px, w, h);
        return saveResult(r, orig);
    }

    private Item saveResult(PaperScanCore.Result r, File orig) throws Exception {
        Bitmap out = Bitmap.createBitmap(r.pixels, r.width, r.height, Bitmap.Config.ARGB_8888);
        File f = new File(workDir, "scan_" + System.currentTimeMillis() + ".jpg");
        FileOutputStream fos = new FileOutputStream(f);
        out.compress(Bitmap.CompressFormat.JPEG, 92, fos);
        fos.close();
        Bitmap thumb = makeThumb(out, 760);
        if (thumb != out) out.recycle();
        return new Item(f, orig, thumb, r.detected, r.quad);
    }

    private Bitmap decodeUri(Uri uri, int maxSide) throws Exception {
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inJustDecodeBounds = true;
        InputStream is = getContentResolver().openInputStream(uri);
        try {
            BitmapFactory.decodeStream(is, null, o);
        } finally {
            if (is != null) is.close();
        }
        if (o.outWidth <= 0 || o.outHeight <= 0) return null;
        int sample = 1;
        while (Math.max(o.outWidth, o.outHeight) / sample > maxSide) sample *= 2;
        BitmapFactory.Options o2 = new BitmapFactory.Options();
        o2.inSampleSize = sample;
        o2.inPreferredConfig = Bitmap.Config.ARGB_8888;
        is = getContentResolver().openInputStream(uri);
        try {
            return BitmapFactory.decodeStream(is, null, o2);
        } finally {
            if (is != null) is.close();
        }
    }

    private Bitmap makeThumb(Bitmap src, int maxSide) {
        float scale = (float) maxSide / Math.max(src.getWidth(), src.getHeight());
        if (scale >= 1f) return src;
        int w = Math.max(1, Math.round(src.getWidth() * scale));
        int h = Math.max(1, Math.round(src.getHeight() * scale));
        return Bitmap.createScaledBitmap(src, w, h, true);
    }

    /** 不做纸张裁剪，直接整图增强（识别失败/识别错时的手动兜底）。 */
    private void redoWholeImage(final int index) {
        final Item it = items.get(index);
        if (it.orig == null || !it.orig.exists()) {
            toast("原图已不在，无法重做");
            return;
        }
        busy = true;
        refreshUi();
        showOverlay("正在重新处理…");
        new Thread(() -> {
            try {
                Bitmap bmp = BitmapFactory.decodeFile(it.orig.getAbsolutePath());
                int w = bmp.getWidth(), h = bmp.getHeight();
                int[] px = new int[w * h];
                bmp.getPixels(px, 0, w, 0, 0, w, h);
                bmp.recycle();
                PaperScanCore.Result r = PaperScanCore.processNoCrop(px, w, h);
                final Item fresh = saveResult(r, it.orig);
                ui.post(() -> {
                    Bitmap old = items.get(index).thumb;
                    items.set(index, fresh);
                    if (old != null && !old.isRecycled()) old.recycle();
                    busy = false;
                    hideOverlay();
                    refreshUi();
                });
            } catch (Throwable t) {
                final String msg = t.getMessage();
                ui.post(() -> {
                    busy = false;
                    hideOverlay();
                    refreshUi();
                    toast("重做失败：" + msg);
                });
            }
        }).start();
    }

    // ------------------------------------------------------------ 界面

    private void refreshUi() {
        grid.removeAllViews();
        for (int i = 0; i < items.size(); i++) grid.addView(buildCell(i));
        if (items.size() % 2 == 1) {
            // 占位格：避免最后一张被拉成整行宽
            View spacer = new View(this);
            GridLayout.LayoutParams lp = new GridLayout.LayoutParams();
            lp.width = 0;
            lp.height = dp(10);
            lp.columnSpec = GridLayout.spec(GridLayout.UNDEFINED, 1f);
            spacer.setLayoutParams(lp);
            grid.addView(spacer);
        }
        emptyView.setVisibility(items.isEmpty() ? View.VISIBLE : View.GONE);
        if (items.isEmpty()) {
            btnExport.setText("导出");
            btnExport.setTextColor(0xFFB9BFCC);
            btnExport.setBackgroundResource(R.drawable.bg_btn_ghost);
        } else {
            btnExport.setText("导出  " + items.size() + " 张");
            btnExport.setTextColor(0xFF2F6BFF);
            btnExport.setBackgroundResource(R.drawable.bg_btn_soft);
        }
    }

    private View buildCell(final int index) {
        final Item it = items.get(index);

        FrameLayout card = new FrameLayout(this);
        GridLayout.LayoutParams lp = new GridLayout.LayoutParams();
        lp.width = 0;
        lp.height = ViewGroup.LayoutParams.WRAP_CONTENT;
        lp.columnSpec = GridLayout.spec(GridLayout.UNDEFINED, 1f);
        lp.setMargins(dp(6), dp(6), dp(6), dp(6));
        card.setLayoutParams(lp);

        ImageView iv = new ImageView(this);
        FrameLayout.LayoutParams ilp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(212));
        iv.setLayoutParams(ilp);
        iv.setScaleType(ImageView.ScaleType.FIT_CENTER);
        iv.setBackgroundResource(R.drawable.bg_thumb);
        iv.setClipToOutline(true);
        iv.setImageBitmap(it.thumb);
        card.addView(iv);

        TextView del = new TextView(this);
        FrameLayout.LayoutParams dlp = new FrameLayout.LayoutParams(dp(26), dp(26),
                Gravity.TOP | Gravity.RIGHT);
        dlp.setMargins(0, dp(6), dp(6), 0);
        del.setLayoutParams(dlp);
        del.setBackgroundResource(R.drawable.bg_del);
        del.setText("×");
        del.setTextColor(Color.WHITE);
        del.setTextSize(15);
        del.setGravity(Gravity.CENTER);
        del.setOnClickListener(v -> confirmDelete(index));
        card.addView(del);

        TextView badge = new TextView(this);
        FrameLayout.LayoutParams blp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM | Gravity.LEFT);
        blp.setMargins(dp(7), 0, 0, dp(7));
        badge.setLayoutParams(blp);
        badge.setBackgroundResource(R.drawable.bg_badge);
        badge.setText(it.cropped ? "已裁纸" : "整图");
        badge.setTextColor(Color.WHITE);
        badge.setTextSize(10);
        badge.setPadding(dp(7), dp(3), dp(7), dp(3));
        card.addView(badge);

        card.setOnClickListener(v -> showPreview(index));
        return card;
    }

    private void confirmDelete(final int index) {
        new AlertDialog.Builder(this)
                .setTitle("删除这张？")
                .setMessage("只会从当前扫描件里移除。")
                .setPositiveButton("删除", (d, w) -> {
                    Item it = items.remove(index);
                    if (it != null) {
                        if (it.thumb != null) it.thumb.recycle();
                        it.file.delete();
                    }
                    refreshUi();
                })
                .setNegativeButton("取消", null)
                .show();
    }

    private void showPreview(final int index) {
        final Item it = items.get(index);
        final Dialog d = new Dialog(this);
        d.requestWindowFeature(Window.FEATURE_NO_TITLE);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundResource(R.drawable.bg_panel);
        int pad = dp(14);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("第 " + (index + 1) + " 张" + (it.cropped ? "（已自动裁纸）" : "（整图）"));
        title.setTextSize(15);
        title.setTextColor(0xFF14161C);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        root.addView(title);

        ImageView iv = new ImageView(this);
        LinearLayout.LayoutParams ilp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        ilp.topMargin = dp(10);
        ilp.bottomMargin = dp(10);
        iv.setLayoutParams(ilp);
        iv.setScaleType(ImageView.ScaleType.FIT_CENTER);
        iv.setBackgroundResource(R.drawable.bg_thumb);
        iv.setImageBitmap(it.thumb);
        root.addView(iv);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        TextView crop = mkWideButton("手动框选", false);
        crop.setOnClickListener(v -> {
            d.dismiss();
            showCropDialog(index);
        });
        TextView redo = mkWideButton("整图重做", false);
        redo.setOnClickListener(v -> {
            d.dismiss();
            redoWholeImage(index);
        });
        TextView close = mkWideButton("关闭", true);
        close.setOnClickListener(v -> d.dismiss());
        LinearLayout.LayoutParams rp = new LinearLayout.LayoutParams(0, dp(46), 1f);
        row.addView(crop, rp);
        LinearLayout.LayoutParams rp1 = new LinearLayout.LayoutParams(0, dp(46), 1f);
        rp1.leftMargin = dp(8);
        row.addView(redo, rp1);
        LinearLayout.LayoutParams rp2 = new LinearLayout.LayoutParams(0, dp(46), 1f);
        rp2.leftMargin = dp(8);
        row.addView(close, rp2);
        root.addView(row);

        d.setContentView(root);
        d.show();
        Window w = d.getWindow();
        if (w != null) {
            w.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
            DisplayMetrics dm = getResources().getDisplayMetrics();
            w.setLayout((int) (dm.widthPixels * 0.92f), (int) (dm.heightPixels * 0.82f));
        }
    }

    // ------------------------------------------------------------ 手动框选

    private void showCropDialog(final int index) {
        final Item it = items.get(index);
        if (it.orig == null || !it.orig.exists()) {
            toast("原图已不在，无法手动框选");
            return;
        }
        final Bitmap src;
        try {
            src = BitmapFactory.decodeFile(it.orig.getAbsolutePath());
        } catch (Throwable t) {
            toast("读取原图失败");
            return;
        }
        if (src == null) {
            toast("读取原图失败");
            return;
        }

        final Dialog d = new Dialog(this);
        d.requestWindowFeature(Window.FEATURE_NO_TITLE);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundResource(R.drawable.bg_panel);
        int pad = dp(10);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("拖动四个角，让它贴住纸的边");
        title.setTextSize(14);
        title.setTextColor(0xFF14161C);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setPadding(dp(4), 0, 0, dp(8));
        root.addView(title);

        final CropView cv = new CropView(this);
        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        cv.setLayoutParams(clp);
        cv.setData(src, it.quad);
        root.addView(cv);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams rowLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        rowLp.topMargin = dp(8);
        TextView cancel = mkWideButton("取消", false);
        cancel.setOnClickListener(v -> {
            if (!src.isRecycled()) src.recycle();
            d.dismiss();
        });
        TextView ok = mkWideButton("确定裁切", true);
        ok.setOnClickListener(v -> {
            float[] q = cv.getQuad();
            d.dismiss();
            applyManualCrop(index, src, q);
        });
        LinearLayout.LayoutParams b1 = new LinearLayout.LayoutParams(0, dp(48), 1f);
        row.addView(cancel, b1);
        LinearLayout.LayoutParams b2 = new LinearLayout.LayoutParams(0, dp(48), 1f);
        b2.leftMargin = dp(10);
        row.addView(ok, b2);
        root.addView(row, rowLp);

        d.setContentView(root);
        d.show();
        Window w = d.getWindow();
        if (w != null) {
            w.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
            DisplayMetrics dm = getResources().getDisplayMetrics();
            w.setLayout((int) (dm.widthPixels * 0.96f), (int) (dm.heightPixels * 0.86f));
        }
    }

    private void applyManualCrop(final int index, final Bitmap src, final float[] quad) {
        final Item old = items.get(index);
        busy = true;
        refreshUi();
        showOverlay("正在裁切…");
        new Thread(() -> {
            try {
                int w = src.getWidth(), h = src.getHeight();
                int[] px = new int[w * h];
                src.getPixels(px, 0, w, 0, 0, w, h);
                src.recycle();
                PaperScanCore.Result r = PaperScanCore.processQuad(px, w, h, quad);
                final Item fresh = saveResult(r, old.orig);
                File oldFile = old.file;
                Bitmap oldThumb = old.thumb;
                ui.post(() -> {
                    items.set(index, fresh);
                    if (oldThumb != null && !oldThumb.isRecycled()) oldThumb.recycle();
                    if (oldFile != null) oldFile.delete();
                    busy = false;
                    hideOverlay();
                    refreshUi();
                });
            } catch (Throwable t) {
                final String msg = t.getClass().getSimpleName() + ": " + t.getMessage();
                ui.post(() -> {
                    busy = false;
                    hideOverlay();
                    refreshUi();
                    toast("裁切失败：" + msg);
                });
            }
        }).start();
    }

    // ------------------------------------------------------------ 导出

    private void showExportSheet() {
        final String[] opts = {"导出为 PDF（多页文档）", "导出为 ZIP 压缩包（JPG 图片）"};
        new AlertDialog.Builder(this)
                .setTitle("导出 " + items.size() + " 张扫描件")
                .setItems(opts, (d, which) -> doExport(which == 0))
                .setNegativeButton("取消", null)
                .show();
    }

    private void doExport(final boolean pdf) {
        busy = true;
        refreshUi();
        showOverlay(pdf ? "正在生成 PDF…" : "正在打包 ZIP…");
        new Thread(() -> {
            try {
                List<File> files = new ArrayList<>();
                for (Item it : items) files.add(it.file);
                String stamp = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(new Date());
                String base = "扫描件_" + stamp;
                final File out = pdf ? ExportUtil.exportPdf(this, files, base)
                        : ExportUtil.exportZip(this, files, base);
                ui.post(() -> {
                    busy = false;
                    hideOverlay();
                    refreshUi();
                    showResult(out);
                });
            } catch (Throwable t) {
                final String msg = t.getClass().getSimpleName() + ": " + t.getMessage();
                ui.post(() -> {
                    busy = false;
                    hideOverlay();
                    refreshUi();
                    toast("导出失败：" + msg);
                });
            }
        }).start();
    }

    private void showResult(final File out) {
        final Dialog d = new Dialog(this);
        d.requestWindowFeature(Window.FEATURE_NO_TITLE);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundResource(R.drawable.bg_panel);
        int pad = dp(20);
        root.setPadding(pad, pad, pad, dp(12));

        TextView t1 = new TextView(this);
        t1.setText("导出成功");
        t1.setTextSize(18);
        t1.setTextColor(0xFF14161C);
        t1.setTypeface(Typeface.DEFAULT_BOLD);
        root.addView(t1);

        TextView t2 = new TextView(this);
        t2.setText(out.getName() + "\n" + humanSize(out.length()) + " · 共 " + items.size() + " 张");
        t2.setTextSize(13);
        t2.setTextColor(0xFF5B6273);
        t2.setLineSpacing(dp(3), 1f);
        LinearLayout.LayoutParams p2 = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        p2.topMargin = dp(8);
        p2.bottomMargin = dp(16);
        root.addView(t2, p2);

        TextView wechat = mkWideButton("分享到微信", true);
        wechat.setOnClickListener(v -> {
            boolean ok = ExportUtil.shareToWeChat(this, out);
            if (!ok) {
                toast("没找到微信，改用系统分享");
                ExportUtil.shareChooser(this, out);
            }
            d.dismiss();
        });
        LinearLayout.LayoutParams wp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(50));
        root.addView(wechat, wp);

        TextView more = mkWideButton("其他应用分享", false);
        more.setOnClickListener(v -> {
            ExportUtil.shareChooser(this, out);
            d.dismiss();
        });
        LinearLayout.LayoutParams mp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48));
        mp.topMargin = dp(10);
        root.addView(more, mp);

        TextView save = mkWideButton("保存到手机「下载」目录", false);
        save.setOnClickListener(v -> {
            try {
                String where = ExportUtil.saveToDownloads(this, out, out.getName());
                toast("已保存到：" + where);
            } catch (Throwable t) {
                toast("保存失败：" + t.getMessage());
            }
            d.dismiss();
        });
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48));
        sp.topMargin = dp(10);
        root.addView(save, sp);

        TextView open = mkWideButton("打开预览", false);
        open.setOnClickListener(v -> ExportUtil.open(this, out));
        LinearLayout.LayoutParams op = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48));
        op.topMargin = dp(10);
        root.addView(open, op);

        TextView close = new TextView(this);
        close.setText("关  闭");
        close.setTextSize(15);
        close.setTextColor(0xFF5B6273);
        close.setGravity(Gravity.CENTER);
        close.setPadding(0, dp(14), 0, dp(4));
        close.setOnClickListener(v -> d.dismiss());
        root.addView(close);

        d.setContentView(root);
        d.show();
        Window w = d.getWindow();
        if (w != null) {
            w.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
            DisplayMetrics dm = getResources().getDisplayMetrics();
            w.setLayout((int) (dm.widthPixels * 0.9f), ViewGroup.LayoutParams.WRAP_CONTENT);
        }
    }

    // ------------------------------------------------------------ 小工具

    private TextView mkWideButton(String text, boolean primary) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextSize(15);
        tv.setGravity(Gravity.CENTER);
        tv.setTypeface(Typeface.DEFAULT_BOLD);
        if (primary) {
            tv.setBackgroundResource(R.drawable.bg_btn_primary);
            tv.setTextColor(Color.WHITE);
        } else {
            tv.setBackgroundResource(R.drawable.bg_btn_ghost);
            tv.setTextColor(0xFF14161C);
        }
        tv.setClickable(true);
        tv.setFocusable(true);
        return tv;
    }

    private void showOverlay(String msg) {
        overlayText.setText(msg);
        overlay.setVisibility(View.VISIBLE);
        overlay.setOnClickListener(null);
    }

    private void hideOverlay() {
        overlay.setVisibility(View.GONE);
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private static String humanSize(long bytes) {
        if (bytes >= 1024 * 1024) return String.format(Locale.CHINA, "%.2f MB", bytes / 1048576.0);
        if (bytes >= 1024) return String.format(Locale.CHINA, "%.0f KB", bytes / 1024.0);
        return bytes + " B";
    }

    private static void clearDir(File dir) {
        File[] fs = dir.listFiles();
        if (fs == null) return;
        for (File f : fs) {
            if (f.isFile()) f.delete();
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        for (Item it : items) {
            if (it.thumb != null) it.thumb.recycle();
        }
        items.clear();
    }
}
