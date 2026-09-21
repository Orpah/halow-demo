/* TXW8301 Simulator — CH32V203C8T6 linker script (64K Flash / 20K RAM) */

OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{
  /* ★ 链接基址必须 0x00000000（2026-09-21 上机实测，别再改回 0x08000000）：
   *   链接到 0x08000000 的镜像烧进去**一条指令都不执行**（灯不亮、串口全静默）。
   *   证据：同一份源码只差基址的对照（0x0 → 正常跑 / 0x08000000 → 一动不动），
   *   且 WCH 自己的 EVT/EXAM/SRC/Ld/Link.ld 三个芯片变体**全部**是 ORIGIN = 0x00000000。
   *   ⇒ 烧录地址也要写 0x00000000（见 firmware/README.md 与 docs/usage.md 的烧录段）。*/
  FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 64K
  RAM  (xrw)  : ORIGIN = 0x20000000, LENGTH = 20K
}

/* Top of user stack (full-descending) */
_eusrstack = ORIGIN(RAM) + LENGTH(RAM);

/* Small-data global pointer (used by -msmall-data-limit if enabled) */
__global_pointer$ = ORIGIN(RAM) + 0x800;

SECTIONS
{
  /* Reset entry
   * ★ 这里**只放** `.init`（+ 4 字节对齐）：中断向量表要紧接其后（= 0x8）。
   *   注意 WCH 官方 `EVT/EXAM/SRC/Ld/Link.ld` 的 ALIGN(64) 是放在表的**后面**
   *   （给下一节对齐用），不是放在表**前面** —— 放前面会把表推到 0x40。*/
  .init :
  {
    KEEP(*(.init))
    . = ALIGN(4);
  } > FLASH

  /* Interrupt vector table：紧接 `.init`；mtvec = 本地址 | 3（与 WCH 一致）。*/
  .vector :
  {
    KEEP(*(.vector))
    . = ALIGN(64);
  } > FLASH

  .text :
  {
    *(.text)
    *(.text.*)
    *(.gnu.linkonce.t.*)
  } > FLASH

  .rodata :
  {
    *(.rodata)
    *(.rodata.*)
    *(.srodata*)
    *(.gnu.linkonce.r.*)
  } > FLASH

  /* Initialized data: load in flash, run in RAM */
  .data :
  {
    . = ALIGN(4);
    _data_vma = .;
    *(.data)
    *(.data.*)
    *(.sdata*)
    *(.gnu.linkonce.d.*)
    _edata = .;
  } > RAM AT > FLASH
  _data_lma = LOADADDR(.data);

  /* Zero-init data */
  .bss :
  {
    . = ALIGN(4);
    _sbss = .;
    *(.bss)
    *(.bss.*)
    *(.sbss*)
    *(COMMON)
    _ebss = .;
  } > RAM

  . = ALIGN(4);
  _end = .;

  /* Heap (not used by default; provided for libc compatibility) */
  .heap (NOLOAD) :
  {
    . = ALIGN(4);
    _heap_start = .;
    . = ORIGIN(RAM) + LENGTH(RAM) - 256;
    _heap_end = .;
  } > RAM
}
