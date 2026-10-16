/* Temporary image only. The runner backs up/restores this entire SRAM range. */
ENTRY(foc_bench_entry)
MEMORY { RAM (rwx) : ORIGIN = 0x20016000, LENGTH = 32K }
SECTIONS {
  .vectors : { KEEP(*(.vectors)) } > RAM
  .text : { *(.text*) *(.rodata*) } > RAM
  .data : { *(.data*) } > RAM
  .bss (NOLOAD) : {
    . = ALIGN(4); __bench_bss_start = .;
    *(.bss*) *(COMMON)
    . = ALIGN(4); __bench_bss_end = .;
  } > RAM
  __bench_stack_top = ORIGIN(RAM) + LENGTH(RAM);
  ASSERT(__bench_bss_end < __bench_stack_top - 4096, "Bench must retain 4KB stack")
  /DISCARD/ : { *(.comment*) *(.ARM.exidx*) *(.ARM.extab*) }
}
