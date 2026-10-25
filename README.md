# astrbot_plugin_epd · 墨水屏推送

把群里的**一句话**或**一张图**，推到一块 768×552 的**四色墨水屏**上喵。

> 硬件 = ESP32-C3 SUPERMINI + 四色水墨屏，跑 [MoInk](https://github.com/atunverse/moink) 固件
> （A1 面板：黑 / 白 / 黄 / 红，2bpp，整帧 106000 字节）。

```
群消息 ──► AstrBot 插件 ──► 生帧(2bpp) ──► POST /api/frame ──► 屏幕刷出来
                                ▲
                     标准调色管线 epd_color.py
```

---

## 1. 它能做什么

| 命令 | 效果 |
|---|---|
| `/epd 想说的话` | 推一行大字上屏（自动折行、带页脚） |
| `/epd` + 一张图 | 走标准调色管线处理后上屏 |
| `/epd 存 想说的话` | 上屏的同时存进板子内部的图库槽位 |
| `/epd 帮助` | 用法说明 |

- 带 **15 秒冷却**（可配置），防手抖刷屏
- 同一时刻只处理一次推图（内部有锁），不会把帧写乱
- 推图失败会把设备返回原样贴回来，不吞错

## 2. 标准调色管线（这个仓库的重点之一）

四色墨水屏最难的是**把彩色照片压成四色还不能脏**。这里的定标思路是：

> **只提亮本来就是暖色的部分，冷色区域保持干净的黑白。**

具体流程（`tools/epd_color.py`）：

1. 自动色阶（把灰蒙蒙的原图拉出对比）
2. **暖色吸引**：色相落在 `30° ± 58°`（即 332°~88°）的像素，暖度越高提亮越多（上限 18）
3. **冷色抑制**：冷色区的饱和度压低（上限 60），让它老老实实变成黑白线条
4. 锐化 30
5. Floyd–Steinberg 误差扩散抖动到 85%，再量化到 4 色

结果：蓝色头发/蓝色领结 → 干净的黑白线条；腮红、发丝高光 → 淡淡的黄。整屏不脏、不糊。
参数全部可命令行覆盖（`--warm-center`、`--warm-span`、`--cool-suppress`、`--sharpen`、`--dither` ……）。

## 3. 安装

### 3.1 插件

```bash
cd /path/to/astrbot/data/plugins
git clone https://github.com/hosta-6/astrbot_plugin_epd.git
# 重启 AstrBot 或在 WebUI 插件页重载
```

依赖：`numpy`、`pillow`（生帧用）。AstrBot 本体依赖之外只需这两个。

### 3.2 推图后端

插件本身**不认识墨水屏**，它只负责「收消息 → 调脚本 → 拿结果」。
真正干活的是 `tools/` 里这三个文件，放到任意目录，比如 `/root/remote-control/epd/`：

```
/root/remote-control/epd/
├── push.sh          ← 入口
├── epd_color.py     ← 调色管线
└── epd_frame.py     ← 帧打包（协议实现）
```

`main.py` 默认就在这个目录找 `push.sh`，可用环境变量 `EPD_WORKDIR` 改。

然后给插件配一下 `push.sh` 的两个环境变量（写在 systemd 单元或 `.bashrc` 都行）：

```bash
# 情况 A：AstrBot 和板子在同一网段（板子连了路由器，或服务器接了它的热点）
export EPD_DEV=http://192.168.4.1

# 情况 B：服务器够不到板子，但有一台电脑正连着板子热点
# 借那台电脑中转一下（需要它开 SSH，Windows 自带 OpenSSH Server 就够）
export EPD_RELAY=user@10.0.0.5:2222
export EPD_SSH_KEY=/root/.ssh/id_ed25519_pc
```

> 情况 B 里脚本会 `scp` 帧到对方机器，再用那台机器的 `curl` 去 `POST`。
> 这也是在「板子只开热点、服务器在云上」的拓扑下唯一不折腾的办法喵。

### 3.3 手动验证

```bash
cd tools
python3 epd_frame.py --text "Hello 4-color" --out /tmp/f.bin
./push.sh --text "Hello 4-color"
./push.sh ./photo.jpg --title "NINE" --sub "10.25" --foot "meow"
```

## 4. 帧协议（想自己写客户端的话看这里）

`POST /api/frame`（`?save=1` 则同时存进图库槽位），`Content-Type: application/octet-stream`：

```
body = 16 字节头 + 105984 字节载荷（2bpp）

头：A5 5A | ver=1 | panel(0=A0, 1=A1) | W(be16) | H(be16)
    | payload_len(be32) | crc16-CCITT-FALSE(be16) | 00 00

2bpp：每字节 4 像素，MSB 优先，像素 x 占位 (6 - 2*(x % 4))
色码：00=黑 01=白 10=黄 11=红
几何：缓冲区是逻辑图旋转 180°，写帧时别忘翻
```

`epd_frame.py` 里 `build_frame()`/`pack()`/`crc16_ccitt_false()` 就是完整实现，
包括设备认的 CRC16（poly `0x1021`、init `0xFFFF`、无反射、无终异或，`"123456789" → 0x29B1`）。

## 5. 关于固件与许可

- 本仓库**只包含插件和推图脚本**，是纯 Python/shell 实现，通过 HTTP 与设备通信。
- 设备端固件是 [atunverse/moink](https://github.com/atunverse/moink)（作者保留版权，**非开源许可**）。
  这个仓库**不包含**它的任何源码或二进制，也不分发固件。
- 若你想复刻：固件走它自己的渠道拿，本仓库负责「往屏幕上丢东西」这一半。
- 本仓库代码以 MIT 释出（见 `LICENSE`）。

## 6. 踩过的坑

1. **固件请求的路径和服务器 nginx 必须逐字对齐**，`/api/epd/frame` ≠ `/epd/frame`；
   404 不会在设备日志里明显报错，只会安静地不刷屏。
2. **ESP32 只认 WPA2 及以上**：碰上 WPA1 的老 AP，`authmode threshold failure` + `reason=211`，
   改代码无解，只能把路由器加密换成 WPA2-PSK。
3. **NVS 里存着旧 SSID 时，改 `DEFAULTS` 完全无效**：先 `esptool erase_region 0x9000 0x4000`，
   判断真凭据要看日志里的 `STA connecting to 'XXX'`。
4. **四色屏的「脏」多半来自抖动强度**：85% 是甜点，100% 会满地麻点，70% 以下色块会脏。
5. **生帧必须整帧重算**（106000 字节），部分刷新在 A1 上会残留旧色，别偷懒。

---

用爱发电喵 🐾 有 bug 就开 issue，咱会去看的。
