# 🦉 冒险岛 Boss 监控

屏幕模板匹配检测Boss出现并弹窗提醒。

## 使用方法

### 1. 克隆仓库
```bash
git clone https://github.com/yeping02/maple-boss-monitor.git
cd maple-boss-monitor
```

### 2. 安装依赖
```bash
pip install opencv-python numpy Pillow
```

### 3. 准备Boss截图
把Boss的截图保存为 `boss_template.png`，放在脚本同目录。
**建议**：只截Boss本体，背景越少匹配越准。

### 4. 运行
```bash
python maple_boss_monitor.py
```

### 5. 停止
`Ctrl+C`

## 配置说明

在脚本顶部修改：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `BOSS_IMAGE_PATH` | `boss_template.png` | Boss模板图片路径 |
| `CHECK_INTERVAL` | `3` | 检测间隔（秒） |
| `MATCH_THRESHOLD` | `0.7` | 匹配阈值，越高越严格 |
| `MONITOR_ONLY_MAIN` | `True` | 只监控主屏幕（双屏适用） |

## 注意事项

- 游戏建议使用**无边框窗口模式**，独占全屏可能截到黑屏
- 误报时调高阈值到0.8，漏检时调低到0.6
- 检测到Boss会弹置顶弹窗，60秒内不重复弹
