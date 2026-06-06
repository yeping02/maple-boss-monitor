"""
冒险岛Boss监控脚本
- 截取主屏幕
- ORB特征点匹配检测Boss出现（不受背景/缩放影响）
- 弹窗提醒 + 小型监控窗口显示实时状态

依赖安装:
    pip install opencv-python numpy Pillow

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
    print("需要安装OpenCV，运行: pip install opencv-python numpy Pillow")
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
BOSS_IMAGE_PATH = "boss_template.png"  # boss截图文件名，和脚本同目录
CHECK_INTERVAL = 0.1      # 检测间隔（秒）
MATCH_THRESHOLD = 0.6      # 匹配阈值（0-1），ORB匹配得分比例
MIN_MATCH_COUNT = 15       # 最少需要多少个特征点匹配才算boss
MONITOR_ONLY_MAIN = True   # True=只监控主屏幕（双屏适用）
PREVIEW_SCALE = 0.25       # 监控窗口预览缩放比例
WINDOW_X = -520            # 窗口X坐标（负数=主屏左侧，即副屏）
WINDOW_Y = 980             # 窗口Y坐标（距顶部）
# ===========================================

running = True

# 全局ORB检测器
orb = cv2.ORB_create(nfeatures=1000)
# BFMatcher with Hamming距离（ORB用的是二进制描述子）
bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)


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
    return np.array(screenshot)


def extract_orb_features(img_bgr):
    """从图像中提取ORB特征点和描述子，去除白色背景区域的特征"""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    # 创建mask：白色区域忽略
    mask = np.ones_like(gray, dtype=np.uint8) * 255
    white = gray > 220
    mask[white] = 0
    # 检测特征点
    kp, des = orb.detectAndCompute(gray, mask)
    return kp, des


def detect_boss(screen_img, template_kp, template_des):
    """用ORB特征点匹配检测boss"""
    # 下采样加速检测
    h, w = screen_img.shape[:2]
    if h > 720:
        scale = 720 / h
        small = cv2.resize(screen_img, None, fx=scale, fy=scale)
    else:
        small = screen_img
        scale = 1.0

    screen_gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    screen_kp, screen_des = orb.detectAndCompute(screen_gray, None)

    if screen_des is None or template_des is None:
        return False, 0.0, 0, screen_img

    # KNN匹配，ratio test过滤
    matches = bf.knnMatch(template_des, screen_des, k=2)
    good = []
    for match_pair in matches:
        if len(match_pair) == 2:
            m, n = match_pair
            if m.distance < 0.75 * n.distance:
                good.append(m)

    match_count = len(good)
    # 匹配得分 = 匹配数 / 模板特征数
    score = match_count / max(len(template_kp), 1)

    found = match_count >= MIN_MATCH_COUNT

    # 在截图上画出匹配点
    marked = screen_img.copy()
    if match_count > 0 and scale < 1.0:
        # 如果下采样了，把匹配点坐标映射回原图
        pts = [(int(m.queryIdx), int(m.trainIdx)) for m in good[:50]]
        # 画出一些匹配点作为标记
        display = cv2.resize(small, (w, h))
        for m in good[:50]:
            sx, sy = screen_kp[m.trainIdx].pt
            cv2.circle(display, (int(sx / scale), int(sy / scale)), 3, (0, 255, 0), -1)
        marked = display
    elif match_count > 0:
        for m in good[:50]:
            sx, sy = screen_kp[m.trainIdx].pt
            cv2.circle(marked, (int(sx / scale), int(sy / scale)), 3, (0, 255, 0), -1)

    return found, score, match_count, marked


def send_alert(msg, count):
    full_msg = f"{msg}\n\n已累计检测到 {count} 次"
    ctypes.windll.user32.MessageBoxW(0, full_msg, "🦉 Boss刷新提醒！", 0x00000040 | 0x00001000)


class MonitorWindow:
    """小型监控窗口，显示实时预览和状态"""

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

        # 加载模板缩略图
        try:
            tmpl = Image.open(template_path).resize((60, 60))
            self._tmpl_photo = ImageTk.PhotoImage(tmpl)
        except:
            self._tmpl_photo = None

        # 预览尺寸
        self.preview_w = int(1920 * PREVIEW_SCALE)
        self.preview_h = int(1080 * PREVIEW_SCALE)

        # --- 布局 ---
        main_frame = ttk.Frame(master, padding=6)
        main_frame.pack()

        top = ttk.Frame(main_frame)
        top.pack(fill=tk.X, pady=(0, 4))

        if self._tmpl_photo:
            ttk.Label(top, image=self._tmpl_photo).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Label(top, text="Boss监控运行中", font=("微软雅黑", 10, "bold")).pack(side=tk.LEFT)

        # 预览图
        self.preview_label = ttk.Label(main_frame)
        self.preview_label.pack(pady=2)

        # 状态信息
        self.status_var = tk.StringVar(value="初始化...")
        ttk.Label(main_frame, textvariable=self.status_var, font=("Consolas", 9)).pack(anchor=tk.W, pady=1)

        # 匹配度进度条
        pb_frame = ttk.Frame(main_frame)
        pb_frame.pack(fill=tk.X, pady=2)
        ttk.Label(pb_frame, text="匹配度:", font=("微软雅黑", 8)).pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(pb_frame, length=150, maximum=100, mode='determinate')
        self.progress.pack(side=tk.LEFT, padx=4)
        self.conf_label = tk.StringVar(value="0.0%")
        ttk.Label(pb_frame, textvariable=self.conf_label, font=("Consolas", 8), width=6).pack(side=tk.LEFT)

        # 特征点数
        self.match_var = tk.StringVar(value="特征点: 0")
        ttk.Label(main_frame, textvariable=self.match_var, font=("微软雅黑", 8), foreground="gray").pack(anchor=tk.W)

        ttk.Label(main_frame, text=f"阈值: {MATCH_THRESHOLD:.0%} | 最少{MIN_MATCH_COUNT}点 | 间隔: {CHECK_INTERVAL}s",
                  font=("微软雅黑", 7), foreground="gray").pack(anchor=tk.W)

    def update_preview(self, img_array, found, score, match_count):
        """更新预览图和状态"""
        small = cv2.resize(img_array, (self.preview_w, self.preview_h))
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        self._photo = ImageTk.PhotoImage(pil_img)
        self.preview_label.config(image=self._photo)

        now = time.strftime("%H:%M:%S")
        if found:
            self.detected_count += 1
            self.status_var.set(f"🚨 [{now}] BOSS出现! (第{self.detected_count}次)")
        else:
            self.status_var.set(f"  [{now}] 未检测到")

        pct = min(score * 100, 100)
        self.progress['value'] = pct
        self.conf_label.set(f"{pct:.1f}%")
        self.match_var.set(f"特征点匹配: {match_count}/{MIN_MATCH_COUNT}")

    def on_close(self):
        global running
        running = False
        self.master.destroy()


def monitor_loop(window, template_kp, template_des):
    """监控主循环（子线程）"""
    global running

    while running:
        try:
            screen = capture_main_screen()
            found, score, match_count, marked = detect_boss(screen, template_kp, template_des)

            window.master.after(0, window.update_preview, marked, found, score, match_count)

            if found and not window._alert_cooldown:
                window.master.after(0, send_alert, "🦉 BOSS出现了！快去打！", window.detected_count)
                ts = int(time.time())
                cv2.imwrite(f"boss_detected_{ts}.png", marked)
                window._alert_cooldown = True
                cooldown_end = time.time() + 60
                while running and time.time() < cooldown_end:
                    time.sleep(1)
                window._alert_cooldown = False
            elif not found:
                window._alert_cooldown = False

        except Exception as e:
            print(f"检测出错: {e}")
        time.sleep(max(CHECK_INTERVAL, 0.05))


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(script_dir, BOSS_IMAGE_PATH)

    if not os.path.exists(template_path):
        msg = f"找不到boss模板图片!\n请将boss截图保存为:\n{template_path}"
        ctypes.windll.user32.MessageBoxW(0, msg, "配置错误", 0x00000010)
        sys.exit(1)

    template = cv2.imread(template_path)
    if template is None:
        msg = f"无法读取图片:\n{template_path}"
        ctypes.windll.user32.MessageBoxW(0, msg, "配置错误", 0x00000010)
        sys.exit(1)

    # 提取模板ORB特征（忽略白色背景）
    template_kp, template_des = extract_orb_features(template)
    print(f"🦉 冒险岛Boss监控已启动")
    print(f"   模板: {template_path} ({template.shape[1]}x{template.shape[0]})")
    print(f"   特征点数: {len(template_kp)}")
    print(f"   间隔: {CHECK_INTERVAL}s | 最少匹配: {MIN_MATCH_COUNT}点")

    if len(template_kp) < MIN_MATCH_COUNT:
        msg = f"模板特征点太少({len(template_kp)}点)，请换一张更清晰的boss截图"
        ctypes.windll.user32.MessageBoxW(0, msg, "配置警告", 0x00000030)
        print(f"   ⚠️ 警告: 特征点太少")

    root = tk.Tk()
    window = MonitorWindow(root, template_path)

    t = threading.Thread(target=monitor_loop, args=(window, template_kp, template_des), daemon=True)
    t.start()

    root.mainloop()
    print("监控已停止。")


if __name__ == "__main__":
    main()
