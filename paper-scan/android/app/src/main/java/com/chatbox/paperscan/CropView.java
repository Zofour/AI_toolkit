package com.chatbox.paperscan;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.view.MotionEvent;
import android.view.View;

/** 手动框选：在照片上拖四个角，确定纸张范围。 */
class CropView extends View {

    private Bitmap bmp;
    private final float[] q = new float[8];      // 源图坐标 TL,TR,BR,BL
    private int active = -1;

    private float scale = 1f, offX = 0f, offY = 0f;
    private float viewW = 0f, viewH = 0f;

    private final Paint bmpPaint = new Paint(Paint.FILTER_BITMAP_FLAG);
    private final Paint linePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint shadePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint handlePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint handleRing = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint crossPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint loupeRing = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint loupeBg = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path shadePath = new Path();
    private final Path loupeClip = new Path();

    /** 放大窗里相对当前显示倍率的放大倍数 */
    private static final float MAG = 3.0f;
    private float touchX = -1f, touchY = -1f;

    CropView(Context c) {
        super(c);
        bmpPaint.setFilterBitmap(true);
        linePaint.setStyle(Paint.Style.STROKE);
        linePaint.setStrokeWidth(dp(2.2f));
        linePaint.setColor(0xFF2F6BFF);
        shadePaint.setStyle(Paint.Style.FILL);
        shadePaint.setColor(0x77000000);
        handlePaint.setStyle(Paint.Style.FILL);
        handlePaint.setColor(Color.WHITE);
        handleRing.setStyle(Paint.Style.STROKE);
        handleRing.setStrokeWidth(dp(2.2f));
        handleRing.setColor(0xFF2F6BFF);
        crossPaint.setStyle(Paint.Style.STROKE);
        crossPaint.setStrokeWidth(dp(1.5f));
        crossPaint.setColor(0xFFFF3B30);
        loupeRing.setStyle(Paint.Style.STROKE);
        loupeRing.setStrokeWidth(dp(2.6f));
        loupeRing.setColor(Color.WHITE);
        loupeBg.setStyle(Paint.Style.FILL);
        loupeBg.setColor(0xFF000000);
        setLayerType(LAYER_TYPE_SOFTWARE, null);
    }

    private float dp(float v) {
        return v * getResources().getDisplayMetrics().density;
    }

    void setData(Bitmap b, float[] quad) {
        bmp = b;
        if (quad != null && quad.length == 8) {
            System.arraycopy(quad, 0, q, 0, 8);
        } else {
            // 默认四角内缩 4%
            q[0] = b.getWidth() * 0.04f;
            q[1] = b.getHeight() * 0.04f;
            q[2] = b.getWidth() * 0.96f;
            q[3] = b.getHeight() * 0.04f;
            q[4] = b.getWidth() * 0.96f;
            q[5] = b.getHeight() * 0.96f;
            q[6] = b.getWidth() * 0.04f;
            q[7] = b.getHeight() * 0.96f;
        }
        invalidate();
    }

    float[] getQuad() {
        return q.clone();
    }

    @Override
    protected void onSizeChanged(int w, int h, int ow, int oh) {
        super.onSizeChanged(w, h, ow, oh);
        viewW = w;
        viewH = h;
        if (bmp != null) fit();
    }

    private void fit() {
        float pad = dp(26);
        float availW = Math.max(1, viewW - pad * 2);
        float availH = Math.max(1, viewH - pad * 2);
        scale = Math.min(availW / bmp.getWidth(), availH / bmp.getHeight());
        offX = (viewW - bmp.getWidth() * scale) / 2f;
        offY = (viewH - bmp.getHeight() * scale) / 2f;
    }

    private float vx(float x) {
        return offX + x * scale;
    }

    private float vy(float y) {
        return offY + y * scale;
    }

