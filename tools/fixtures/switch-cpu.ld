ENTRY(_entry)
SECTIONS {
  . = 0;
  .text : { *(.text) }
  . = 0x1000;
  .rodata : { *(.rodata) }
  . = 0x2000;
  .data : { *(.data) }
  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
