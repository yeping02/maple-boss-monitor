"""
冒险岛Boss监控脚本
- 截取主屏幕
- SIFT特征点匹配检测Boss出现
- 正确处理RGBA模板（alpha通道做mask）
- 弹窗提醒 + 小型监控窗口显示实时状态

依赖安装:
    pip install opencv-contrib-python numpy Pillow

使用方法:
    1. 把boss截图保存为 boss_template.png，和本脚本放同一目录
    2. 运行: python maple_boss_monitor.py
    3. Ctrl+C 或关闭监控窗口停止
"""

import time
import os
import sys
import ctypes
import threading
import numpy as np
from datetime import datetime

try:
    import cv2
except ImportError:
    print("需要安装opencv-contrib-python: pip install opencv-contrib-python numpy Pillow")
    sys.exit(1)

try:
    from PIL import ImageGrab, Image
    from PIL import ImageTk
except ImportError:
    print("需要安装Pillow，运行: pip install Pillow")
    sys.exit(1)

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    print("需要tkinter（Python自带，如果缺失请重新安装Python）")
    sys.exit(1)

# ============ 配置（可按需修改） ============
BOSS_IMAGE_PATH = "boss_template.png"  # boss截图文件名
CHECK_INTERVAL = 0.5      # 检测间隔（秒）
MIN_MATCH_COUNT = 8        # 最少特征点匹配数
MONITOR_ONLY_MAIN = True   # True=只监控主屏幕（双屏适用）
PREVIEW_SCALE = 0.25       # 监控窗口预览缩放比例
WINDOW_X = -520            # 窗口X坐标
WINDOW_Y = 980             # 窗口Y坐标
# ===========================================

running = True

sift = cv2.SIFT_create(nfeatures=500)
bf = cv2.BFMatcher(cv2.NORM_L2)


def load_template(path):
    """加载模板图片，正确处理RGBA alpha通道"""
    # 用PIL读取保留alpha
    pil_img = Image.open(path).convert("RGBA")
    arr = np.array(pil_img)  # RGBA

    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3]

    # PIL是RGB, 转BGR给OpenCV
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    # 用alpha通道做mask（透明区域忽略）
    mask = np.where(alpha > 128, 255, 0).astype(np.uint8)

    return bgr, mask


def get_primary_screen_bounds():
    user32 = ctypes.windll.user32
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    return (0, 0, w, h)


def capture_main_screen():
    if MONITOR_ONLY_MAIN:
        bounds = get_primary_screen_bounds()
        screenshot = ImageGrab.grab(bbox=bounds)
    else:
        screenshot = ImageGrab.grab()

    arr = np.array(screenshot)
    # 去掉alpha通道
    if arr.ndim == 3 and arr.shape[2] == 4:
        arr = arr[:, :, :3]
    # PIL RGB -> OpenCV BGR
    arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    return arr


def extract_sift_features(img_bgr, mask):
    """提取SIFT特征，使用mask排除背景"""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    kp, des = sift.detectAndCompute(gray, mask)
    return kp, des


def detect_boss(screen_bgr, template_kp, template_des):
    """在截屏中用SIFT匹配检测boss"""
    h, w = screen_bgr.shape[:2]
    best_match_count = 0
    best_score = 0
    found = False
    marked = screen_bgr.copy()

    scales = [0.5, 0.75, 1.0]

    for scale in scales:
        if scale < 1.0:
            small = cv2.resize(screen_bgr, None, fx=scale, fy=scale)
        else:
            small = screen_bgr

        screen_gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        screen_kp, screen_des = sift.detectAndCompute(screen_gray, None)

        if screen_des is None or template_des is None:
            continue

        matches = bf.knnMatch(template_des, screen_des, k=2)

        good = []
        for pair in matches:
            if len(pair) == 2:
                m, n = pair
                if m.distance < 0.75 * n.distance:
                    good.append(m)

        match_count = len(good)
        score = match_count / max(len(template_kp), 1)

        if match_count > best_match_count:
            best_match_count = match_count
            best_score = score

        if match_count >= MIN_MATCH_COUNT:
            found = True
            display = small.copy()
            for m in good:
                sx, sy = screen_kp[m.trainIdx].pt
                cv2.circle(display, (int(sx), int(sy)), 4, (0, 255, 0), -1)
            if scale < 1.0:
                marked = cv2.resize(display, (w, h))
            else:
                marked = display
            break

    return found, best_score, best_match_count, marked


def send_alert(msg, count):
    full_msg = f"{msg}\n\n已累计检测到 {count} 次"
    ctypes.windll.user32.MessageBoxW(0, full_msg, "🦉 Boss刷新提醒！", 0x00000040 | 0x00001000)


