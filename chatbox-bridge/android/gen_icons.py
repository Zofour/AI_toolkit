"""从 Chatbox 图标生成 Android launcher 图标（各密度 + 自适应前景）。"""
import os
from PIL import Image

SRC = r"C:\Program Files\Chatbox\resources\assets\icons\1024x1024.png"
RES = r"C:\chatbox_temp\chatbox-bridge\android\app\src\main\res"

LEGACY = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
# 自适应前景：108dp 画布，内容占中央 66%（安全区 72/108）
FG = {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}


def main():
    src = Image.open(SRC).convert("RGBA")
    for d, sz in LEGACY.items():
        folder = os.path.join(RES, f"mipmap-{d}")
        os.makedirs(folder, exist_ok=True)
        src.resize((sz, sz), Image.LANCZOS).save(os.path.join(folder, "ic_launcher.png"))
        print("legacy", d, sz)
    for d, canvas in FG.items():
        folder = os.path.join(RES, f"mipmap-{d}")
        inner = round(canvas * 0.66)
        img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        icon = src.resize((inner, inner), Image.LANCZOS)
        off = (canvas - inner) // 2
        img.paste(icon, (off, off), icon)
        img.save(os.path.join(folder, "ic_launcher_foreground.png"))
        print("fg", d, canvas)
    print("done")


if __name__ == "__main__":
    main()
