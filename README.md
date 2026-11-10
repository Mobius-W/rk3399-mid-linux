# rk3399-mid-linux

RK3399 MID 板（Rockchip Sapphire + Excavator 参考设计的定制会议平板）的 Linux 移植构建仓。

用 GitHub Actions 云端编译，本机不需要交叉工具链。

## 硬件一句话

RK3399 / 4GB DDR3-1600 / 8GB eMMC（DG4008）/ eDP 1920×1080 / GT9xx 触摸 / ES8316 + 2×ES7243 + 3×SN3732A / HR8833 云台 / AP6255 WiFi+BT / 千兆 RGMII / 2S 8.4V 电池 / 双 ISP / 无 SD 卡槽 / UART2 调试口。

详见 `rk3399-mid-backup/armbian/硬件清单-详尽版.md`。

## 目录

```
uboot/
  rk3399-mid.dts           # U-Boot 最小设备树（eMMC + SD + USB OTG + uart2）
  rk3399-mid_defconfig     # 基于 generic-rk3399，走 EXTERNAL_TPL
.github/workflows/
  build-uboot.yml          # 云端编译 U-Boot
```

## 关键设计

1. **DDR 初始化不用手写参数**：`CONFIG_ROCKCHIP_EXTERNAL_TPL=y` + Rockchip 官方
   `rk3399_ddr_800MHz_v1.30.bin`（本板 DDR3-1600 = 800MHz，实测 dmc 频率 800000000 Hz）。
   这是本轮移植最关键的取舍——避开手写 `rockchip,sdram-params` 的风险。

2. **串口降速到 115200**：vendor 固件用 1500000，但移植阶段 115200 兼容所有 USB-TTL。
   产物烧录后若串口无输出，可用 workflow 的 `baudrate` 参数改回 1500000 重编。

3. **产物布局**（Rockchip 标准）：
   - `idbloader.img` → **LBA 64**（0x8000）
   - `u-boot.itb` → **LBA 16384**（0x8000 偏移 8MiB）
   - 或直接用合并版 `u-boot-rockchip.bin` 写到 LBA 64

## 烧录（先用 db/ul 在内存试跑，不写 flash）

```bash
# 1. 进 MaskROM（断电 → 按住 MASKROM/音量减 → 插 OTG → 上电）
rkdeveloptool ld                      # 应看到 Maskrom

# 2. 下载 DDR+SPL 到 SRAM，再把 U-Boot 传进内存执行（不写 eMMC）
rkdeveloptool db idbloader.img
rkdeveloptool ul u-boot.itb

# 串口 115200 8N1 应看到 U-Boot 启动日志
```

试跑通过后再写 flash：

```bash
rkdeveloptool wl 64    idbloader.img
rkdeveloptool wl 16384 u-boot.itb
rkdeveloptool rd
```

## 回退

刷之前先备份 LBA 64 起的 4MB（vendor loader 区）：

```bash
rkdeveloptool rl 64 8192 vendor-idb-backup.img
```

出问题写回：`rkdeveloptool wl 64 vendor-idb-backup.img`

整盘兜底：`rk3399-mid-backup/rescue/rk3399-mid-emmc-full-20261110.img`（`wl 0`，已验证可救砖）。

## 进度

- [x] 硬件清单 + 路线评估
- [ ] U-Boot 编译（本仓）
- [ ] `db/ul` 内存试跑
- [ ] 写 flash + 自动引导
- [ ] Armbian rootfs（board config + DTS patch）
- [ ] 云台 / 功放 / 摄像头驱动
