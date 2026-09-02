/* TXW8301 Simulator — CH32V203C8T6 linker script (64K Flash / 20K RAM) */

OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{
  FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 64K
  RAM  (xrw)  : ORIGIN = 0x20000000, LENGTH = 20K
}

/* Top of user stack (full-descending) */
_eusrstack = ORIGIN(RAM) + LENGTH(RAM);

/* Small-data global pointer (used by -msmall-data-limit if enabled) */
__global_pointer$ = ORIGIN(RAM) + 0x800;

SECTIONS
{
  /* Reset entry */
  .init :
  {
    KEEP(*(.init))
    KEEP(*(.text.entry))
  } > FLASH

  /* Interrupt vector table (aligned for mtvec | 3) */
  .vector :
  {
    . = ALIGN(64);
    KEEP(*(.vector))
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
