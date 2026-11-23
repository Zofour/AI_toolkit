# -*- coding: utf-8 -*-
"""
K230 / CanMV —— 真实场景一条龙：【板端直出卡片 v4 · 路线甲】
预览 -> KEY1 拍照 -> 抠图 -> **人脸检测(构图+连通块)** -> 轮廓平滑 -> 风格化 -> 换背景 -> 描边
     -> 贴装饰(四周贴纸 + 底部校徽校名) -> 存盘

v4 新增（修“背景物品被当成人”）：
  · YuNet 人脸检测（/sdcard/kmodel/yunet_640.kmodel，接口来自 CanMV 官方例程
    face_detect_yunet.py，**不需要 prior_data 锚点文件**）。
  · 构图改为**以人脸为中心**：人脸水平居中、放在卡片 FACE_ANCHOR_Y 高度处。
  · 抠像后**只保留人脸所在的那一个连通 mask**（keep_face_component），
    其余连通块（背景杂物/影子）全删；没人脸时回退为“保留最大连通块”。
  · 全程依然板端实现，仍远低于 60s。

沿用 v3：背景为动漫插画 JPEG（板上解码）、装饰层自动回退、分割 mask 限定人像、
深色描边、只用 style_s1 模型 + 边缘线稿漫画化后处理。

v2 相对 v1 的核心改动（P0：修"发白雾"）
  1) 风格模型：不再用 style_u8fix（那是复现不了的"重绘"学生网，输出整张灰白雾），
     改用 style_s1（确定性滤镜版，保留本色 + 平涂 + 线稿）。单一模型，一次推理。
  2) 去掉 REPAINT_K 过冲：col = model_out（不再 i + 1.4*(a-i) 放大偏差）。
  3) 后处理换成"漫画化"链：保边平涂 -> 色阶 + 提亮 -> 边缘线稿加深 -> 饱和。
     线稿只用"边缘图"（|亮度-邻域均值|），所以只压真正的线，不会把暗衣服/阴影一起压黑。
  4) 描边颜色由纯白改成深色（参考图的人物是黑/深描边，白描边会显"贴纸感"）。

装饰层仍由 PC 端生成（stickers_card.py --overlay），放 /sdcard/deco/deco_<背景名>.bin，
608x768 RGBA8888：RGB = 不预乘的贴纸颜色，A = 软 alpha。

用法：CanMV IDE 打开本文件 -> 运行。KEY1(GPIO61) 触发一次。
【自动测试开关】/sdcard/temp/_autocap 内容 = 延迟秒数 -> 自动抓拍一次后退出；
  内容以 'off' 开头 -> 走离线自检（不碰相机，用 /sdcard/temp/picture_125.jpg）。
"""

from libs.PipeLine import PipeLine, ScopedTiming
from libs.AIBase import AIBase
from libs.AI2D import Ai2d
import os
from media.media import *
from time import *
import nncase_runtime as nn
import ulab.numpy as np
import time
import utime
import image
import gc
import aidemo
from machine import Pin, FPIOA, UART
import jpegenc

# ============================== 配置区 ==============================
STYLE_MODEL = "/sdcard/kmodel/style_s1.kmodel"   # 确定性滤镜版学生网（保留本色+平涂+线稿）

# ---- 漫画化后处理（v2 新增，都是板端 ulab 向量化运算）----
LEVELS = (0, 250)          # 色阶拉伸（去灰）；(0,255) = 关闭
CONTRAST = 1.04            # 对比度（1.0 = 关闭）
BRIGHT = 10                # 提亮（0 = 关闭）
SAT = 1.15                 # 饱和度（1.0 = 关闭）
LINE_K = 0.62              # 线稿加深强度 0~1（0 = 关闭）。只压"边缘"，不压衣服/阴影
LINE_GAIN = 2.4            # 线稿响应增益（越大线越硬）
LINE_DILATE = 1            # 线宽加粗：边缘图膨胀几像素（0 = 不加粗）
EDGE_LO = 6                # 边缘死区：边缘强度低于该值不算线（去噪点）
FLAT_THR = 28              # 保边平涂阈值：|亮度-邻域均值| < 该值就平掉（0 = 关闭）
WB = (0.97, 1.00, 1.05)    # 白平衡增益(R,G,B)：相机偏暖时降红/升蓝（(1,1,1) = 关闭）

BG_DIR = "/sdcard/backgrounds"
SAVE_DIR = "/sdcard/Zofour_nb_txt"
BG_THR = 234                # 原图里 min(R,G,B) >= 该值 -> 判为白背景（越小越严格，毛边少）
SAVE_WHITE = True           # 是否同时存白底风格化 white_N.jpg
SAVE_QUALITY = 95

DECO_DIR = "/sdcard/deco"   # PC 预生成的装饰层目录（deco_<背景名>.bin）
DECO_ON = True              # 有 bin 就贴；缺文件自动跳过
KEEP_SHRINK = 3             # 人物遮罩先收几像素（去掉模型输出的白晕/毛边）
KEEP_OPEN = 2               # 开运算半径（平滑轮廓）
OUTLINE_R = 2               # 人像描边宽度（像素）
OUTLINE_COLOR = (36, 36, 44)  # 描边颜色（深色；参考图人物是黑/深描边）

IN_W, IN_H = 608, 768       # 风格模型输入(宽,高)
CROP_SCALE = 1.65           # 构图：裁框 = 人像高度 x 该值（越大人物越小、背景越多）
HEAD_TOP = 0.16             # 裁框顶部留白比例
HEAD_BAND = 0.22

# ---- 人脸检测（YuNet，接口来自 CanMV 官方例程 face_detect_yunet.py）----
FACE_MODEL = "/sdcard/kmodel/yunet_640.kmodel"
FACE_CONF = 0.6             # 人脸置信度阈值
FACE_NMS = 0.3
FACE_CROP_K = 4.7           # 裁框高 = 人脸高 x 该值（≈人脸占卡片 1/5）
FACE_ANCHOR_Y = 0.34        # 人脸中心放在卡片高度的比例
FACE_KEEP_COMPONENT = True  # 只保留人脸所在的那块连通 mask（其余删掉）

# ---- 脸部高倍重绘（style_s2，320x320 脸部专精学生网）----
# 训练时：从源图裁 2.1x 脸框（中心上移 8%），缩到 320，teacher 重绘成动漫脸
# 上板时用同样的几何裁出来喂模型，再按卡片坐标贴回
FACE2_ON = True
FACE2_MODEL = "/sdcard/kmodel/style_s2.kmodel"
FACE2_IN = 320
FACE2_K = 2.1
FACE2_TOP = 0.08

# ---- 外部串口屏（陶晶驰 TJC X2 系列 7.0"）----
# ⚠ 硬件事实（本固件实测）：K230 的 IO42/IO43 在 FPIOA 里**只能**做 UART1_RTS /
#   UART1_CTS（硬件流控），**做不了 TXD/RXD**。能做 UART1 数据脚的：IO40/IO41、IO9/IO10
#   （板厂 YbUart 用的就是 IO9=TX / IO10=RX）。下面按顺序尝试，第一个成功的就用。
SCREEN_ON = True
SCREEN_BAUD = 115200         # ⚠ 必须与串口屏工程的波特率一致（TJC 出厂默认 9600）
# 按顺序尝试 (K230_TX, K230_RX)：
#   ①IO9/IO10  = 板厂 YbUart 用的 UART1（板上那个「串口」排针，最保险、不碰屏/摄像头）
#   ②IO40/IO41 = 另外一组可做 UART1 TXD/RXD 的引脚
#   ③IO43/IO42 = 用户原计划，但实测**只能做 UART1_RTS/CTS**，只能是失败后兜底试一下
SCREEN_PIN_CHOICES = ((9, 10), (40, 41), (43, 42))
# 屏上存放位置：**sd0/ 就是 SD 卡的根目录**（sd0 是设备名，不是子文件夹）；ram/ 是屏内存
#   → SCREEN_FILE 最终就是“SD 卡根目录/K230.jpg”
SCREEN_SD_ROOT = "sd0/"        # 根目录；如果要放到子目录就写 "sd0/pics/"（目录需先存在）
SCREEN_FILE_NAME = "k230"      # 文件名前缀：实际是 k230_0.jpg / k230_1.jpg ...（自增）
SCREEN_NAME_WRAP = 1000       # 编号到多少回绕到 0
SCREEN_FILE = SCREEN_SD_ROOT + SCREEN_FILE_NAME + "_0.jpg"   # 兜底默认名
SCREEN_CHUNK = 2048          # 每包数据字节（协议上限 4096，含校验；无校验则纯数据）
# 给屏的图片：尺寸必须是 16 的整数倍，且必须是 4:2:0 的 baseline JPEG
#（屏只认 4:2:0；K230 硬件编码器只出 4:4:4，所以用板端 Python 编码器 jpegenc.py）
SEND_W = 384                 # 宽（16 的倍数）
SEND_H = 480                 # 高（16 的倍数）
SEND_QUALITY = 30            # JPEG 质量 1~99
#     SEND_POOL = 3 -> 202x256  ~48KB   (~4.4s)
OUTLINE_BLACK_R = 3          # 01 信号：黑色描边宽度（像素）
OUTLINE_BLACK_COLOR = (0, 0, 0)
SCREEN_AFTER_PAGE = "page 2"   # 传完后先跳页（空串 = 不跳）
SCREEN_PIC_CTRL = "exp0"       # 屏上"外部图片"控件名；跳页后会发 exp0.path="sd0/k230_N.jpg"
                             # （控件名不是 p0 就改成你的；留空 = 不发加载指令）
