;/* TXW8301 Simulator — CH32V203 (QingKe V2B) startup
; *
; * Replicates WCH startup_ch32v20x_D6.S conventions:
; *   - hardware stack / interrupt nesting  (csrw 0x804, 0x3)
; *   - pipelining / instruction prediction (csrw 0xbc0, 0x1f)
; *   - mtvec = vector_base | 3 (vectored + direct base)
; *   - mstatus = 0x88 (MIE | MPIE) then jump to main via mepc/mret
; *
; * Interrupt handlers use __attribute__((interrupt("WCH-Interrupt-fast")))
; * in C (MounRiver toolchain).
; */

    .section    .init,"ax",@progbits
    .global     _start
    .align      2
_start:
    j           handle_reset

    /* ------------------------------------------------------------------ */
    /* Vector table: exception slots 0..15, then external IRQs (IRQn N at
       index 16+N, i.e. WWDG=16 ... DMA1_Channel8=63)                     */
    /* ------------------------------------------------------------------ */
    .section    .vector,"ax",@progbits
    .align      6
    .global     _vector_base
_vector_base:
    .option norvc;
    .word   _start
    .word   0
    .word   NMI_Handler                 /* NMI                        */
    .word   HardFault_Handler           /* Hard Fault                 */
    .word   0
    .word   Ecall_M_Mode_Handler        /* Ecall M Mode               */
    .word   0
    .word   0
    .word   Ecall_U_Mode_Handler        /* Ecall U Mode               */
    .word   Break_Point_Handler         /* Break Point                */
    .word   0
    .word   0
    .word   SysTick_Handler             /* SysTick                    */
    .word   0
    .word   SW_Handler                  /* SW                         */
    .word   0
    /* External Interrupts */
    .word   WWDG_IRQHandler             /* 0  Window Watchdog         */
    .word   PVD_IRQHandler              /* 1  PVD                     */
    .word   TAMPER_IRQHandler           /* 2  TAMPER                  */
    .word   RTC_IRQHandler              /* 3  RTC                     */
    .word   FLASH_IRQHandler            /* 4  FLASH                   */
    .word   RCC_IRQHandler              /* 5  RCC                     */
    .word   EXTI0_IRQHandler            /* 6  EXTI0                   */
    .word   EXTI1_IRQHandler            /* 7  EXTI1                   */
    .word   EXTI2_IRQHandler            /* 8  EXTI2                   */
    .word   EXTI3_IRQHandler            /* 9  EXTI3                   */
    .word   EXTI4_IRQHandler            /* 10 EXTI4                   */
    .word   DMA1_Channel1_IRQHandler    /* 11 DMA1 CH1                */
    .word   DMA1_Channel2_IRQHandler    /* 12 DMA1 CH2                */
    .word   DMA1_Channel3_IRQHandler    /* 13 DMA1 CH3                */
    .word   DMA1_Channel4_IRQHandler    /* 14 DMA1 CH4                */
    .word   DMA1_Channel5_IRQHandler    /* 15 DMA1 CH5                */
    .word   DMA1_Channel6_IRQHandler    /* 16 DMA1 CH6                */
    .word   DMA1_Channel7_IRQHandler    /* 17 DMA1 CH7                */
    .word   ADC1_2_IRQHandler           /* 18 ADC1_2                  */
    .word   USB_HP_CAN1_TX_IRQHandler   /* 19 USB HP CAN1 TX          */
    .word   USB_LP_CAN1_RX0_IRQHandler  /* 20 USB LP CAN1 RX0         */
    .word   CAN1_RX1_IRQHandler         /* 21 CAN1 RX1                */
    .word   CAN1_SCE_IRQHandler         /* 22 CAN1 SCE                */
    .word   EXTI9_5_IRQHandler          /* 23 EXTI9_5                 */
    .word   TIM1_BRK_IRQHandler         /* 24 TIM1 BRK                */
    .word   TIM1_UP_IRQHandler          /* 25 TIM1 UP                 */
    .word   TIM1_TRG_COM_IRQHandler     /* 26 TIM1 TRG COM            */
    .word   TIM1_CC_IRQHandler          /* 27 TIM1 CC                 */
    .word   TIM2_IRQHandler             /* 28 TIM2                    */
    .word   TIM3_IRQHandler             /* 29 TIM3                    */
    .word   TIM4_IRQHandler             /* 30 TIM4                    */
    .word   I2C1_EV_IRQHandler          /* 31 I2C1 EV                 */
    .word   I2C1_ER_IRQHandler          /* 32 I2C1 ER                 */
    .word   I2C2_EV_IRQHandler          /* 33 I2C2 EV                 */
    .word   I2C2_ER_IRQHandler          /* 34 I2C2 ER                 */
    .word   SPI1_IRQHandler             /* 35 SPI1                    */
    .word   SPI2_IRQHandler             /* 36 SPI2                    */
    .word   USART1_IRQHandler           /* 37 USART1                  */
    .word   USART2_IRQHandler           /* 38 USART2                  */
    .word   USART3_IRQHandler           /* 39 USART3                  */
    .word   EXTI15_10_IRQHandler        /* 40 EXTI15_10               */
    .word   RTCAlarm_IRQHandler         /* 41 RTC Alarm               */
    .word   USBWakeUp_IRQHandler        /* 42 USB WakeUp              */
    .word   USBFS_IRQHandler            /* 43 USBFS                   */
    .word   USBFSWakeUp_IRQHandler      /* 44 USBFS WakeUp            */
    .word   UART4_IRQHandler            /* 45 UART4                   */
    .word   DMA1_Channel8_IRQHandler    /* 46 DMA1 CH8                */
    .option rvc;

    /* ---------------------------------------------------------------- */
    /* Weak default handlers: all jump to Default_Handler               */
    /* ---------------------------------------------------------------- */
    .section    .text.vector_handler,"ax",@progbits
    .weak   NMI_Handler
    .weak   HardFault_Handler
    .weak   Ecall_M_Mode_Handler
    .weak   Ecall_U_Mode_Handler
    .weak   Break_Point_Handler
    .weak   SysTick_Handler
    .weak   SW_Handler
    .weak   WWDG_IRQHandler
    .weak   PVD_IRQHandler
    .weak   TAMPER_IRQHandler
    .weak   RTC_IRQHandler
    .weak   FLASH_IRQHandler
    .weak   RCC_IRQHandler
    .weak   EXTI0_IRQHandler
    .weak   EXTI1_IRQHandler
    .weak   EXTI2_IRQHandler
    .weak   EXTI3_IRQHandler
    .weak   EXTI4_IRQHandler
    .weak   DMA1_Channel1_IRQHandler
    .weak   DMA1_Channel2_IRQHandler
    .weak   DMA1_Channel3_IRQHandler
    .weak   DMA1_Channel4_IRQHandler
    .weak   DMA1_Channel5_IRQHandler
    .weak   DMA1_Channel6_IRQHandler
    .weak   DMA1_Channel7_IRQHandler
    .weak   ADC1_2_IRQHandler
    .weak   USB_HP_CAN1_TX_IRQHandler
    .weak   USB_LP_CAN1_RX0_IRQHandler
    .weak   CAN1_RX1_IRQHandler
    .weak   CAN1_SCE_IRQHandler
    .weak   EXTI9_5_IRQHandler
    .weak   TIM1_BRK_IRQHandler
    .weak   TIM1_UP_IRQHandler
    .weak   TIM1_TRG_COM_IRQHandler
    .weak   TIM1_CC_IRQHandler
    .weak   TIM2_IRQHandler
    .weak   TIM3_IRQHandler
    .weak   TIM4_IRQHandler
    .weak   I2C1_EV_IRQHandler
    .weak   I2C1_ER_IRQHandler
    .weak   I2C2_EV_IRQHandler
    .weak   I2C2_ER_IRQHandler
    .weak   SPI1_IRQHandler
    .weak   SPI2_IRQHandler
    .weak   USART1_IRQHandler
    .weak   USART2_IRQHandler
    .weak   USART3_IRQHandler
    .weak   EXTI15_10_IRQHandler
    .weak   RTCAlarm_IRQHandler
    .weak   USBWakeUp_IRQHandler
    .weak   USBFS_IRQHandler
    .weak   USBFSWakeUp_IRQHandler
    .weak   UART4_IRQHandler
    .weak   DMA1_Channel8_IRQHandler