    @Override
    protected void onDraw(Canvas c) {
        super.onDraw(c);
        if (bmp == null) return;
        if (viewW == 0) {
            viewW = getWidth();
            viewH = getHeight();
        }
        c.drawColor(0xFF111318);
        c.drawBitmap(bmp, null, new android.graphics.RectF(offX, offY,
                offX + bmp.getWidth() * scale, offY + bmp.getHeight() * scale), bmpPaint);

        // 四角之外压暗
        shadePath.reset();
        shadePath.setFillType(Path.FillType.EVEN_ODD);
        shadePath.addRect(0, 0, viewW, viewH, Path.Direction.CW);
        shadePath.moveTo(vx(q[0]), vy(q[1]));
        shadePath.lineTo(vx(q[2]), vy(q[3]));
        shadePath.lineTo(vx(q[4]), vy(q[5]));
        shadePath.lineTo(vx(q[6]), vy(q[7]));
        shadePath.close();
        c.drawPath(shadePath, shadePaint);

        // 边框
        Path p = new Path();
        p.moveTo(vx(q[0]), vy(q[1]));
        p.lineTo(vx(q[2]), vy(q[3]));
        p.lineTo(vx(q[4]), vy(q[5]));
        p.lineTo(vx(q[6]), vy(q[7]));
        p.close();
        c.drawPath(p, linePaint);

        // 四个角把手
        float r = dp(11);
        for (int i = 0; i < 4; i++) {
            float x = vx(q[i * 2]), y = vy(q[i * 2 + 1]);
            c.drawCircle(x, y, r, handlePaint);
            c.drawCircle(x, y, r, handleRing);
        }

        // 拖角时的放大镜 + 十字准星
        drawLoupe(c);
    }

    /** 放大镜：默认在左上角，若手指在左上区域则翻到右上角，避免挡住手指。 */
    private void drawLoupe(Canvas c) {
        if (active < 0 || bmp == null) return;
        float r = dp(56);
        float margin = r + dp(10);
        boolean fingerUpperLeft = touchX >= 0 && touchX < viewW * 0.5f && touchY < viewH * 0.5f;
        float cx = fingerUpperLeft ? viewW - margin : margin;
        float cy = margin;

        float hx = q[active * 2], hy = q[active * 2 + 1];
        float k = scale * MAG;
        if (k < 1.5f) k = 1.5f;

        c.save();
        loupeClip.reset();
        loupeClip.addCircle(cx, cy, r, Path.Direction.CW);
        c.clipPath(loupeClip);
        c.drawCircle(cx, cy, r, loupeBg);
        c.translate(cx, cy);
        c.scale(k, k);
        c.translate(-hx, -hy);
        c.drawBitmap(bmp, 0, 0, bmpPaint);
        c.restore();

        // 十字准星
        c.drawLine(cx - dp(18), cy, cx + dp(18), cy, crossPaint);
        c.drawLine(cx, cy - dp(18), cx, cy + dp(18), crossPaint);
        c.drawCircle(cx, cy, dp(3f), crossPaint);

        // 外圈（白圈 + 深色投影边）
        loupeRing.setColor(0x66000000);
        c.drawCircle(cx, cy, r + dp(2f), loupeRing);
        loupeRing.setColor(Color.WHITE);
        c.drawCircle(cx, cy, r, loupeRing);
    }

    @Override
    public boolean onTouchEvent(MotionEvent e) {
        if (bmp == null) return false;
        float x = e.getX(), y = e.getY();
        switch (e.getActionMasked()) {
            case MotionEvent.ACTION_DOWN: {
                float best = dp(44);
                active = -1;
                for (int i = 0; i < 4; i++) {
                    float dx = vx(q[i * 2]) - x, dy = vy(q[i * 2 + 1]) - y;
                    float d = (float) Math.sqrt(dx * dx + dy * dy);
                    if (d < best) {
                        best = d;
                        active = i;
                    }
                }
                touchX = x;
                touchY = y;
                if (active >= 0) invalidate();
                return active >= 0;
            }
            case MotionEvent.ACTION_MOVE: {
                if (active < 0) return false;
                touchX = x;
                touchY = y;
                float bx = (x - offX) / scale;
                float by = (y - offY) / scale;
                bx = Math.max(0, Math.min(bmp.getWidth() - 1, bx));
                by = Math.max(0, Math.min(bmp.getHeight() - 1, by));
                q[active * 2] = bx;
                q[active * 2 + 1] = by;
                invalidate();
                return true;
            }
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL: {
                active = -1;
                invalidate();
                return true;
            }
        }
        return false;
    }
}
