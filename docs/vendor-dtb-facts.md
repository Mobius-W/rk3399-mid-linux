# 原厂 DTB 关键事实（从 stock/resource.img 反编译，用于校准 mainline DTS）

> 来源：`stock/resource.img` 偏移 0x800 起 77980 字节 = `rk-kernel.dtb`（vendor 4.4.83）
> 工具：`tools/fdt.py`（本机无 dtc，自写的纯 Python FDT 解析器）
> 复现：`dd if=stock/resource.img of=/tmp/v.dtb bs=1 skip=2048 count=77980` → `python3 tools/fdt.py dump /tmp/v.dtb`
> 时间：2026-11-10

## 1. eDP 面板（`/edp-panel`）— 唯一显示通道

| 项 | vendor 值 | 换算 |
|---|---|---|
| compatible | `simple-panel` | mainline `panel-simple` 认这个 fallback 名 |
| display-timings clock-frequency | 0x84157A0 | **138 500 000 Hz** |
| hactive / hfp / hbp / hsync | 0x780 / 0x78 / 0x20 / 0x08 | 1920 / 120 / 32 / 8 |
| vactive / vfp / vbp / vsync | 0x438 / 0x17 / 0x06 / 0x02 | 1080 / 23 / 6 / 2 |
| 极性（h/v/de/pclk） | 全 0x00 | 全 active-low |
| 实测刷新率 | — | 138.5e6 / (2080 × 1111) = **59.96 Hz** |
| backlight | phandle 0xd0 → `/backlight` | pwm-backlight |
| power-supply | phandle **0xd1 → PMIC `SWITCH_REG2`** | ⚠️ 不是 vcc3v3_s0 |
| enable-gpios / reset-gpios | **均无此属性** | ⚠️ 现 DTS 里的 `gpio3 RK_PA4` 属推测，未证实 |

## 2. eDP 控制器（`/edp@ff970000`）

- `compatible = "rockchip,rk3399-edp"`，`power-domains = <pd_edp>`
- `pinctrl-0` → `/pinctrl/edp/edp-hpd` = `rockchip,pins = <4 0x17 2 ...>` → **GPIO4_C7, func2**
- 与 mainline `&edp_hpd`（`<4 RK_PC7 2>`）**完全一致** ✅
- 无 `hpd-gpios`（走 GRF），mainline 需 `hpd-gpios = <&gpio4 RK_PC7 GPIO_ACTIVE_HIGH>` 或 `force-hpd`

## 3. 背光（`/backlight`，phandle 0xd0）

| 项 | 值 |
|---|---|
| compatible | `pwm-backlight` |
| pwms | `<&pwm@ff420000 0 0x61A8 0>` → **PWM0 ch0, 周期 25000 ns, 正极性** |
| enable-gpios | `<gpio1 13 ACTIVE_HIGH>` → **GPIO1_B5** ✅ 与现 DTS 一致 |
| brightness-levels | 257 级（0, 0x14, 0x14, 0x15…0xFF，低段有平台） |
| default-brightness-level | 0xC8 = 200 |

## 4. vdd_log（CPU 大核供电）= PWM 调压

- `/vdd-log`：`pwm-regulator`，`pwms = <pwm@ff420020 0 25000 1>` → **PWM2 ch0，反极性**
- `rockchip,pwm_voltage = 0xE57E0` = 940 000 µV；范围 750 000–1 350 000 µV
- mainline `rk3399-sapphire.dtsi` 的 `vdd_log` 已是 `<&pwm2 0 25000 1>` ✅ 不用改

## 5. 已解析的 phandle 对照

| phandle | 节点 | 说明 |
|---|---|---|
| 0xc2 | `/pinctrl/gpio0@ff720000` | bank0 |
| 0x34 | `/pinctrl/gpio1@ff730000` | bank1 |
| 0x3d | `/pinctrl/gpio2@ff780000` | bank2 |
| （见 §2） | `/pinctrl/gpio3@ff788000` | bank3 |
| 0x3b | `/pinctrl/gpio4@ff790000` | bank4 |
| 0xc1 | `/saradc@ff100000` | ADC |
| 0xd1 | `/i2c@ff3c0000/pmic@1b/regulators/SWITCH_REG2` | 面板 3V3 |
| 0xd6 | `/pwm@ff420020` | PWM2 → vdd_log |
| 0xd7 | `/pwm@ff420000` | PWM0 → 背光 |
| 0xd8 | `/i2s@ff880000` | I2S0 → es8316 |
| 0xd9 | `/i2c@ff110000/es8316@11` | 音频 codec |

> 注意：**i2c 总线号与地址**——es8316 在 `ff110000`（mainline 的 `&i2c1`），触摸 goodix 在 `ff120000`（`&i2c2`）0x5d，PMIC 在 `ff3c0000`（`&i2c4` 之误？实测 vendor 用 `i2c@ff3c0000`）。以 vendor 节点名为准，勿照抄 mainline 的 i2c 编号。

## 6. 本板专有外设（mainline 无驱动，仅记录 GPIO）

| 节点 | compatible | 关键引脚 |
|---|---|---|
| `/motor` | `heroic,hr8833`（云台） | ain1=`gpio2 2`、ain2=`gpio2 3`、sleep=`gpio2 4`(高有效)、ocp-det=`gpio2 5`(低有效) |
| `/ntc-monitor` | `ntc_monitor` | io-channels=`saradc ch0`、charge-en=`gpio1 4`(高有效) |
| `/modem-power` | `modem_power`（4G） | power=`gpio4 0x1d`、reset=`gpio2 0x1b`(低有效) |
| `/rk_headset` | `rockchip_headset` | headset=`gpio4 0x1c`(低)、hp-con=`gpio4 0x1e` |
| `/wireless-wlan` | `wlan-platdata` | `wifi_chip_type = "ap6255"`、wake-irq=`gpio0 3`、`sdio_vref=0x708(1800mV)` |
| `/wireless-bluetooth` | `bluetooth-platdata` | reset=`gpio0 9`、wake=`gpio2 0x1a`、wake-host-irq=`gpio0 4` |
| `/sdio-pwrseq` | `mmc-pwrseq-simple` | reset=`gpio0 0x0a`(低有效)，ext_clock=`<&rk808 1>` ✅ 与现 DTS 一致 |
| `/sn3732a-*` | `pinctrl` 组 | 3 路 LED 驱动，仅 pinctrl |
| `/ak8963` `/cm3218` `/kxtj2` | pinctrl 组 | 磁力计/光感/加速度，i2c 上无常驻节点 |

## 7. 待实测校准（写进 DTS 前必须验证）

1. eDP 面板 `power-supply` 到底是 PMIC `SWITCH_REG2` 还是固定 3V3 —— 影响能否点亮
2. 面板是否真有 enable/reset GPIO（vendor DT 里没有）
3. `adc-keys` 电压阈值（vendor 用 `rockchip,adc_value` 原始值，非 µV）
4. GMAC `tx_delay/rx_delay`：vendor 45/34，sapphire 默认 40/17
