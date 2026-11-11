# RK3399-MID (Android 7 母板 / 云台一体机)
#
# 引导链设计要点（全部经官方 armbian/build 源码 + u-boot v2026.10 源码逐条核对）：
#
#  1. 本板 eMMC boot0 硬件分区里已有原厂 miniloader（DDR3-1600 / dmc 800MHz），
#     它负责 DDR 初始化，并从 user 区固定偏移读取引导件：
#         LBA8192  -> "LOADER" 容器（vendor 格式 U-Boot）
#         LBA16384 -> "BL3X"   容器（trust / ATF）
#     原厂 parameter（mtdparts）里写死了这两个坐标：
#         0x00002000@0x00002000(uboot)  0x00002000@0x00004000(trust)
#
#  2. 因此本板走 rockchip64 家族的 only-blobs 场景：
#       BOOT_SCENARIO=only-blobs
#         -> u-boot-dtb.bin  --loaderimage --pack-->  uboot.img（LOADER 格式）
#         -> trust_merger                          ->  trust.bin（BL3X 格式）
#     官方默认写盘坐标是 64 / 16384 / 24576，与本板不符，
#     故在下面用 post_family_config hook 覆盖 write_uboot_platform()。
#
#  3. idbloader.bin 本板不落盘：boot0 里已经有原厂 miniloader，
#     user 区 LBA64 不被任何东西读取（BootROM 才会读 LBA64，而本板走 boot0 路径）。
#     DDR 参数也由原厂 miniloader 决定，官方 DDR blob 对本板无效但仍需存在（仅构建期）。
#
#  4. BOOT_SOC 必须显式指定为 rk3399：
#     官方推导规则 expr "${BOOTCONFIG}" : '.*\(rk[[:digit:]]\+.*\)_.*'
#     对任何含 rk3399 的 defconfig 都推不出 "rk3399"（会推成 rk3399-evb 之类），
#     case "$BOOT_SOC" in rk3399) 分支不命中 => BOOT_SCENARIO / DDR_BLOB /
#     MINILOADER_BLOB / BL31_BLOB 全部落空。
#
#  5. BOOTCONFIG 使用上游 mainline U-Boot 自带的 evb-rk3399_defconfig：
#     本板走 only-blobs，U-Boot 只作为 payload 被打进 vendor LOADER 容器，
#     其内嵌 DTB 由 armbianEnv.txt 的 fdtfile 覆盖，故沿用 evb 即可。
#     已核验该 defconfig 在 v2022.04 / v2022.07 / v2024.10 / v2025.10 / v2026.10
#     全部存在。
#
#  6. U-Boot 分支选 v2026.10（当前最新正式 tag，也是官方 radxa rk3399 板所用的 tag），
#     补丁目录用官方 patch/u-boot/v2026.10。该目录带 0000.patching_config.yaml，
#     支持把 defconfig / dts 直接拷进 u-boot 源码树。
#
#  6b. ★ trust.ini 必须自己带：rockchip64 家族的默认补丁目录是
#        BOOTPATCHDIR="${BOOTPATCHDIR:-"u-boot-rockchip64"}"   (rockchip64_common.inc:22)
#      官方 add-trust-ini.patch（298 B，只是新增一个 15 行的 trust.ini）就放在
#      patch/u-boot/u-boot-rockchip64/ 里；一旦把 BOOTPATCHDIR 覆写成 v2026.10，
#      这个补丁就不在列表内了，于是 only-blobs 后处理
#        trust_merger --replace bl31.elf <BL31_BLOB> trust.ini
#     会以 "config(trust.ini) not found! merge failed!" 失败（2026-11-11 CI 实测）。
#      注意 u-boot-rockchip64/ 里另外 47 个补丁是给家族默认 v2022.07 用的，
#      不能整体带进来（BOOTBRANCH 默认是 tag:v2022.07，见 common.conf:189）。
#      => 只在 userpatches/u-boot/v2026.10/ 补一个同名补丁，内容与官方逐字节一致。
#
#  7. ★ U-Boot 的文件系统能力不是靠 defconfig 显式开启的，而是靠 Kconfig 依赖链：
#         CONFIG_ROCKCHIP_RK3399=y
#           -> imply BOOTSTD_FULL            (arch/arm/mach-rockchip/Kconfig:280)
#           -> imply BOOTSTD_DEFAULTS
#           -> select BOOT_DEFAULTS
#           -> select BOOT_DEFAULTS_CMDS if CMDLINE   (CMDLINE 默认 y)
#           -> select CMD_EXT4 / CMD_FAT / CMD_FS_GENERIC / CMD_PART
#              (分别 select FS_EXT4 / FS_FAT)
#     但 **CMD_BOOTI 有一个缺口**：v2026.10 的
#         config CMD_BOOTI
#             depends on ARM64 || RISCV || SANDBOX
#             depends on LMB          <-- LMB 的 default y 列表里没有 ARM64
#     而 LMB 只被 EFI_LOADER select，所以 ARM64 上 LMB 默认 n -> CMD_BOOTI 不被带出。
#     boot-rockchip64.cmd 结尾是 `booti ${kernel_addr_r} ... ${fdt_addr_r}`，
#     没有 booti 就起不了内核。
#     => 因此下面用 post_config_uboot_target hook 显式补齐
#        LMB / CMD_BOOTI / CMD_PART / CMD_FS_GENERIC / CMD_EXT4 / FS_EXT4 / CMD_FAT / FS_FAT。
#        （该 hook 在 `make ${BOOTCONFIG}` 之后、`make olddefconfig` 之前执行，
#          此时 .config 已存在，scripts/config 生效。）
#
#  8. ★ 引导方式与路径（已核对 armbian 源码 + 本地真实 armbian rockchip64 镜像）：
#     - rockchip64 family 不设 BOOTFS_TYPE => 只有一个 rootfs 分区，
#       /boot 在 rootfs 分区内部 => 镜像里是 <p1>/boot/boot.scr。
#     - u-boot v2026.10 默认走 BOOTSTD（bootcmd=bootflow scan），
#       其 BOOTMETH_SCRIPT 正是找 "boot/boot.scr"（boot/Kconfig 的 help 原文），
#       且会把 prefix 设为 "boot" => boot-rockchip64.cmd 里的
#       ${prefix}armbianEnv.txt / ${prefix}Image / ${prefix}dtb/${fdtfile} 全部对得上。
#     => 所以本板走经典 boot.scr 路线（不设 SRC_EXTLINUX），与官方 rockchip64 一致。
#
#  9. ★★ PARM 与 GPT 冲突（本板专属，尚未落盘验证）：
#     - 本板 user 区 LBA0 是 Rockchip parameter（"PARM" + u32 长度 0x382 + 文本），
#       文本 898 B，跨 LBA0 与 LBA1 前 386 B。
#     - 文本里的 CMDLINE 段带着 mtdparts，其中
#       mtdparts=rk29xxnand:0x00002000@0x00002000(uboot),0x00002000@0x00004000(trust)
#       正好压在 LBA0 的 435..510 字节区间。
#     - 而 armbian 默认 IMAGE_PARTITION_TABLE=gpt：sfdisk 会把 GPT 头写到 LBA1、
#       保护 MBR 写到 LBA0 => 与 PARM 正面冲突，且 miniloader 需要 PARM 里的 mtdparts
#       才能定位 uboot@0x2000 / trust@0x4000。
#     - 已验证可行的化解方案（下一步做，build 侧不动）：
#         用 armbian 的 USE_HOOK_FOR_PARTITION=yes + create_partition_table 钩子，
#         自己写 MBR：
#             LBA0[0:446]  = 压缩版 parameter（保留全部头字段 + 只留 uboot/trust 两条 mtdparts）
#             LBA0[446:512]= MBR 分区表（p1 @ LBA32768）+ 0x55AA
#         这样 miniloader 读得到 mtdparts，u-boot 也读得到分区表。
#         （主链路的 GPT 版镜像照常出，作为对照/备份。）
#