NMI_Handler:
HardFault_Handler:
Ecall_M_Mode_Handler:
Ecall_U_Mode_Handler:
Break_Point_Handler:
SysTick_Handler:
SW_Handler:
WWDG_IRQHandler:
PVD_IRQHandler:
TAMPER_IRQHandler:
RTC_IRQHandler:
FLASH_IRQHandler:
RCC_IRQHandler:
EXTI0_IRQHandler:
EXTI1_IRQHandler:
EXTI2_IRQHandler:
EXTI3_IRQHandler:
EXTI4_IRQHandler:
DMA1_Channel1_IRQHandler:
DMA1_Channel2_IRQHandler:
DMA1_Channel3_IRQHandler:
DMA1_Channel4_IRQHandler:
DMA1_Channel5_IRQHandler:
DMA1_Channel6_IRQHandler:
DMA1_Channel7_IRQHandler:
ADC1_2_IRQHandler:
USB_HP_CAN1_TX_IRQHandler:
USB_LP_CAN1_RX0_IRQHandler:
CAN1_RX1_IRQHandler:
CAN1_SCE_IRQHandler:
EXTI9_5_IRQHandler:
TIM1_BRK_IRQHandler:
TIM1_UP_IRQHandler:
TIM1_TRG_COM_IRQHandler:
TIM1_CC_IRQHandler:
TIM2_IRQHandler:
TIM3_IRQHandler:
TIM4_IRQHandler:
I2C1_EV_IRQHandler:
I2C1_ER_IRQHandler:
I2C2_EV_IRQHandler:
I2C2_ER_IRQHandler:
SPI1_IRQHandler:
SPI2_IRQHandler:
USART1_IRQHandler:
USART2_IRQHandler:
USART3_IRQHandler:
EXTI15_10_IRQHandler:
RTCAlarm_IRQHandler:
USBWakeUp_IRQHandler:
USBFS_IRQHandler:
USBFSWakeUp_IRQHandler:
UART4_IRQHandler:
DMA1_Channel8_IRQHandler:
1:
    j       1b

    /* ---------------------------------------------------------------- */
    /* Reset handler                                                     */
    /* ---------------------------------------------------------------- */
    .section    .text.handle_reset,"ax",@progbits
    .weak       handle_reset
    .align      2
handle_reset:
    .option push
    .option norelax
    la     gp, __global_pointer$
    .option pop

    la     sp, _eusrstack

    /* copy data from flash to RAM */
    la     a0, _data_lma
    la     a1, _data_vma
    la     a2, _edata
    bgeu   a1, a2, 2f
1:
    lw     t0, (a0)
    sw     t0, (a1)
    addi   a0, a0, 4
    addi   a1, a1, 4
    bltu   a1, a2, 1b
2:
    /* clear bss */
    la     a0, _sbss
    la     a1, _ebss
    bgeu   a0, a1, 2f
1:
    sw     zero, (a0)
    addi   a0, a0, 4
    bltu   a0, a1, 1b
2:
    /* configure pipelining and instruction prediction */
    li     t0, 0x1f
    csrw   0xbc0, t0
    /* enable interrupt nesting and hardware stack */
    li     t0, 0x3
    csrw   0x804, t0
    /* enable global interrupt and privileged mode */
    li     t0, 0x88
    csrw   mstatus, t0
    /* configure vector table recognition mode and entry address mode */
    la     t0, _vector_base
    ori    t0, t0, 3
    csrw   mtvec, t0

    jal    SystemInit
    la     t0, main
    csrw   mepc, t0
    mret