SCREEN_LOG = "/sdcard/uart_raw.bin"   # 把串口收到的每个字节都存这里（排障用；空串 = 不存）
SCREEN_W = 800               # 屏分辨率（用于把图片控件居中）
SCREEN_H = 480
SCREEN_PIC_AUTORECT = True   # True: 贴图前把控件摆成 x居中/y=0/w=SEND_W/h=SEND_H

KEY_PIN = 61
AUTO_FLAG = "/sdcard/temp/_autocap"

KMODEL_CANDIDATES = [
    "/sdcard/app/tests/kmodel/yolov8n_seg_320.kmodel",
    "/sdcard/kmodel/yolov8n_seg_320.kmodel",
    "/sdcard/temp/yolov8n_seg_320.kmodel",
    "/sdcard/yolov8n_seg_320.kmodel",
]

LABELS = ["person"]  # 只需要 person

# ============================== 抠图 App（沿用固定版） ==============================
class SegmentationApp(AIBase):
    def __init__(self, kmodel_path, labels, model_input_size, confidence_threshold=0.2,
                 nms_threshold=0.5, mask_threshold=0.5, rgb888p_size=[320, 320],
                 display_size=[800, 480], debug_mode=0):
        super().__init__(kmodel_path, model_input_size, rgb888p_size, debug_mode)
        self.kmodel_path = kmodel_path
        self.labels = labels
        self.model_input_size = model_input_size
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.mask_threshold = mask_threshold
        self.rgb888p_size = [ALIGN_UP(rgb888p_size[0], 16), rgb888p_size[1]]
        self.display_size = [ALIGN_UP(display_size[0], 16), display_size[1]]
        self.debug_mode = debug_mode
        self.color_four = [(255, 220, 20, 60), (255, 119, 11, 32), (255, 0, 0, 142), (255, 0, 0, 230),
                           (255, 106, 0, 228), (255, 0, 60, 100), (255, 0, 80, 100), (255, 0, 0, 70),
                           (255, 0, 0, 192), (255, 250, 170, 30), (255, 100, 170, 30), (255, 220, 220, 0),
                           (255, 175, 116, 175), (255, 250, 0, 30), (255, 165, 42, 42), (255, 255, 77, 255),
                           (255, 0, 226, 252), (255, 182, 182, 255), (255, 0, 82, 0), (255, 120, 166, 157)]
        self.masks = np.zeros((1, self.display_size[1], self.display_size[0], 4), dtype=np.uint8)
        self.ai2d = Ai2d(debug_mode)
        self.ai2d.set_ai2d_dtype(nn.ai2d_format.NCHW_FMT, nn.ai2d_format.NCHW_FMT, np.uint8, np.uint8)

    def config_preprocess(self, input_image_size=None):
        with ScopedTiming("set preprocess config", self.debug_mode > 0):
            ai2d_input_size = input_image_size if input_image_size else self.rgb888p_size
            top, bottom, left, right = self.get_padding_param()
            self.ai2d.pad([0, 0, 0, 0, top, bottom, left, right], 0, [114, 114, 114])
            self.ai2d.resize(nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
            self.ai2d.build([1, 3, ai2d_input_size[1], ai2d_input_size[0]],
                            [1, 3, self.model_input_size[1], self.model_input_size[0]])

    def postprocess(self, results):
        with ScopedTiming("postprocess", self.debug_mode > 0):
            seg_res = aidemo.segment_postprocess(
                results, [self.rgb888p_size[1], self.rgb888p_size[0]], self.model_input_size,
                [self.display_size[1], self.display_size[0]], self.confidence_threshold,
                self.nms_threshold, self.mask_threshold, self.masks)
            return seg_res

    def draw_result(self, pl, seg_res):
        with ScopedTiming("display_draw", self.debug_mode > 0):
            if seg_res[0]:
                pl.osd_img.clear()
                mask_img = image.Image(self.display_size[0], self.display_size[1],
                                       image.ARGB8888, alloc=image.ALLOC_REF, data=self.masks)
                # 擦掉后处理画进 mask 的检测框
                for det in seg_res[0]:
                    x1, y1, w, h = map(lambda v: int(round(v, 0)), det)
                    mask_img.draw_rectangle(x1 - 2, y1 - 2, w + 4, h + 4,
                                            color=(0, 0, 0, 0), thickness=7)
                pl.osd_img.copy_from(mask_img)
            else:
                pl.osd_img.clear()

    def get_padding_param(self):
        dst_w = self.model_input_size[0]
        dst_h = self.model_input_size[1]
        ratio_w = float(dst_w) / self.rgb888p_size[0]
        ratio_h = float(dst_h) / self.rgb888p_size[1]
        ratio = ratio_w if ratio_w < ratio_h else ratio_h
        new_w = (int)(ratio * self.rgb888p_size[0])
        new_h = (int)(ratio * self.rgb888p_size[1])
        dw = (dst_w - new_w) / 2
        dh = (dst_h - new_h) / 2
        top = (int)(round(dh - 0.1))
        bottom = (int)(round(dh + 0.1))
        left = (int)(round(dw - 0.1))
        right = (int)(round(dw + 0.1))
        return top, bottom, left, right

    def get_color(self, x):
        return self.color_four[x % len(self.color_four)]


class FaceDetector(AIBase):
    """YuNet 人脸检测：只要最大那张脸（用于构图 + 选连通块）。
    在**方形 crop** 上跑（crop + resize），**不用 letterbox pad** ——
    实测本固件对 800x480 -> 640x640 的大填充（要填 128 行）会把板子直接卡死。
    模型与接口来自 CanMV 官方例程 face_detect_yunet.py。"""
    def __init__(self, kmodel_path=FACE_MODEL, model_input_size=[640, 640],
                 confidence_threshold=FACE_CONF, nms_threshold=FACE_NMS,
                 top_k=50, debug_mode=0):
        super().__init__(kmodel_path, model_input_size, [640, 640], debug_mode)
        self.kmodel_path = kmodel_path
        self.model_input_size = model_input_size
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.top_k = top_k
        self.debug_mode = debug_mode
        self.crop_size = [640, 640]
        self.ai2d = Ai2d(debug_mode)
        self.ai2d.set_ai2d_dtype(nn.ai2d_format.NCHW_FMT, nn.ai2d_format.NCHW_FMT,
                                 np.uint8, np.uint8)
        self._built = None

    def postprocess(self, results):
        w = self.crop_size[0]
        h = self.crop_size[1]
        return aidemo.yunet_postprocess(
            results, [h, w], [self.model_input_size[1], self.model_input_size[0]],
            [h, w], [8, 16, 32], self.confidence_threshold, self.nms_threshold, self.top_k)

    def detect(self, planar, crop):
        """planar:(3,H,W) uint8；crop:(x,y,w,h) 方形区域。
        返回最大人脸的 (cx,cy,w,h)（**原图坐标**）或 None。"""
        x, y, w, h = crop
        if self._built != crop:
            self.crop_size = [w, h]
            self.ai2d.crop(x, y, w, h)
            self.ai2d.resize(nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
            self.ai2d.build([1, 3, planar.shape[1], planar.shape[2]],
                            [1, 3, self.model_input_size[1], self.model_input_size[0]])
            self._built = crop
        res = self.run(planar)
        try:
            dets = res[0]
        except Exception:
            return None
        if dets is None:
            return None
        best = None
        try:
            n = len(dets)
        except Exception:
            return None
        for i in range(n):
            b = dets[i]
            bw = float(b[2])
            bh = float(b[3])
            if bw <= 1 or bh <= 1:
                continue
            if best is None or bw * bh > best[2] * best[3]:
                best = (float(b[0]), float(b[1]), bw, bh)
        if best is None:
            return None
        return (best[0] + best[2] * 0.5 + x, best[1] + best[3] * 0.5 + y, best[2], best[3])


def face_crop_for(src_w, src_h, bbox):
    """人脸检测用的方形 crop：边长 = 画面高，水平对准人像包围盒中心。"""
    side = src_h if src_h < src_w else src_w
    side -= side % 2
    bx, by, bw, bh = bbox
    cx = bx + bw // 2
    x = max(0, min(cx - side // 2, src_w - side))
    y = max(0, min((src_h - side) // 2, src_h - side))
    return (x, y, side, side)


def face_roi(src_w, src_h, face):
    """以人脸为中心算裁框：人脸中心水平居中、放在卡片 FACE_ANCHOR_Y 高度处。
    注意：h 和 w 必须保持 IN_W:IN_H 的比例（先钳 h 再算 w，若 w 超宽就反过来钳 h）。"""
    cx, cy, fw, fh = face
    h = int(fh * FACE_CROP_K)
    if h > src_h:
        h = src_h
    w = int(h * float(IN_W) / float(IN_H))
    if w > src_w:
        w = src_w
        h = int(w * float(IN_H) / float(IN_W))
    w -= w % 2
    h -= h % 2
    if h < 64 or w < 64:
        return None
    x = int(cx - w * 0.5)
    y = int(cy - FACE_ANCHOR_Y * h)
    x = max(0, min(x, src_w - w))
    y = max(0, min(y, src_h - h))
    return (x, y, w, h)


def keep_face_component(keep, seed=None, step=4):
    """只保留一块连通区域：seed=(x,y) 模型空间 -> 包含该点的那块；seed=None -> 最大的一块。
    在 step 倍降采样网格上做连通标记（快），膨胀 1 格后升采样，最后与原 keep 按位与
    （所以边缘仍是全分辨率的）。返回新的 keep。"""
    gw = (IN_W + step - 1) // step
    gh = (IN_H + step - 1) // step
    grid = np.zeros((gh, gw), dtype=np.uint8)
    for gy in range(gh):
        y = gy * step
        if y >= IN_H:
            y = IN_H - 1
        for gx in range(gw):
            x = gx * step
            if x >= IN_W:
                x = IN_W - 1
            if keep[y, x]:
                grid[gy, gx] = 1
    sx = sy = -1
    if seed is not None:
        sx = int(seed[0]) // step
        sy = int(seed[1]) // step
        if sx < 0:
            sx = 0
        elif sx >= gw:
            sx = gw - 1
        if sy < 0:
            sy = 0
        elif sy >= gh:
            sy = gh - 1
    labels = np.zeros((gh, gw), dtype=np.int16)
    lab = 0
    best_lab = -1
    best_size = -1
    best_d = 1 << 30
    for gy in range(gh):
        for gx in range(gw):
            if grid[gy, gx] == 0 or labels[gy, gx] != 0:
                continue
            lab += 1
            size = 0
            dmin = 1 << 30
            stack = [gy * gw + gx]
            labels[gy, gx] = lab
            while stack:
                i = stack.pop()
                cyy = i // gw
                cxx = i - cyy * gw
                size += 1
                if sx >= 0:
                    d = (cxx - sx) * (cxx - sx) + (cyy - sy) * (cyy - sy)
                    if d < dmin:
                        dmin = d
                for dy in (-1, 0, 1):
                    ny = cyy + dy
                    if ny < 0 or ny >= gh:
                        continue
                    base = ny * gw
                    for dx in (-1, 0, 1):
                        nx = cxx + dx
                        if nx < 0 or nx >= gw:
                            continue
                        if grid[ny, nx] and labels[ny, nx] == 0:
                            labels[ny, nx] = lab
                            stack.append(base + nx)
            if sx >= 0:
                if dmin < best_d or (dmin == best_d and size > best_size):
                    best_d = dmin
                    best_size = size
                    best_lab = lab
            else:
                if size > best_size:
                    best_size = size
                    best_lab = lab
    if best_lab < 0:
        return keep
    sel = np.array((labels == best_lab), dtype=np.uint8) * 255
    d4 = np.zeros((gh, gw), dtype=np.uint8)
    d4[:, :] = sel
    d4[1:, :] = d4[1:, :] | sel[:-1, :]
    d4[:-1, :] = d4[:-1, :] | sel[1:, :]
    d4[:, 1:] = d4[:, 1:] | sel[:, :-1]
    d4[:, :-1] = d4[:, :-1] | sel[:, 1:]
    up = np.zeros((IN_H, IN_W), dtype=np.uint8)
    for gy in range(gh):
        y0 = gy * step
        y1 = y0 + step
        if y1 > IN_H:
            y1 = IN_H
        for gx in range(gw):
            if d4[gy, gx]:
                x0 = gx * step
                x1 = x0 + step
                if x1 > IN_W:
                    x1 = IN_W
                up[y0:y1, x0:x1] = 255
    del grid, labels, sel, d4
    gc.collect()
    return keep & up


# ============================== 漫画化后处理（板端 ulab） ==============================
def box5_u16(x):
    """uint16 (IN_H,IN_W) 的 5 点均值（自己 + 上下左右）/ 5。"""
    acc = np.zeros((IN_H, IN_W), dtype=np.uint16)
    acc[:] = x
    acc[:, 1:] = acc[:, 1:] + x[:, :-1]
    acc[:, :-1] = acc[:, :-1] + x[:, 1:]
    acc[1:, :] = acc[1:, :] + x[:-1, :]
    acc[:-1, :] = acc[:-1, :] + x[1:, :]
    m = acc // 5
    del acc
    gc.collect()
    return m


def comic_post(base):
    """风格模型输出 -> 漫画感：保边平涂 -> 色阶/对比/提亮 -> 边缘线稿加深 -> 饱和。
    线稿只用「边缘图」(|亮度-邻域均值|)，所以只压真正的线，
    不会像 v2 初版那样把暗衣服/阴影一起压黑。
    base: (3,IN_H,IN_W) uint8  ->  res: (3,IN_H,IN_W) uint8"""
    res = np.zeros((3, IN_H, IN_W), dtype=np.uint8)

    # A) 亮度 + 边缘强度图
    lum = np.array(base[0], dtype=np.uint16) * 77
    lum = lum + np.array(base[1], dtype=np.uint16) * 150
    lum = lum + np.array(base[2], dtype=np.uint16) * 29
    lum = lum // 256
    ml = box5_u16(lum)
    li = np.array(lum, dtype=np.int16)
    mi = np.array(ml, dtype=np.int16)
    del lum, ml
    gc.collect()
    ad = np.clip(li - mi, 0, 255) + np.clip(mi - li, 0, 255)   # 边缘强度 0~255
    del li, mi
    gc.collect()

    if FLAT_THR > 0:
        w = np.clip(FLAT_THR - ad, 0, FLAT_THR)                # 平涂权重（整数刻度 0~FLAT_THR）
    if LINE_K > 0:
        dl = np.clip(ad - EDGE_LO, 0, 255)
        dl = np.minimum(dl * int(LINE_GAIN * 100) // 100, 255)
        if LINE_DILATE > 0:                                    # 线宽加粗（边缘膨胀）
            dl8 = np.array(dl, dtype=np.uint8)
            dd = np.zeros((IN_H, IN_W), dtype=np.uint8)
            dd[:] = dl8
            dd = _shift_or(dd, dl8, LINE_DILATE, 0)
            dd = _shift_or(dd, dl8, -LINE_DILATE, 0)
            dd = _shift_or(dd, dl8, 0, LINE_DILATE)
            dd = _shift_or(dd, dl8, 0, -LINE_DILATE)
            dl = np.array(dd, dtype=np.uint16)
            del dl8, dd
            gc.collect()
        else:
            dl = np.array(dl, dtype=np.uint16)
        t = 255 - (dl * int(LINE_K * 255)) // 255              # 乘性系数 0~255
        del dl
        gc.collect()

    # B) 逐通道：保边平涂 -> 色阶 -> 对比 -> 提亮 -> 线稿
    for c in range(3):
        xc = np.array(base[c], dtype=np.uint16)
        if FLAT_THR > 0:
            mc = box5_u16(xc)
            xi = np.array(xc, dtype=np.int16)
            mi2 = np.array(mc, dtype=np.int16)
            del mc
            gc.collect()
            adj = (xi - mi2) * w // FLAT_THR
            fx = np.array(np.clip(xi + adj, 0, 255), dtype=np.float)
            del xi, mi2, adj
        else:
            fx = np.array(xc, dtype=np.float)
        del xc
        gc.collect()
        if LEVELS[1] > LEVELS[0]:
            fx = np.clip((fx - LEVELS[0]) * (255.0 / (LEVELS[1] - LEVELS[0])), 0, 255)
        if CONTRAST != 1.0:
            fx = np.clip((fx - 128.0) * CONTRAST + 128.0, 0, 255)
        if BRIGHT:
            fx = np.clip(fx + BRIGHT, 0, 255)
        if LINE_K > 0:
            xu = np.array(np.clip(fx, 0, 255), dtype=np.uint16)
            del fx
            gc.collect()
            fx = np.array((xu * t) // 255, dtype=np.float)
            del xu
        res[c] = np.array(np.clip(fx, 0, 255), dtype=np.uint8)
        del fx
        gc.collect()
    del ad
    gc.collect()
    if FLAT_THR > 0:
        del w
        gc.collect()
    if LINE_K > 0:
        del t
        gc.collect()

    # C) 饱和度
    if SAT != 1.0:
        g = (np.array(res[0], dtype=np.uint16) + np.array(res[1], dtype=np.uint16)
             + np.array(res[2], dtype=np.uint16)) // 3
        gf = np.array(g, dtype=np.float)
        del g
        gc.collect()
        for c in range(3):
            cf = np.array(res[c], dtype=np.float)
            res[c] = np.array(np.clip(gf + (cf - gf) * SAT, 0, 255), dtype=np.uint8)
            del cf
            gc.collect()
        del gf
        gc.collect()

    # D) 白平衡（把偏青灰的肤色拉暖）
    if WB != (1.0, 1.0, 1.0):
        for c in range(3):
            num = int(WB[c] * 100)
            if num != 100:
                res[c] = np.array(
                    np.minimum((np.array(res[c], dtype=np.uint16) * num) // 100, 255),
                    dtype=np.uint8)
    return res


def roi_keep_from_mask(mask_buf, W, H, roi):
    """把显示空间(800x480) ARGB 人像 mask 映射到模型空间 (IN_H,IN_W) 的 0/255 遮罩。
    v3 新增：只用"白底阈值"分不清人物和背景影子（会把人影也当人 -> 灰白"鬼影"），
    所以用分割 mask 限定范围（2x2 块采样，够用且快）。"""
    x, y, w, h = roi
    k = np.zeros((IN_H, IN_W), dtype=np.uint8)
    step = 2
    row = W * 4
    for my in range(0, IN_H, step):
        sy = y + (my * h) // IN_H
        if sy < 0:
            sy = 0
        elif sy >= H:
            sy = H - 1
        base = sy * row
        for mx in range(0, IN_W, step):
            sx = x + (mx * w) // IN_W
            if sx < 0:
                sx = 0
            elif sx >= W:
                sx = W - 1
            i = base + sx * 4
            if mask_buf[i + 1] == 220 and mask_buf[i + 2] == 20 and mask_buf[i + 3] == 60:
                k[my:my + step, mx:mx + step] = 255
    return k


# ============================== 风格模型（单模型 + 抠图掩膜） ==============================
class StyleModel:
    def __init__(self, kmodel=STYLE_MODEL):
        self.kpu = nn.kpu()
        self.kpu.load_kmodel(kmodel)
        self.ai2d = Ai2d(0)
        self.ai2d.set_ai2d_dtype(nn.ai2d_format.NCHW_FMT,
                                 nn.ai2d_format.NCHW_FMT, np.uint8, np.uint8)
        self._built = None

    def _run_kpu(self, tensor):
        self.kpu.set_input_tensor(0, tensor)
        self.kpu.run()
        out = self.kpu.get_output_tensor(0)
        try:
            chw = out.to_numpy().reshape((3, IN_H, IN_W))
            val = np.array(np.clip(chw, 0, 255), dtype=np.uint8)
        finally:
            rel = getattr(out, "release", None)
            if callable(rel):
                try:
                    rel()
                except Exception:
                    pass
        del out, chw
        gc.collect()
        return val

    def _forward(self, ai2d_out, seg_keep=None, seed=None):
        inp = ai2d_out.to_numpy().reshape((3, IN_H, IN_W))
        mn = np.minimum(np.minimum(inp[0], inp[1]), inp[2])
        keep = np.array((mn < BG_THR), dtype=np.uint8) * 255
        del mn
        gc.collect()
        if seg_keep is not None:          # 与分割 mask 求交 -> 去掉背景影子/杂项
            keep = keep & seg_keep
        if FACE_KEEP_COMPONENT:           # 只留人脸所在连通块，其余全删
            try:
                t_k = time.ticks_ms()
                keep = keep_face_component(keep, seed)
                print("   [comp] 连通块 %d ms (seed=%r)" % (time.ticks_ms() - t_k, seed))
            except Exception as e:
                print("   [warn] 连通块过滤失败:", repr(e))

        base = self._run_kpu(ai2d_out)
        res = comic_post(base)
        del base
        gc.collect()
        return res, keep

    def infer(self, frame_np, roi, seg_keep=None, seed=None):
        x, y, w, h = roi
        if self._built != roi:
            self.ai2d.crop(x, y, w, h)
            self.ai2d.resize(nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
            self.ai2d.build([1, 3, frame_np.shape[1], frame_np.shape[2]],
                            [1, 3, IN_H, IN_W])
            self._built = roi
        ai2d_out = self.ai2d.run(frame_np)
        return self._forward(ai2d_out, seg_keep, seed)


# ============================== 脸部专精模型（style_s2, 320x320） ==============================
class FaceStyle2:
    def __init__(self, kmodel=FACE2_MODEL):
        self.kpu = nn.kpu()
        self.kpu.load_kmodel(kmodel)
        self.ai2d = Ai2d(0)
        self.ai2d.set_ai2d_dtype(nn.ai2d_format.NCHW_FMT,
                                 nn.ai2d_format.NCHW_FMT, np.uint8, np.uint8)
        self._built = None

    def infer(self, frame_np, box):
        x, y, s = box
        if self._built != (x, y, s):
            self.ai2d.crop(x, y, s, s)
            self.ai2d.resize(nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
            self.ai2d.build([1, 3, frame_np.shape[1], frame_np.shape[2]],
                            [1, 3, FACE2_IN, FACE2_IN])
            self._built = (x, y, s)
        ai2d_out = self.ai2d.run(frame_np)
        self.kpu.set_input_tensor(0, ai2d_out)
        self.kpu.run()
        out = self.kpu.get_output_tensor(0)
        try:
            chw = out.to_numpy().reshape((3, FACE2_IN, FACE2_IN))
            val = np.array(np.clip(chw, 0, 255), dtype=np.uint8)
        finally:
            rel = getattr(out, "release", None)
            if callable(rel):
                try:
                    rel()
                except Exception:
                    pass
        del out, chw
        gc.collect()
        return val


def face2_box(fx, fy, fw, fh, W, H):
    """与训练时完全一致的裁法：边长 = max(fw,fh)*FACE2_K，中心上移 FACE2_TOP*边长。"""
    s = int(max(fw, fh) * FACE2_K)
    if s > W:
        s = W
    if s > H:
        s = H
    cx = fx + fw * 0.5
    cy = fy + fh * 0.5 - s * FACE2_TOP
    x0 = int(cx - s * 0.5)
    y0 = int(cy - s * 0.5)
    if x0 < 0:
        x0 = 0
    elif x0 + s > W:
        x0 = W - s
    if y0 < 0:
        y0 = 0
    elif y0 + s > H:
        y0 = H - s
    return x0, y0, s


def paste_face2(comp, chw, box, roi, keep=None):
    """把 320x320 动漫脸缩到卡片对应位置，边缘羽化混合。返回贴入边长（0=没贴）。"""
    x0, y0, s = box
    fx = float(IN_W) / float(roi[2])
    fy = float(IN_H) / float(roi[3])
    X0 = int((x0 - roi[0]) * fx + 0.5)
    Y0 = int((y0 - roi[1]) * fy + 0.5)
    SW = int(s * fx + 0.5)
    SH = int(s * fy + 0.5)
    if SW < 16 or SH < 16:
        return 0
    if X0 >= IN_W or Y0 >= IN_H or X0 + SW <= 0 or Y0 + SH <= 0:
        return 0
    img, _hwc = planar_to_image(chw)
    sc = img.scale(float(SW) / FACE2_IN, float(SH) / FACE2_IN)
    if sc is not None:
        img = sc
    rgb = img.to_rgb888()
    pk = np.array(rgb.to_numpy_ref(), dtype=np.uint8)   # (sh, sw, 3)
    sw = rgb.width()
    sh = rgb.height()
    del img, sc, rgb
    gc.collect()
    px0 = X0 if X0 > 0 else 0
    py0 = Y0 if Y0 > 0 else 0
    px1 = IN_W if X0 + sw > IN_W else X0 + sw
    py1 = IN_H if Y0 + sh > IN_H else Y0 + sh
    bw = px1 - px0
    bh = py1 - py0
    if bw <= 1 or bh <= 1:
        return 0
    sx0 = px0 - X0
    sy0 = py0 - Y0
    f = int(min(bw, bh) // 14)
    if f < 3:
        f = 3
    cola = np.zeros(bw, dtype=np.float32)
    for j in range(bw):
        dj = j if j < (bw - 1 - j) else (bw - 1 - j)
        cola[j] = 1.0 if dj >= f else float(dj) / float(f)
    for i in range(bh):
        dy = i if i < (bh - 1 - i) else (bh - 1 - i)
        arow = 1.0 if dy >= f else float(dy) / float(f)
        a2 = cola * arow
        if keep is not None:
            km = keep[py0 + i, px0:px1].astype(np.float32)
            km = km * (1.0 / 255.0)
            a2 = a2 * km
        dst = comp[py0 + i, px0:px1, :]
        src = pk[sy0 + i, sx0:sx0 + bw, :]
        for c in range(3):
            d = dst[:, c].astype(np.float32)
            s_ = src[:, c].astype(np.float32)
            r = s_ * a2 + d * (1.0 - a2)
            comp[py0 + i, px0:px1, c] = r.astype(np.uint8)
    return sw


# ============================== 工具函数 ==============================
def ensure_dir(path):
    try:
        os.mkdir(path)
    except Exception:
        pass


def collect_raw_frames(pl, n=25, dt=1.2):
    """采集模式（临时）：/sdcard/temp/_collect 存在时，上电后连拍 n 张原图存 temp/raw_XX.jpg。"""
    print("[collect] 开始采集 %d 张（每张间隔 %.1fs）" % (n, dt))
    for i in range(n):
        try:
            W2, H2, buf = grab_source_frame(pl)
            img = image.Image(W2, H2, image.RGB888, alloc=image.ALLOC_REF, data=buf)
            img.to_jpeg().save('/sdcard/temp/raw_%02d.jpg' % i)
            print("[collect] raw_%02d.jpg ok (%dx%d)" % (i, W2, H2))
            del img
        except Exception as e:
            print("[collect] 第 %d 张失败:" % i, repr(e))
        time.sleep(dt)
        gc.collect()
    try:
        os.remove('/sdcard/temp/_collect')
    except Exception:
        pass
    print("[collect] 完成，请断电重启")
    while True:
        os.exitpoint()
        time.sleep_ms(500)


def pick_kmodel():
    for p in KMODEL_CANDIDATES:
        try:
            if os.stat(p)[6] > 0:
                return p
        except Exception:
            pass
    return KMODEL_CANDIDATES[0]


def next_index(directory):
    idx = 0
    try:
        for name in os.listdir(directory):
            n = name.lower()
            if n.startswith("result_") and n.endswith(".jpg"):
                try:
                    v = int(n[7:-4])
                    if v > idx:
                        idx = v
                except Exception:
                    pass
    except Exception:
        pass
    return idx + 1


def grab_source_frame(pl):
    """取一帧 packed RGB888（chn1；chn2 的 to_rgb888 是坏的）。返回 (W,H,bytearray)。"""
    img = None
    try:
        img = pl.sensor.snapshot(chn=CAM_CHN_ID_1)
    except Exception:
        img = pl.sensor.snapshot(chn=CAM_CHN_ID_2)
    rgb = img.to_rgb888()
    return rgb.width(), rgb.height(), rgb.bytearray()


def compose_person_white(out, mask_buf, src_buf, W, H, SW, SH):
    """把 mask 里 person 的像素从 src 搬到白底 out 上。只比对 R,G,B=(220,20,60)。"""
    person = 0
    row = W * 4
    row3 = W * 3
    same = (SW == W and SH == H)
    xmap = None
    if not same:
        xmap = [x * SW // W for x in range(W)]
    for y in range(H):
        m = y * row
        o = y * row3
        if same:
            for x in range(W):
                if mask_buf[m + 1] == 220 and mask_buf[m + 2] == 20 and mask_buf[m + 3] == 60:
                    out[o] = src_buf[o]
                    out[o + 1] = src_buf[o + 1]
                    out[o + 2] = src_buf[o + 2]
                    person += 1
                m += 4
                o += 3
        else:
            srow = (y * SH // H) * SW * 3
            for x in range(W):
                if mask_buf[m + 1] == 220 and mask_buf[m + 2] == 20 and mask_buf[m + 3] == 60:
                    si = srow + xmap[x] * 3
                    out[o] = src_buf[si]
                    out[o + 1] = src_buf[si + 1]
                    out[o + 2] = src_buf[si + 2]
                    person += 1
                m += 4
                o += 3
    return person


def packed_to_planar(buf, W, H):
    """packed RGB888 bytearray -> (3,H,W) uint8 平面数组。"""
    packed = np.frombuffer(buf, dtype=np.uint8).reshape((H, W, 3))
    planar = np.zeros((3, H, W), dtype=np.uint8)
    planar[0] = packed[:, :, 0]
    planar[1] = packed[:, :, 1]
    planar[2] = packed[:, :, 2]
    del packed
    gc.collect()
    return planar


def decode_to_planar(jpg_path):
    """jpeg -> (3,H,W) uint8 平面数组（本固件用 to_rgb888 + to_numpy_ref）。"""
    im = image.Image(jpg_path)
    packed_img = im.to_rgb888()
    packed = packed_img.to_numpy_ref()
    H = packed.shape[0]
    W = packed.shape[1]
    planar = np.zeros((3, H, W), dtype=np.uint8)
    planar[0] = packed[:, :, 0]
    planar[1] = packed[:, :, 1]
    planar[2] = packed[:, :, 2]
    try:
        packed_img.free()
    except Exception:
        pass
    try:
        im.free()
    except Exception:
        pass
    del packed
    gc.collect()
    return planar, H, W


def person_bbox(r_plane, thr=235):
    H = r_plane.shape[0]
    W = r_plane.shape[1]
    rows = []
    for y in range(H):
        if int(np.min(r_plane[y])) < thr:
            rows.append(y)
    if not rows:
        return None
    y0 = rows[0]
    y1 = rows[-1]
    x0 = W
    x1 = 0
    for y in rows:
        row = r_plane[y]
        for x in range(W):
            if row[x] < thr:
                if x < x0:
                    x0 = x
                if x > x1:
                    x1 = x
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def training_roi(src_w, src_h, r_plane, thr=235):
    bb = person_bbox(r_plane, thr)
    if bb is None:
        return None
    bx, by, bw, bh = bb
    y_end = min(src_h, by + max(1, int(bh * HEAD_BAND)))
    hx0 = src_w
    hx1 = -1
    for y in range(by, y_end):
        row = r_plane[y]
        for x in range(src_w):
            if row[x] < thr:
                if x < hx0:
                    hx0 = x
                if x > hx1:
                    hx1 = x
    if hx1 < hx0:
        hcx = bx + bw // 2
    else:
        hcx = (hx0 + hx1) // 2
    h = int(bh * CROP_SCALE)
    w = int(h * float(IN_W) / float(IN_H))
    # ⚠ 必须把裁框钳在画面内！否则 AI2D crop 越界会把板子挂死（实测：h>src_h 时卡死）
    if h > src_h:
        h = src_h
    if w > src_w:
        w = src_w
    w -= w % 2
    h -= h % 2
    if h < 64 or w < 64:
        return None
    x = hcx - w // 2
    y = by - int(h * HEAD_TOP)
    x = max(0, min(x, src_w - w))
    y = max(0, min(y, src_h - h))
    return (x, y, w, h)


def all_bg_names():
    """背景名（不带扩展名）。v3：优先 .jpg（板上解码，上传体积小 10 倍），兼容旧 .rgb888。"""
    names = []
    try:
        for n in sorted(os.listdir(BG_DIR)):
            low = n.lower()
            for ext in (".jpg", ".jpeg", ".png", ".rgb888"):
                if low.endswith(ext):
                    nm = n[:-len(ext)]
                    if nm not in names:
                        names.append(nm)
                    break
    except Exception as e:
        print("[warn] 打不开背景目录", BG_DIR, e)
    return names


def pick_background():
    """每次触发挑一张（按文件名顺序轮换，状态存 SAVE_DIR/bg_state.txt）。"""
    names = all_bg_names()
    if not names:
        return None
    state = SAVE_DIR + "/bg_state.txt"
    last = None
    try:
        f = open(state, "r")
        last = f.read().strip()
        f.close()
    except Exception:
        last = None
    idx = (names.index(last) + 1) % len(names) if last in names else 0
    cur = names[idx]
    try:
        ensure_dir(SAVE_DIR)
        f = open(state, "w")
        f.write(cur)
        f.close()
    except Exception as e:
        print("   [warn] 写背景状态失败:", repr(e))
    return cur


def load_bg_rgb888(name):
    """载入背景 -> (np (IN_H,IN_W,3) uint8, 原始bytearray或None)。
    v3：优先 JPEG/PNG（板上解码，上传体积小 10 倍），没有才回退旧 .rgb888。"""
    for ext in (".jpg", ".jpeg", ".png"):
        path = BG_DIR + "/" + name + ext
        try:
            if os.stat(path)[6] <= 0:
                continue
        except Exception:
            continue
        im = image.Image(path)
        pi = im.to_rgb888()
        packed = pi.to_numpy_ref()
        H = packed.shape[0]
        W = packed.shape[1]
        if H != IN_H or W != IN_W:
            print("   [bg] 尺寸不符 %dx%d（要 %dx%d）: %s" % (W, H, IN_W, IN_H, path))
        bg = np.zeros((H, W, 3), dtype=np.uint8)
        bg[:, :, 0] = packed[:, :, 0]
        bg[:, :, 1] = packed[:, :, 1]
        bg[:, :, 2] = packed[:, :, 2]
        try:
            pi.free()
        except Exception:
            pass
        try:
            im.free()
        except Exception:
            pass
        del packed
        gc.collect()
        return bg, None
    path = BG_DIR + "/" + name + ".rgb888"
    f = open(path, "rb")
    data = bytearray(f.read())
    f.close()
    if len(data) != IN_H * IN_W * 3:
        raise ValueError("背景尺寸不对: %d" % len(data))
    return np.frombuffer(data, dtype=np.uint8).reshape((IN_H, IN_W, 3)), data


def composite(res, keep, bg):
    inv = np.array(keep ^ 0xFF, dtype=np.uint8)
    out = np.zeros((IN_H, IN_W, 3), dtype=np.uint8)
    for c in range(3):
        out[:, :, c] = (res[c] & keep) | (bg[:, :, c] & inv)
    del inv
    gc.collect()
    return out


def _shift_or(dst, k, dx, dy):
    """把 k 平移 (dx,dy) 后 OR 进 dst（位运算做形态学，ulab 向量化，快）"""
    t = np.zeros((IN_H, IN_W), dtype=np.uint8)
    if dy == 0:
        if dx > 0:
            t[:, dx:] = k[:, :-dx]
        else:
            t[:, :dx] = k[:, -dx:]
    else:
        if dy > 0:
            t[dy:, :] = k[:-dy, :]
        else:
            t[:dy, :] = k[-dy:, :]
    r = dst | t
    del t
    return r


def _dilate_sq(k, n):
    """方形结构元膨胀 n 像素"""
    d = np.zeros((IN_H, IN_W), dtype=np.uint8)
    d[:] = k
    if n > 0:
        d = _shift_or(d, k, n, 0)
        d = _shift_or(d, k, -n, 0)
        d = _shift_or(d, k, 0, n)
        d = _shift_or(d, k, 0, -n)
    return d


def _erode_sq(k, n):
    """腐蚀 n 像素 = 反相膨胀再反相"""
    inv = k ^ 0xFF
    d = _dilate_sq(inv, n)
    e = d ^ 0xFF
    del d, inv
    gc.collect()
    return e


def _mask01(keep):
    return np.array(keep > 0, dtype=np.uint8) * 255


def smooth_keep(keep):
    """人物遮罩清理：先收 KEEP_SHRINK 像素（去掉模型输出的白晕/毛边），
    再做开运算平滑轮廓（板端没高斯模糊，用形态学近似）。"""
    k = _mask01(keep)
    k = _erode_sq(k, KEEP_SHRINK)
    k = _dilate_sq(k, KEEP_SHRINK - 1)
    k = _erode_sq(k, KEEP_OPEN)
    k = _dilate_sq(k, KEEP_OPEN)
    return k


def draw_person_outline(comp, keep, r=OUTLINE_R, color=OUTLINE_COLOR):
    """给人像描一圈边（r <= 0 则不描）。01 信号用黑色粗描边，02 不加。"""
    if r <= 0:
        return 0
    k = _mask01(keep)
    d = _dilate_sq(k, r)
    ring = d & (k ^ 0xFF)
    inv = ring ^ 0xFF
    for c in range(3):
        comp[:, :, c] = (ring & color[c]) | (comp[:, :, c] & inv)
    del k, d, ring, inv
    gc.collect()
    return 1


def find_deco(bgname):
    """找装饰层文件。v3：装饰层内容与背景无关（实测 6 个 bin MD5 完全一样），
    所以 deco_<背景>.bin 不存在时自动回退到目录里任何一个尺寸正确的 deco_*.bin。"""
    want = IN_H * IN_W * 4
    path = DECO_DIR + "/deco_" + bgname + ".bin"
    try:
        if os.stat(path)[6] == want:
            return path
    except Exception:
        pass
    try:
        for n in sorted(os.listdir(DECO_DIR)):
            if n.startswith("deco_") and n.endswith(".bin"):
                p2 = DECO_DIR + "/" + n
                try:
                    if os.stat(p2)[6] == want:
                        print("   [deco] 用回退装饰层:", n)
                        return p2
                except Exception:
                    pass
    except Exception as e:
        print("   [deco] 扫描目录失败:", repr(e))
    return None


def apply_deco(comp, bgname):
    """贴 PC 预生成的装饰层（四周贴纸 + 底部校徽校名）。
    deco_<bgname>.bin: 608*768 RGBA8888，RGB = 不预乘的贴纸颜色，A = 软 alpha。
    实心（A>=240）走位运算；半透明边缘逐点真 alpha 混合 ——
    这样贴纸压在人像上是"叠上去"而不是"替换掉"，不会挖出方块。"""
    if not DECO_ON:
        return 0
    path = find_deco(bgname)
    if path is None:
        print("   [deco] 没有可用的装饰层，跳过")
        return 0
    row_bytes = IN_W * 4
    try:
        if os.stat(path)[6] != IN_H * row_bytes:
            print("   [deco] 文件大小不对，跳过:", path)
            return 0
    except Exception:
        print("   [deco] 没有装饰层，跳过:", path)
        return 0
    t0 = time.ticks_ms()
    f = open(path, "rb")
    CH = 64
    soft_px = 0
    for y0 in range(0, IN_H, CH):
        h = CH if y0 + CH <= IN_H else IN_H - y0
        data = bytearray(f.read(h * row_bytes))
        ov = np.frombuffer(data, dtype=np.uint8).reshape((h, IN_W, 4))
        core = np.array(ov[:, :, 3] >= 240, dtype=np.uint8) * 255
        inv = core ^ 0xFF
        for c in range(3):
            comp[y0:y0 + h, :, c] = (ov[:, :, c] & core) | (comp[y0:y0 + h, :, c] & inv)
        cb = comp[y0:y0 + h].tobytes()          # 这一块的合成图（扁平 RGB）
        for i in range(h * IN_W):
            p = i * 4
            al = data[p + 3]
            if al == 0 or al >= 240:
                continue
            ia = 255 - al
            j = i * 3
            cb[j] = (data[p] * al + cb[j] * ia) // 255
            cb[j + 1] = (data[p + 1] * al + cb[j + 1] * ia) // 255
            cb[j + 2] = (data[p + 2] * al + cb[j + 2] * ia) // 255
            soft_px += 1
        if soft_px:
            comp[y0:y0 + h, :, :] = np.frombuffer(cb, dtype=np.uint8).reshape((h, IN_W, 3))
        del ov, core, inv, data, cb
    f.close()
    gc.collect()
    print("   [deco] 已贴装饰层 %s (半透明像素 %d, %d ms)"
          % (path, soft_px, time.ticks_ms() - t0))
    return 1


def planar_to_image(chw):
    H = chw.shape[1]
    W = chw.shape[2]
    hwc = np.zeros((H, W, 3), dtype=np.uint8)
    hwc[:, :, 0] = chw[0]
    hwc[:, :, 1] = chw[1]
    hwc[:, :, 2] = chw[2]
    return image.Image(W, H, image.RGB888, alloc=image.ALLOC_REF, data=hwc), hwc


def save_hwc(hwc, path, quality=SAVE_QUALITY):
    H = hwc.shape[0]
    W = hwc.shape[1]
    img = image.Image(W, H, image.RGB888, alloc=image.ALLOC_REF, data=hwc)
    img.to_jpeg().save(path, quality=quality)


# ============================== 一次完整处理 ==============================
# ============================== 外部串口屏（陶晶驰 TJC） ==============================
def save_send_jpeg(hwc, path):
    """给串口屏的 JPEG：缩到 SEND_W x SEND_H，用板端 Python 编码器出 4:2:0 baseline。
    （屏的"外部图片"控件只认 4:2:0；K230 硬件编码器只出 4:4:4，实测屏会花屏）"""
    H = hwc.shape[0]
    W = hwc.shape[1]
    img = image.Image(W, H, image.RGB888, alloc=image.ALLOC_REF, data=hwc)
    try:
        sc = img.scale(float(SEND_W) / W, float(SEND_H) / H)
        if sc is not None:
            img = sc
    except Exception as e:
        print("   [send] scale 失败，按原尺寸:", repr(e))
    rgb = img.to_rgb888()
    w2 = rgb.width()
    h2 = rgb.height()
    pk = rgb.to_numpy_ref()
    return jpegenc.encode(pk, w2, h2, path, SEND_QUALITY)


def next_pic_index():
    """下一张图片的编号（k230_N.jpg 自增，存盘 pic_idx.txt，重启也接着走）。"""
    p = SAVE_DIR + "/pic_idx.txt"
    n = 0
    try:
        f = open(p, 'r')
        s = f.read().strip()
        f.close()
        if s:
            n = int(s)
    except Exception:
        n = 0
    try:
        f = open(p, 'w')
        f.write(str((n + 1) % SCREEN_NAME_WRAP))
        f.close()
    except Exception as e:
        print("   [screen] 写编号失败:", repr(e))
    return n


class ScreenLink:
    """陶晶驰 TJC 串口屏：
       · 收屏发来的 0x01 / 0x02（0x01 = 带黑色描边，0x02 = 不描边）
       · 按 wiki（运行中串口传输文件）把 JPEG 传到屏的 sd0：
         1) twfile "sd0/xxx.jpg",<size> + FF FF FF  -> 等 0xFE(成功) / 0x06(失败)
         2) 每包：12 字节包头 3A A1 BB 44 7F FF FE | 校验类型0x00 | 包ID(小端2B) | 数据长(小端2B)
            然后紧跟数据；每包后等 0x05(成功) / 0x04(失败)
         3) 全部发完等 0xFD
       dry_path 不为 None 时把要发的字节写进本地文件（不接屏也能验证协议）。
    """
    def __init__(self, baud=SCREEN_BAUD, dry_path=None):
        self.uart = None
        self.pins = None
        self.dry = None
        if dry_path:
            self.dry = open(dry_path, 'wb')
            print("[screen] DRY RUN -> %s" % dry_path)
            return
        if not SCREEN_ON:
            print("[screen] SCREEN_ON=False，不初始化")
            return
        try:
            f = FPIOA()
        except Exception as e:
            print("[screen] FPIOA 不可用:", repr(e))
            return
        for tx, rx in SCREEN_PIN_CHOICES:
            try:
                f.set_function(tx, FPIOA.UART1_TXD, ie=0, oe=1, pu=1)
                f.set_function(rx, FPIOA.UART1_RXD, ie=1, oe=0, pu=1)
            except Exception as e:
                print("[screen] IO%d/IO%d 不能做 UART1 TXD/RXD -> %s" % (tx, rx, e))
                continue
            try:
                self.uart = UART(UART.UART1, baud)
                self.pins = (tx, rx)
                print("[screen] OK: TX=IO%d  RX=IO%d  %d bps" % (tx, rx, baud))
                break
            except Exception as e:
                print("[screen] IO%d/IO%d 映射成功但 UART 打不开: %r" % (tx, rx, e))
                self.uart = None
        if self.uart is None:
            print("[screen] 串口未就绪（屏没接就先只本地保存）")

    def ready(self):
        return (self.uart is not None) or (self.dry is not None)

    def _log_rx(self, d):
        """把收到的原始字节追加到日志（排障：判断接线/波特率）。"""
        if not SCREEN_LOG or not d:
            return
        try:
            f = open(SCREEN_LOG, 'ab')
            f.write(d)
            f.close()
        except Exception:
            pass

    def _wraw(self, b):
        if self.dry is not None:
            self.dry.write(b)
            return
        if self.uart is not None:
            self.uart.write(b)

    def _wait(self, want, ms, also=None):
        if self.dry is not None:
            return want
        if self.uart is None:
            return None
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < ms:
            try:
                n = self.uart.any()
            except Exception:
                n = 0
            if n:
                try:
                    d = self.uart.read(n)
                except Exception:
                    d = None
                if d:
                    for b in d:
                        if b == want:
                            return want
                        if also is not None and b in also:
                            return b
                        if b == 0x04 or b == 0x06:
                            return b
            time.sleep_ms(2)
        return None

    def poll(self):
        """非阻塞：看有没有 0x01/0x02。返回 1 / 2 / None。"""
        if self.uart is None:
            return None
        try:
            n = self.uart.any()
        except Exception:
            return None
        if not n:
            return None
        try:
            d = self.uart.read(n)
        except Exception:
            return None
        if not d:
            return None
        self._log_rx(d)
        code = None
        for b in d:
            if b == 0x01:
                code = 1
            elif b == 0x02:
                code = 2
        if code is not None:
            print("[screen] 收到触发 0x%02X" % code)
        return code

    def drain(self):
        """清空串口接收缓冲（丢掉上一次残留的应答）。"""
        if self.uart is None:
            return
        try:
            n = self.uart.any()
            while n:
                self.uart.read(n)
                time.sleep_ms(2)
                n = self.uart.any()
        except Exception:
            pass

    def send_cmd(self, s):
        """给屏发一条指令（自动补 FF FF FF）。"""
        self._wraw(s.encode())
        self._wraw(b'\xff\xff\xff')
        print("[screen] 已发指令: %s" % s)

    def send_file(self, path, remote=None):
        if not self.ready():
            print("[screen] 没串口，跳过发送")
            return False
        try:
            size = os.stat(path)[6]
        except Exception as e:
            print("[screen] 读不到文件:", repr(e))
            return False
        if not remote:
            remote = SCREEN_FILE
        self.drain()          # 清掉残留应答，避免把旧的 0x06 当成这次失败
        # 屏健康检查（无回应只警告，不阻断）
        self._wraw(b'sendme')
        self._wraw(b'\xff\xff\xff')
        if self._wait(0x66, 700) != 0x66:
            print("[screen] 警告: sendme 无回应（屏可能卡在透传模式/线松了）")
            self.drain()
        t0 = time.ticks_ms()
        print("[screen] 目标: %s（%s）" % (
            remote, 'SD卡根目录' if remote.startswith('sd0/') else '见路径'))
        self._wraw(('twfile "%s",%d' % (remote, size)).encode())
        self._wraw(b'\xff\xff\xff')
        r = self._wait(0xFE, 6000)
        if r != 0xFE:
            print("[screen] twfile 未确认(%r)：屏没接 / 波特率不对 / 路径不对" % (r,))
            return False
        f = open(path, 'rb')
        pid = 0
        sent = 0
        got_end = False
        try:
            while sent < size:
                n = SCREEN_CHUNK
                if size - sent < n:
                    n = size - sent
                data = f.read(n)
                if not data:
                    break
                ln = len(data)
                hdr = bytes([0x3A, 0xA1, 0xBB, 0x44, 0x7F, 0xFF, 0xFE, 0x00,
                             pid & 0xFF, (pid >> 8) & 0xFF, ln & 0xFF, (ln >> 8) & 0xFF])
                self._wraw(hdr)
                self._wraw(data)
                r = self._wait(0x05, 6000, also=(0xFD,))
                pid += 1
                sent += ln
                if r == 0xFD:
                    got_end = True      # 最后一包：屏直接回 0xFD 表示传输完成
                    break
                if r != 0x05:
                    print("[screen] 第 %d 包失败(%r)，中止" % (pid - 1, r))
                    return False
        finally:
            f.close()
        r = 0xFD if got_end else self._wait(0xFD, 8000)
        ok = (r == 0xFD) or (self.dry is not None)
        print("[screen] 传完 %d 字节 / %d 包 / %d ms（末应答 %r）%s"
              % (size, pid, time.ticks_diff(time.ticks_ms(), t0), r,
                 'OK' if ok else '末尾未确认'))
        if ok and self.uart is not None:
            time.sleep_ms(80)          # 等屏从透传模式退回指令模式
            if SCREEN_AFTER_PAGE:
                self.send_cmd(SCREEN_AFTER_PAGE)
            if SCREEN_PIC_CTRL:
                if SCREEN_PIC_AUTORECT:
                    ox = (SCREEN_W - SEND_W) // 2
                    if ox < 0:
                        ox = 0
                    oy = (SCREEN_H - SEND_H) // 2
                    if oy < 0:
                        oy = 0
                    self.send_cmd('%s.x=%d' % (SCREEN_PIC_CTRL, ox))
                    self.send_cmd('%s.y=%d' % (SCREEN_PIC_CTRL, oy))
                    self.send_cmd('%s.w=%d' % (SCREEN_PIC_CTRL, SEND_W))
                    self.send_cmd('%s.h=%d' % (SCREEN_PIC_CTRL, SEND_H))
                self.send_cmd('%s.path="%s"' % (SCREEN_PIC_CTRL, remote))
        return ok

    def deinit(self):
        if self.dry is not None:
            try:
                self.dry.close()
            except Exception:
                pass
            self.dry = None
        if self.uart is not None:
            try:
                self.uart.deinit()
            except Exception:
                pass
            self.uart = None


# ============================== 一次完整处理 ==============================
def do_capture(pl, seg, style, face_det, idx, outline=True, face2=None):
    """KEY1 一次触发：抠图 -> 白底人像 -> 风格化 -> 换背景 -> 存 Zofour_nb_txt。"""
    t0 = time.ticks_ms()
    W = seg.display_size[0]
    H = seg.display_size[1]

    # 0) 主循环已不再持续跑分割，这里现跑一次，保证 seg.masks 对应当前画面
    try:
        img = pl.get_frame()
        seg.run(img)
    except Exception as e:
        print("  [warn] 取帧/分割失败:", repr(e))

    # 1) 抓一帧原图
    SW, SH, src_buf = grab_source_frame(pl)

    # 2) 用 mask 抠出 person（白底）
    mask_img = image.Image(W, H, image.ARGB8888, alloc=image.ALLOC_REF, data=seg.masks)
    mask_buf = mask_img.bytearray()
    out = bytearray(W * H * 3)
    white_row = bytearray(b"\xff" * (W * 3))
    for y in range(H):
        off = y * W * 3
        out[off:off + W * 3] = white_row
    person_px = compose_person_white(out, mask_buf, src_buf, W, H, SW, SH)
    print("  [1] 人像像素:", person_px)
    if person_px <= 0:
        print("  [!] 没抠到人，检查 kmodel / 是否有人在画面里")
        return None

    # 3) packed -> 平面
    planar = packed_to_planar(out, W, H)
    del out
    gc.collect()

    # 4) 训练构图 + 风格化（v4：先人脸检测 -> 以脸为中心构图 + 只留人脸连通块）
    face = None
    try:
        t_f = time.ticks_ms()
        bb = person_bbox(planar[0])
        if bb is not None:
            crop = face_crop_for(W, H, bb)
            face = face_det.detect(planar, crop)
        print("  [1b] 人脸检测 %d ms -> %r" % (time.ticks_ms() - t_f, face))
    except Exception as e:
        print("  [warn] 人脸检测失败:", repr(e))
        face = None
    roi = None
    seed = None
    if face is not None:
        roi = face_roi(W, H, face)
        if roi is not None:
            seed = (int((face[0] - roi[0]) * IN_W / roi[2]),
                    int((face[1] - roi[1]) * IN_H / roi[3]))
    if roi is None:
        print("  [!] 没人脸，回退到人像包围盒构图 + 最大连通块")
        roi = training_roi(W, H, planar[0])
    if roi is None:
        print("  [!] 找不到构图")
        return None
    print("  [2] 构图:", roi, "在卡片上的脸心:", seed)
    t_st = time.ticks_ms()
    seg_keep = None
    try:                      # v3：用分割 mask 限定人像范围，去掉背景影子
        t_k = time.ticks_ms()
        seg_keep = roi_keep_from_mask(mask_buf, W, H, roi)
        seg_keep = _dilate_sq(seg_keep, 2)
        print("  [2a] 分割遮罩 %d ms" % (time.ticks_ms() - t_k))
    except Exception as e:
        print("  [warn] 分割遮罩失败（回退到白底阈值）:", repr(e))
        seg_keep = None
    styled, keep = style.infer(planar, roi, seg_keep, seed)
    print("  [2b] 风格化 %d ms" % (time.ticks_ms() - t_st))
    try:
        keep = smooth_keep(keep)
    except Exception as e:
        print("  [warn] 轮廓平滑失败:", repr(e))
    del planar
    gc.collect()

    # 5) 白底版另存
    if SAVE_WHITE:
        try:
            wi, _wb = planar_to_image(styled)
            save_hwc(_wb, SAVE_DIR + "/white_" + str(idx) + ".jpg")
            del wi, _wb
            gc.collect()
        except Exception as e:
            print("  [warn] 白底保存失败:", repr(e))

    # 6) 换背景 + 存合成
    bgname = pick_background()
    if bgname is None:
        print("  [!] 没有背景")
        return None
    bg, raw = load_bg_rgb888(bgname)
    comp = composite(styled, keep, bg)
    del bg, raw, styled
    gc.collect()
    # 6b) 脸部高倍重绘（style_s2）：从原图裁脸 -> 动漫脸 -> 贴回卡片对应位置
    if FACE2_ON and face2 is not None and face is not None:
        try:
            t_f2 = time.ticks_ms()
            b2 = face2_box(face[0], face[1], face[2], face[3], W, H)
            psrc = packed_to_planar(src_buf, W, H)
            chw2 = face2.infer(psrc, b2)
            del psrc
            gc.collect()
            sw2 = paste_face2(comp, chw2, b2, roi, keep)
            del chw2
            gc.collect()
            print("   [face2] box=%r 贴入=%dpx %d ms" % (b2, sw2, time.ticks_ms() - t_f2))
        except Exception as e:
            print("   [warn] 脸部重绘失败:", repr(e))
    try:
        if outline:
            draw_person_outline(comp, keep, OUTLINE_BLACK_R, OUTLINE_BLACK_COLOR)
            print("   [outline] 黑色描边 %dpx" % OUTLINE_BLACK_R)
        else:
            print("   [outline] 不描边（02）")
    except Exception as e:
        print("   [warn] 描边失败:", repr(e))
    del keep
    gc.collect()
    try:
        apply_deco(comp, bgname)
    except Exception as e:
        print("   [warn] 装饰层失败:", repr(e))
    path = SAVE_DIR + "/result_" + str(idx) + ".jpg"
    save_hwc(comp, path, SAVE_QUALITY)
    size = os.stat(path)[6]
    send_path = path
    try:
        send_path = SAVE_DIR + "/send_" + str(idx) + ".jpg"
        sb = save_send_jpeg(comp, send_path)
        print("   [send] 小图 %d 字节（%dx%d 4:2:0 q%d）" % (sb, SEND_W, SEND_H, SEND_QUALITY))
    except Exception as e:
        print("   [warn] 小图生成失败（改发原图）:", repr(e))
        send_path = path
    del comp
    gc.collect()
    print("  [3] 背景=%s -> %s (%d 字节, 总 %d ms)"
          % (bgname, path, size, time.ticks_ms() - t0))
    return (path, bgname, person_px, send_path)


# ============================== 离线自检 ==============================
def offline_capture(style, idx):
    """离线自检：用 /sdcard/temp/picture_125.jpg 走风格化+合成+存盘（不碰相机/display）。"""
    src = "/sdcard/temp/picture_125.jpg"
    t0 = time.ticks_ms()
    planar, H, W = decode_to_planar(src)
    roi = training_roi(W, H, planar[0])
    print("  [off] src=%s %dx%d roi=%r" % (src, W, H, roi))
    if roi is None:
        return None
    t_st = time.ticks_ms()
    styled, keep = style.infer(planar, roi)
    print("  [off] 风格化 %d ms" % (time.ticks_ms() - t_st))
    try:
        keep = smooth_keep(keep)
    except Exception as e:
        print("  [warn] 轮廓平滑失败:", repr(e))
    del planar
    gc.collect()
    if SAVE_WHITE:
        wi, wb = planar_to_image(styled)
        save_hwc(wb, SAVE_DIR + "/white_" + str(idx) + ".jpg")
        del wi, wb
        gc.collect()
    bgname = pick_background()
    bg, raw = load_bg_rgb888(bgname)
    comp = composite(styled, keep, bg)
    del bg, raw, styled
    gc.collect()
    try:
        draw_person_outline(comp, keep)
    except Exception as e:
        print("   [warn] 描边失败:", repr(e))
    del keep
    gc.collect()
    try:
        apply_deco(comp, bgname)
    except Exception as e:
        print("   [warn] 装饰层失败:", repr(e))
    path = SAVE_DIR + "/result_" + str(idx) + ".jpg"
    save_hwc(comp, path)
    print("  [off] bg=%s -> %s (%d B, %d ms)"
          % (bgname, path, os.stat(path)[6], time.ticks_ms() - t0))
    return path


# ============================== 主程序 ==============================
def main():
    display_mode = "lcd"
    display_size = [800, 480]
    rgb888p_size = [320, 320]

    ensure_dir(SAVE_DIR)

    # 自动测试开关
    auto_delay = None
    auto_offline = False
    try:
        f = open(AUTO_FLAG, "r")
        s = f.read().strip()
        f.close()
        if s.lower().startswith("off"):
            auto_offline = True
        else:
            auto_delay = float(s) if s else 3.0
    except Exception:
        auto_delay = None

    if auto_offline:
        print("[auto] 离线自检模式（不碰相机）")
        style = StyleModel()
        idx = next_index(SAVE_DIR)
        offline_capture(style, idx)
        print("[auto] 离线自检完成")
        return

    kmodel_path = pick_kmodel()
    pl = PipeLine(rgb888p_size=rgb888p_size, display_size=display_size, display_mode=display_mode)
    pl.create()
    print("[pipe] display_size:", pl.get_display_size(), "seg kmodel:", kmodel_path)

    try:
        if os.stat('/sdcard/temp/_collect')[6] >= 0:
            collect_raw_frames(pl, 25, 1.2)
    except Exception:
        pass

    seg = SegmentationApp(kmodel_path, labels=LABELS, model_input_size=[320, 320],
                          confidence_threshold=0.2, nms_threshold=0.5, mask_threshold=0.5,
                          rgb888p_size=rgb888p_size, display_size=display_size, debug_mode=0)
    seg.config_preprocess()

    print("[style] 加载风格模型...")
    style = StyleModel()
    print("[style] OK")

    print("[face] 加载人脸检测模型...")
    face_det = FaceDetector()
    print("[face] OK")

    face2 = None
    if FACE2_ON:
        try:
            print("[face2] 加载脸部专精模型...")
            face2 = FaceStyle2()
            print("[face2] OK")
        except Exception as e:
            print("[face2] 加载失败（跳过脸部重绘）:", repr(e))
            face2 = None

    print("[screen] 初始化串口屏链路...")
    try:
        screen = ScreenLink()
    except Exception as e:
        print("[screen] 初始化异常:", repr(e))
        screen = None

    print("[wifi] 启动热点 + HTTP 下载服务...")
    try:
        import wifi_http
        wifi_http.start()
    except Exception as e:
        print("[wifi] 跳过:", repr(e))

    _fpioa = FPIOA()
    _fpioa.set_function(KEY_PIN, FPIOA.GPIO61, ie=1, oe=0)
    key1 = Pin(KEY_PIN, Pin.IN, pull=Pin.PULL_UP, drive=7)
    _pressed = [False]

    def _cb(pin):
        _pressed[0] = True

    try:
        key1.irq(trigger=Pin.IRQ_FALLING, handler=_cb)
        irq_ok = True
    except Exception as e:
        irq_ok = False
    print("[key] key1(GPIO%d) ok=%d 当前=%d" % (KEY_PIN, irq_ok, key1.value()))

    idx = next_index(SAVE_DIR)
    save_index = idx
    last_key = key1.value()
    t_start = time.ticks_ms()
    banner = "KEY1 = catch  ->  " + SAVE_DIR
    last_keep = time.ticks_ms()

    try:
        while True:
            os.exitpoint()
            # 本机没有 LCD，预览无意义：空闲时不跑分割/刷屏/gc，把 CPU 全留给 WiFi 下载
            # 每秒才取一帧保活，避免 sensor 流水线停住导致拍照拿到旧帧
            if time.ticks_ms() - last_keep > 1000:
                last_keep = time.ticks_ms()
                try:
                    pl.get_frame()
                except Exception:
                    pass
            v = key1.value()
            key_hit = _pressed[0] or (last_key == 1 and v == 0)
            last_key = v

            ser_hit = 0
            if screen is not None:
                sc = screen.poll()
                if sc is not None:
                    ser_hit = sc

            auto_hit = False
            if auto_delay is not None and (time.ticks_ms() - t_start) > auto_delay * 1000:
                auto_hit = True   # 自动测试

            if key_hit or ser_hit or auto_hit:
                # 02 = 不描边；01 / KEY1 / 自动 = 黑色描边
                outline_req = (ser_hit != 2)
                if ser_hit:
                    trig = 'serial 0x%02X' % ser_hit
                elif key_hit:
                    trig = 'KEY1'
                else:
                    trig = 'auto'
                if key_hit and auto_delay is None:
                    time.sleep_ms(30)
                print("[catch] 第 %d 张 ...（触发=%s 描边=%s）" % (save_index, trig, outline_req))
                try:
                    r = do_capture(pl, seg, style, face_det, save_index, outline_req, face2)
                    if r:
                        if screen is not None and screen.ready():
                            remote = (SCREEN_SD_ROOT + SCREEN_FILE_NAME + "_"
                                      + str(next_pic_index()) + ".jpg")
                            screen.send_file(r[3], remote)
                        save_index += 1
                except Exception as e:
                    print("[catch] 失败:", repr(e))
                # 松手 / 清抖
                while auto_delay is None and key1.value() == 0:
                    time.sleep_ms(10)
                _pressed[0] = False
                last_key = 1
                if auto_delay is not None:
                    print("[auto] 测试完成，退出")
                    break
            time.sleep_ms(20)
    except Exception as e:
        print("ERROR:", e)
    finally:
        try:
            seg.deinit()
        except Exception:
            pass
        try:
            pl.destroy()
        except Exception:
            pass
        print("[pipe] 已退出")


if not globals().get('SKIP_MAIN'):
    main()