BOARD_NAME="RK3399-MID"
BOARD_VENDOR="rk3399-mid"
BOARDFAMILY="rockchip64"
BOARD_MAINTAINER="Mobius-W"
INTRODUCED="2026"

# ---- 内核 ---------------------------------------------------------------
KERNEL_TARGET="current"
KERNEL_TEST_TARGET="current"

# ---- U-Boot -------------------------------------------------------------
BOOTCONFIG="evb-rk3399_defconfig"
BOOTBRANCH_BOARD="tag:v2026.10"
BOOTPATCHDIR="v2026.10"

# 本板 SoC 判定（见文件头注释第 4 条）
BOOT_SOC="rk3399"

# ---- 内核设备树 ---------------------------------------------------------
# 本板专用 DTS（eDP 1920x1080 / GMAC RGMII / PWM0 背光 / AP6255 / ES8316 /
# GT9xx / CW2015 / 云台），由 armbian 的 dts-directories 机制直接拷进内核树，
# 源码在 userpatches/kernel/archive/rockchip64-6.18/dt/rk3399-mid.dts
BOOT_FDT_FILE="rockchip/rk3399-mid.dtb"

# ---- 引导场景 -----------------------------------------------------------
BOOT_SCENARIO="only-blobs"

# ---- 串口 / 内核命令行 --------------------------------------------------
# 本板调试串口为 UART2 @ 1500000 8N1（与 stock kernel cmdline 一致）。
SERIALCON="ttyS2"
SRC_CMDLINE="console=ttyS2,1500000n8 console=tty0"