class MonitorWindow:
    """小型监控窗口"""

    def __init__(self, master, template_path):
        self.master = master
        self.template_path = template_path
        self.detected_count = 0
        self._photo = None
        self._alert_cooldown = False

        master.title("🦉 冒险岛Boss监控")
        master.resizable(False, False)
        master.geometry(f"+{WINDOW_X}+{WINDOW_Y}")
        master.protocol("WM_DELETE_WINDOW", self.on_close)

        try:
            tmpl = Image.open(template_path).resize((60, 60))
            self._tmpl_photo = ImageTk.PhotoImage(tmpl)
        except:
            self._tmpl_photo = None

        self.preview_w = int(1920 * PREVIEW_SCALE)
        self.preview_h = int(1080 * PREVIEW_SCALE)

        main_frame = ttk.Frame(master, padding=6)
        main_frame.pack()

        top = ttk.Frame(main_frame)
        top.pack(fill=tk.X, pady=(0, 4))
        if self._tmpl_photo:
            ttk.Label(top, image=self._tmpl_photo).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(top, text="Boss监控运行中", font=("微软雅黑", 10, "bold")).pack(side=tk.LEFT)

        self.preview_label = ttk.Label(main_frame)
        self.preview_label.pack(pady=2)

        self.status_var = tk.StringVar(value="初始化...")
        ttk.Label(main_frame, textvariable=self.status_var, font=("Consolas", 9)).pack(anchor=tk.W, pady=1)

        pb_frame = ttk.Frame(main_frame)
        pb_frame.pack(fill=tk.X, pady=2)
        ttk.Label(pb_frame, text="匹配:", font=("微软雅黑", 8)).pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(pb_frame, length=120, maximum=100, mode='determinate')
        self.progress.pack(side=tk.LEFT, padx=4)
        self.conf_label = tk.StringVar(value="0.0%")
        ttk.Label(pb_frame, textvariable=self.conf_label, font=("Consolas", 8), width=6).pack(side=tk.LEFT)

        self.match_var = tk.StringVar(value="点: 0/8")
        ttk.Label(main_frame, textvariable=self.match_var, font=("Consolas", 9)).pack(anchor=tk.W)

        ttk.Label(main_frame, text=f"SIFT | 间隔{CHECK_INTERVAL}s | 阈值{MIN_MATCH_COUNT}点",
                  font=("微软雅黑", 7), foreground="gray").pack(anchor=tk.W)

    def update_preview(self, img_bgr, found, score, match_count):
        small = cv2.resize(img_bgr, (self.preview_w, self.preview_h))
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        self._photo = ImageTk.PhotoImage(pil_img)
        self.preview_label.config(image=self._photo)

        now = time.strftime("%H:%M:%S")
        if found:
            self.detected_count += 1
            self.status_var.set(f"🚨 [{now}] BOSS! (第{self.detected_count}次)")
        else:
            self.status_var.set(f"  [{now}] 未检测到")

        pct = min(score * 100, 100)
        self.progress['value'] = pct
        self.conf_label.set(f"{pct:.1f}%")
        self.match_var.set(f"点: {match_count}/{MIN_MATCH_COUNT}")

    def on_close(self):
        global running
        running = False
        self.master.destroy()


def monitor_loop(window, template_kp, template_des):
    global running

    while running:
        try:
            screen = capture_main_screen()
            found, score, match_count, marked = detect_boss(screen, template_kp, template_des)
            window.master.after(0, window.update_preview, marked, found, score, match_count)

            if found and not window._alert_cooldown:
                window.master.after(0, send_alert, "🦉 BOSS出现了！快去打！", window.detected_count)
                ts = int(time.time())
                save_img = cv2.cvtColor(marked, cv2.COLOR_BGR2RGB)
                Image.fromarray(save_img).save(f"boss_detected_{ts}.png")
                window._alert_cooldown = True
                cooldown_end = time.time() + 60
                while running and time.time() < cooldown_end:
                    time.sleep(1)
                window._alert_cooldown = False
            elif not found:
                window._alert_cooldown = False

        except Exception as e:
            print(f"检测出错: {e}")
        time.sleep(max(CHECK_INTERVAL, 0.1))


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(script_dir, BOSS_IMAGE_PATH)

    if not os.path.exists(template_path):
        msg = f"找不到boss模板图片!\n请将boss截图保存为:\n{template_path}"
        ctypes.windll.user32.MessageBoxW(0, msg, "配置错误", 0x00000010)
        sys.exit(1)

    # 用PIL加载模板（保留alpha通道做mask）
    if not os.path.exists(template_path):
        msg = f"找不到模板: {template_path}"
        ctypes.windll.user32.MessageBoxW(0, msg, "配置错误", 0x00000010)
        sys.exit(1)

    template_bgr, template_mask = load_template(template_path)
    template_kp, template_des = extract_sift_features(template_bgr, template_mask)

    print(f"🦉 冒险岛Boss监控已启动")
    print(f"   模板: {template_path} ({template_bgr.shape[1]}x{template_bgr.shape[0]})")
    print(f"   SIFT特征点: {len(template_kp)} (仅boss区域)")
    if len(template_kp) < MIN_MATCH_COUNT:
        print(f"   ⚠️ 警告: 特征点太少({len(template_kp)})")

    root = tk.Tk()
    window = MonitorWindow(root, template_path)

    t = threading.Thread(target=monitor_loop, args=(window, template_kp, template_des), daemon=True)
    t.start()

    root.mainloop()
    print("监控已停止。")


if __name__ == "__main__":
    main()
