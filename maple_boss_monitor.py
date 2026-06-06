"""
冒险岛Boss监控脚本
- 截取主屏幕
- 用模板匹配检测Boss出现
- 检测到弹窗提醒

依赖安装:
    pip install opencv-python numpy Pillow

使用方法:
    1. 把boss截图保存为 boss_template.png，和本脚本放同一目录
    2. 运行: python maple_boss_monitor.py
    3. Ctrl+C 停止
"""

import time
import os
import sys
import ctypes
import numpy as np

try:
    import cv2
except ImportError:
    print("需要安装OpenCV，运行: pip install opencv-python numpy Pillow")
    sys.exit(1)

try:
    from PIL import ImageGrab
except ImportError:
    print("需要安装Pillow，运行: pip install Pillow")
    sys.exit(1)

# ============ 配置（可按需修改） ============
BOSS_IMAGE_PATH = "boss_template.png"  # boss截图文件名，和脚本同目录
CHECK_INTERVAL = 3        # 检测间隔（秒），建议3-5秒
MATCH_THRESHOLD = 0.7    # 匹配阈值（0-1），越高越严格不容易误报，越低越灵敏
MONITOR_ONLY_MAIN = True  # True=只监控主屏幕（双屏适用）
# ===========================================

def get_primary_screen_bounds():
    """获取主屏幕区域（Windows双屏时只取主屏）"""
    user32 = ctypes.windll.user32
    
    # 获取主屏幕分辨率
    w = user32.GetSystemMetrics(0)   # SM_CXSCREEN
    h = user32.GetSystemMetrics(1)   # SM_CYSCREEN
    
    return (0, 0, w, h)

def capture_main_screen():
    """截取主屏幕"""
    if MONITOR_ONLY_MAIN:
        bounds = get_primary_screen_bounds()
        print(f"  截屏区域: 主屏幕 {bounds[2]}x{bounds[3]}")
        screenshot = ImageGrab.grab(bbox=bounds)
    else:
        screenshot = ImageGrab.grab()
    return np.array(screenshot)

def detect_boss(screen_img, template_img):
    """多尺度模板匹配检测boss"""
    screen_gray = cv2.cvtColor(screen_img, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)

    best_match = 0
    found = False
    best_loc = None
    best_size = None

    # 多缩放比例匹配，适应不同分辨率
    scales = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2]
    
    for scale in scales:
        scaled = cv2.resize(template_gray, None, fx=scale, fy=scale)
        sh, sw = scaled.shape
        if sh > screen_gray.shape[0] or sw > screen_gray.shape[1]:
            continue

        result = cv2.matchTemplate(screen_gray, scaled, cv2.TM_CCOEFF_NORMED)
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
    """Windows弹窗提醒"""
    full_msg = f"{msg}\n\n已累计检测到 {count} 次"
    # MB_ICONINFORMATION + MB_SYSTEMMODAL（置顶弹窗）
    ctypes.windll.user32.MessageBoxW(0, full_msg, "🦉 Boss刷新提醒！", 0x00000040 | 0x00001000)

def main():
    # 检查模板图片
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

    print("=" * 50)
    print("🦉 冒险岛Boss监控已启动")
    print(f"   模板图片: {template_path}")
    print(f"   模板尺寸: {template.shape[1]}x{template.shape[0]}")
    print(f"   检测间隔: {CHECK_INTERVAL}秒")
    print(f"   匹配阈值: {MATCH_THRESHOLD}")
    print(f"   监控范围: {'主屏幕' if MONITOR_ONLY_MAIN else '全部屏幕'}")
    print("   按 Ctrl+C 停止")
    print("=" * 50)

    detected_count = 0
    alert_cooldown = False

    try:
        while True:
            now = time.strftime("%H:%M:%S")
            print(f"\n[{now}] 检测中...")

            screen = capture_main_screen()
            found, confidence, marked = detect_boss(screen, template)

            print(f"  最佳匹配度: {confidence:.3f} (阈值: {MATCH_THRESHOLD})")

            if found and not alert_cooldown:
                detected_count += 1
                send_alert("🦉 BOSS出现了！快去打！", detected_count)
                # 保存检测截图
                ts = int(time.time())
                cv2.imwrite(f"boss_detected_{ts}.png", marked)
                print(f"  🚨 已提醒！截图已保存: boss_detected_{ts}.png")
                # 60秒内不重复弹窗，避免疯狂弹
                alert_cooldown = True
                print("  冷却60秒，避免重复弹窗...")
            elif found and alert_cooldown:
                print("  🦉 Boss仍在，冷却中不重复提醒")
            else:
                alert_cooldown = False

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print(f"\n监控已停止。共检测到boss {detected_count} 次。")

if __name__ == "__main__":
    main()
