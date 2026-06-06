"""
冒险岛Boss监控脚本
- 截取主屏幕
- 用模板匹配检测Boss出现（mask忽略白色背景）
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
CHECK_INTERVAL = 1        # 检测间隔（秒）
MATCH_THRESHOLD = 0.7    # 匹配阈值（0-1），越高越严格不容易误报，越低越灵敏
MONITOR_ONLY_MAIN = True  # True=只监控主屏幕（双屏适用）
PREVIEW_SCALE = 0.25     # 监控窗口预览缩放比例（越小窗口越小）
WINDOW_X = -520            # 窗口X坐标（负数=主屏左侧，即副屏）
WINDOW_Y = 980            # 窗口Y坐标（距顶部，1440屏的话靠近底部）
# ===========================================

running = True


def prepare_template(template_img):
    """处理模板：把白色/近白色背景填充成随机噪声，避免误匹配"""
    img = template_img.copy()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    white_mask = gray > 230
    # 用随机噪点填充白色区域（不可能跟游戏画面匹配）
    noise = np.random.randint(0, 256, img.shape, dtype=np.uint8)
    img[white_mask] = noise[white_mask]
    return img


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


def detect_boss(screen_img, template_img):
    screen_gray = cv2.cvtColor(screen_img, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)

    best_match = 0
    found = False
    best_loc = None
    best_size = None

    scales = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2]

    for scale in scales:
        scaled_tmpl = cv2.resize(template_gray, None, fx=scale, fy=scale)
        sh, sw = scaled_tmpl.shape
        if sh > screen_gray.shape[0] or sw > screen_gray.shape[1]:
            continue

        # 使用TM_CCOEFF_NORMED，随机噪点区域不会产生有意义的相关性
        result = cv2.matchTemplate(screen_gray, scaled_tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val > best_match:
            best_match = max_val
            best_loc = max_loc
            best_size = (sw, sh)

        if max_val >= MATCH_THRESHOLD:
            found = True
            break

    if found:
        top_left = best_loc
        bottom_right = (top_left[0] + best_size[0], top_left[1] + best_size[1])
        cv2.rectangle(screen_img, top_left, bottom_right, (0, 255, 0), 3)

    return found, best_match, screen_img


def send_alert(msg, count):
    full_msg = f"{msg}\n\n已累计检测到 {count} 次"
    ctypes.windll.user32.MessageBoxW(0, full_msg, "🦉 Boss刷新提醒！", 0x00000040 | 0x00001000)


class MonitorWindow:
    """小型监控窗口，显示实时预览和状态"""

    def __init__(self, master, template_path):
        self.master = master
        self.template_path = template_path
        self.detected_count = 0
        self.last_status = "等待中..."
        self.last_confidence = 0
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

        # 标题行
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

        # 底部信息
        ttk.Label(main_frame, text=f"阈值: {MATCH_THRESHOLD:.0%} | 间隔: {CHECK_INTERVAL}s | 主屏幕: {MONITOR_ONLY_MAIN}",
                  font=("微软雅黑", 7), foreground="gray").pack(anchor=tk.W)

    def update_preview(self, img_array, found, confidence):
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

        pct = min(confidence * 100, 100)
        self.progress['value'] = pct
        self.conf_label.set(f"{pct:.1f}%")

    def on_close(self):
        global running
        running = False
        self.master.destroy()


def monitor_loop(window, template):
    """监控主循环（子线程）"""
    global running

    while running:
        try:
            screen = capture_main_screen()
            found, confidence, marked = detect_boss(screen, template)

            window.master.after(0, window.update_preview, marked, found, confidence)

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

            time.sleep(max(CHECK_INTERVAL, 0.5))

        except Exception as e:
            print(f"检测出错: {e}")
            time.sleep(CHECK_INTERVAL)


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

    # 处理模板（白色背景填充噪点，避免误匹配）
    template = prepare_template(template)

    # 启动tkinter窗口
    root = tk.Tk()
    window = MonitorWindow(root, template_path)

    print(f"🦉 冒险岛Boss监控已启动")
    print(f"   模板: {template_path} ({template.shape[1]}x{template.shape[0]})")
    print(f"   间隔: {CHECK_INTERVAL}s | 阈值: {MATCH_THRESHOLD} | 主屏: {MONITOR_ONLY_MAIN}")
    print(f"   Mask: 噪点填充白色背景")

    # 启动监控线程
    t = threading.Thread(target=monitor_loop, args=(window, template), daemon=True)
    t.start()

    root.mainloop()
    print("监控已停止。")


if __name__ == "__main__":
    main()