# ---- 镜像布局 -----------------------------------------------------------
# 本板 eMMC 前 4MiB 保留原厂 parameter(PARM) 与 IDB，
# 镜像 p1/p2 从 LBA32768 起（OFFSET=16 MiB，与官方 rockchip64 一致）。
IMAGE_PARTITION_TABLE="gpt"

# ======================================================================
# hook：覆盖写盘坐标
# ======================================================================
#
# 官方 only-blobs 分支（config/sources/families/include/rockchip64_common.inc
# 的 write_uboot_platform()）写的是：
#     dd idbloader.bin seek=64      <- 本板不写（boot0 已有原厂 miniloader）
#     dd uboot.img     seek=16384   <- 本板应为 8192
#     dd trust.bin     seek=24576   <- 本板应为 16384
#
# 本板 boot0 miniloader 按原厂 mtdparts 固定读取：
#     LOADER @ LBA8192   BL3X @ LBA16384
#
# post_family_config hook 在 family 配置完成之后执行，此处定义的
# write_uboot_platform() 会覆盖 family 里同名函数（后定义者胜）。
# 官方同类写法见 config/boards/yy3568.csc（unset 后重新定义）。

function post_family_config__rk3399mid_write_uboot_platform() {
	display_alert "rk3399-mid" "Overriding write_uboot_platform() for this board's boot0 coordinate scheme" "info"
	display_alert "rk3399-mid" "uboot.img -> LBA8192 (LOADER), trust.bin -> LBA16384 (BL3X), idbloader.bin NOT written" "info"

	unset write_uboot_platform write_uboot_platform_mtd

	function write_uboot_platform() {
		# 这个函数在构建机与板端 (armbian-install) 都会跑，logging_prelude 要自己判断
		local logging_prelude=""
		[[ $(type -t run_host_command_logged) == function ]] && logging_prelude="run_host_command_logged"

		# 本板 boot0 miniloader 已存在，user 区 LBA64 的 idbloader 不被读取，跳过。
		${logging_prelude} dd if=$1/uboot.img of=$2 bs=512 seek=8192  conv=notrunc status=none
		${logging_prelude} dd if=$1/trust.bin of=$2 bs=512 seek=16384 conv=notrunc status=none
	}

	function write_uboot_platform_mtd() {
		echo "rk3399-mid: no SPI bootloader for this board"
		exit 1
	}
}

# ======================================================================
# hook：校验 only-blobs 所需的三件套 blob 都已定位
# ======================================================================

function post_family_config__rk3399mid_uboot_defaults() {
	display_alert "rk3399-mid" "BOOT_SOC=${BOOT_SOC} BOOT_SCENARIO=${BOOT_SCENARIO} BOOTCONFIG=${BOOTCONFIG}" "info"
	display_alert "rk3399-mid" "BOOTPATCHDIR=${BOOTPATCHDIR} BOOT_FDT_FILE=${BOOT_FDT_FILE}" "info"

	# 校验 only-blobs 所需的三件套 blob 都已由 family 定位
	if [[ "${BOOT_SCENARIO}" != "only-blobs" ]]; then
		exit_with_error "rk3399-mid requires BOOT_SCENARIO=only-blobs" "got '${BOOT_SCENARIO}'"
	fi
	for _blob_var in DDR_BLOB MINILOADER_BLOB BL31_BLOB; do
		if [[ -z "${!_blob_var}" ]]; then
			exit_with_error "rk3399-mid: ${_blob_var} is empty; BOOT_SOC='${BOOT_SOC}' did not match the rk3399 case branch"
		fi
	done
}

# ======================================================================
# hook：给 U-Boot 补齐引导 ext4 分区所需的能力
# ======================================================================
#
# boot-rockchip64.cmd 用
#     load ${devtype} ${devnum}:${distro_bootpart} ${load_addr} ${prefix}armbianEnv.txt
#     part uuid mmc ${devnum}:${distro_bootpart} partuuid
#     booti ${kernel_addr_r} ${ramdisk_addr_r} ${fdt_addr_r}
# 来引导内核，因此 U-Boot 必须有：
#     CONFIG_CMD_FS_GENERIC-> load / ls 通用文件命令
#     CONFIG_FS_EXT4      -> ext4 读取实现（CMD_EXT4 会 select 它）
#     CONFIG_CMD_PART      -> part 命令（GPT 由 CMD_GPT -> EFI_PARTITION -> PARTITIONS 带出）
#     CONFIG_CMD_BOOTI     -> booti（★ 缺口：ARM64 上 LMB 默认关，CMD_BOOTI 带不出来）
#
# ★ hook 时机：post_config_uboot_target 在 `make ${BOOTCONFIG}` 之后、
#   `make olddefconfig` 之前调用（lib/functions/compilation/uboot.sh:206 / 214），
#   此时 .config 已由 defconfig 生成，scripts/config 修改有效。
#   不能用 pre_config_uboot_target —— 它在 `make ${BOOTCONFIG}` 之前调用，
#   .config 还不存在，scripts/config 无效。

function post_config_uboot_target__rk3399mid_uboot_features() {
	display_alert "rk3399-mid" "Enabling partition/ext4/booti support in U-Boot for boot.scr loading" "info"

	# LMB 是 CMD_BOOTI 的硬依赖，ARM64 上默认关，必须显式打开
	run_host_command_logged scripts/config --enable CONFIG_LMB
	run_host_command_logged scripts/config --enable CONFIG_CMD_BOOTI

	# 分区表与文件系统
	run_host_command_logged scripts/config --enable CONFIG_CMD_PART
	run_host_command_logged scripts/config --enable CONFIG_CMD_FS_GENERIC
	run_host_command_logged scripts/config --enable CONFIG_CMD_EXT4
	run_host_command_logged scripts/config --enable CONFIG_FS_EXT4
	run_host_command_logged scripts/config --enable CONFIG_CMD_FAT
	run_host_command_logged scripts/config --enable CONFIG_FS_FAT

	# 介质与 GPT
	run_host_command_logged scripts/config --enable CONFIG_CMD_MMC
	run_host_command_logged scripts/config --enable CONFIG_CMD_GPT

	# ★ 不要改 DEFAULT_FDT_FILE！
	#   U-Boot 内嵌 DTB 是 evb-rk3399_defconfig 自带的 rockchip/rk3399-evb.dtb，
	#   u-boot 源码树里并不存在 rk3399-mid.dtb；把它指过去会让 U-Boot 自身
	#   FDT 加载失败（u-boot-dtb.bin 的 CAT 阶段就崩）。
	#   内核用的 DTB 由 armbianEnv.txt 的 fdtfile=rockchip/rk3399-mid.dtb 覆盖，
	#   与 U-Boot 内嵌 DTB 无关，两者互不影响。

	return 0
}
