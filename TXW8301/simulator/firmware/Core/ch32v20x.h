/* ch32v20x.h — CH32V203 register definitions (minimal, self-contained)
 *
 * For the TXW8301 Simulator. Layout follows STM32F103-style peripherals
 * as used by WCH CH32V203, plus WCH-specific PFIC / SysTick.
 */
#ifndef __CH32V20X_H__
#define __CH32V20X_H__

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------ */
/* Core convenience                                                    */
/* ------------------------------------------------------------------ */
#define __I  volatile const
#define __O  volatile
#define __IO volatile

#ifndef NULL
#define NULL ((void *)0)
#endif

#define BIT(n) (1u << (n))

/* IRQ numbers (IRQn N maps to vector table index 16+N) */
typedef enum {
    WWDG_IRQn             = 0,
    PVD_IRQn              = 1,
    TAMPER_IRQn           = 2,
    RTC_IRQn              = 3,
    FLASH_IRQn            = 4,
    RCC_IRQn              = 5,
    EXTI0_IRQn            = 6,
    EXTI1_IRQn            = 7,
    EXTI2_IRQn            = 8,
    EXTI3_IRQn            = 9,
    EXTI4_IRQn            = 10,
    DMA1_Channel1_IRQn    = 11,
    DMA1_Channel2_IRQn    = 12,
    DMA1_Channel3_IRQn    = 13,
    DMA1_Channel4_IRQn    = 14,
    DMA1_Channel5_IRQn    = 15,
    DMA1_Channel6_IRQn    = 16,
    DMA1_Channel7_IRQn    = 17,
    ADC1_2_IRQn           = 18,
    USB_HP_CAN1_TX_IRQn   = 19,
    USB_LP_CAN1_RX0_IRQn  = 20,
    CAN1_RX1_IRQn         = 21,
    CAN1_SCE_IRQn         = 22,
    EXTI9_5_IRQn          = 23,
    TIM1_BRK_IRQn         = 24,
    TIM1_UP_IRQn          = 25,
    TIM1_TRG_COM_IRQn     = 26,
    TIM1_CC_IRQn          = 27,
    TIM2_IRQn             = 28,
    TIM3_IRQn             = 29,
    TIM4_IRQn             = 30,
    I2C1_EV_IRQn          = 31,
    I2C1_ER_IRQn          = 32,
    I2C2_EV_IRQn          = 33,
    I2C2_ER_IRQn          = 34,
    SPI1_IRQn             = 35,
    SPI2_IRQn             = 36,
    USART1_IRQn           = 37,
    USART2_IRQn           = 38,
    USART3_IRQn           = 39,
    EXTI15_10_IRQn        = 40,
    RTCAlarm_IRQn         = 41,
    USBWakeUp_IRQn        = 42,
    USBFS_IRQn            = 43,
    USBFSWakeUp_IRQn      = 44,
    UART4_IRQn            = 45,
    DMA1_Channel8_IRQn    = 46,
} IRQn_Type;

/* ------------------------------------------------------------------ */
/* PFIC (Programmable Fast Interrupt Controller) = NVIC at 0xE000E000  */
/* ------------------------------------------------------------------ */
typedef struct {
    __I  uint32_t ISR[8];          /* 0x000 Interrupt status        */
    __I  uint32_t IPR[8];          /* 0x020 Interrupt pending       */
    __IO uint32_t ITHRESDR;        /* 0x040                         */
    __IO uint32_t RESERVED;        /* 0x044                         */
    __IO uint32_t CFGR;            /* 0x048 (reset: key3|(1<<7))    */
    __I  uint32_t GISR;            /* 0x04C                         */
    __IO uint8_t  VTFIDR[4];       /* 0x050                         */
    uint8_t       RESERVED0[12];   /* 0x054                         */
    __IO uint32_t VTFADDR[4];      /* 0x060                         */
    uint8_t       RESERVED1[0x90]; /* 0x070                         */
    __O  uint32_t IENR[8];         /* 0x100 Interrupt enable        */
    uint8_t       RESERVED2[0x60]; /* 0x120                         */
    __O  uint32_t IRER[8];         /* 0x180 Interrupt clear         */
} PFIC_Type;

#define PFIC  ((PFIC_Type *)0xE000E000)
#define NVIC  PFIC
#define NVIC_KEY3 ((uint32_t)0xBEEF0000)

/* SysTick at 0xE000F000 (WCH) */
typedef struct {
    __IO uint32_t CTLR;            /* 0x00 */
    __IO uint32_t SR;              /* 0x04 (bit0 = CNTFLAG) */
    __IO uint64_t CNT;             /* 0x08 */
    __IO uint64_t CMP;             /* 0x10 */
} SysTick_Type;

#define SysTick ((SysTick_Type *)0xE000F000)

/* ------------------------------------------------------------------ */
/* GPIO (STM32F1-style)                                                */
/* ------------------------------------------------------------------ */
typedef struct {
    __IO uint32_t CFGLR;  /* 0x00 CRL */
    __IO uint32_t CFGHR;  /* 0x04 CRH */
    __I  uint32_t INDR;   /* 0x08 IDR */
    __IO uint32_t OUTDR;  /* 0x0C ODR */
    __IO uint32_t BSHR;   /* 0x10 BSRR */
    __IO uint32_t BCHR;   /* 0x14 BRR */
    __IO uint32_t LCKR;   /* 0x18 */
} GPIO_TypeDef;

#define GPIOA ((GPIO_TypeDef *)0x40010800)
#define GPIOB ((GPIO_TypeDef *)0x40010C00)
#define GPIOC ((GPIO_TypeDef *)0x40011000)
#define GPIOD ((GPIO_TypeDef *)0x40011400)

/* GPIO pin modes (CRL/CRH 4-bit fields) */
#define GPIO_MODE_IN_ANALOG      0x0
#define GPIO_MODE_IN_FLOATING    0x4
#define GPIO_MODE_IN_PUPD        0x8
#define GPIO_MODE_OUT_PP_10MHZ   0x1
#define GPIO_MODE_OUT_PP_2MHZ    0x2
#define GPIO_MODE_OUT_PP_50MHZ   0x3
#define GPIO_MODE_OUT_OD_10MHZ   0x5
#define GPIO_MODE_OUT_OD_2MHZ    0x6
#define GPIO_MODE_OUT_OD_50MHZ   0x7
#define GPIO_MODE_AF_PP_10MHZ    0x9
#define GPIO_MODE_AF_PP_2MHZ     0xA
#define GPIO_MODE_AF_PP_50MHZ    0xB
#define GPIO_MODE_AF_OD_50MHZ    0xF

/* ------------------------------------------------------------------ */
/* AFIO / EXTI                                                         */
/* ------------------------------------------------------------------ */
typedef struct {
    __IO uint32_t EVCR;     /* 0x00 */
    __IO uint32_t MAPR;     /* 0x04 */
    __IO uint32_t EXTICR[4];/* 0x08 */
    __IO uint32_t MAPR2;    /* 0x18 */
} AFIO_TypeDef;
#define AFIO ((AFIO_TypeDef *)0x40010000)

typedef struct {
    __IO uint32_t INTENR;   /* 0x00 IMR */
    __IO uint32_t EVENR;    /* 0x04 EMR */
    __IO uint32_t RTENR;    /* 0x08 RTSR */
    __IO uint32_t FTENR;    /* 0x0C FTSR */
    __IO uint32_t SWIEVR;   /* 0x10 SWIER */
    __IO uint32_t PR;       /* 0x14 (W1C) */
} EXTI_TypeDef;
#define EXTI ((EXTI_TypeDef *)0x40010400)

/* ------------------------------------------------------------------ */
/* RCC (WCH naming: CTLR/CFGR0/... PCENR)                              */
/* ------------------------------------------------------------------ */
typedef struct {
    __IO uint32_t CTLR;      /* 0x00 CR      */
    __IO uint32_t CFGR0;     /* 0x04 CFGR    */
    __IO uint32_t INTR;      /* 0x08 CIR     */
    __IO uint32_t APB2PRSTR; /* 0x0C APB2RSTR*/
    __IO uint32_t APB1PRSTR; /* 0x10 APB1RSTR*/
    __IO uint32_t AHBPCRSTR; /* 0x14 AHBENR  */
    __IO uint32_t APB2PCENR; /* 0x18 APB2ENR */
    __IO uint32_t APB1PCENR; /* 0x1C APB1ENR */
    __IO uint32_t AHBPCCENR; /* 0x20 BDCR    */
    __IO uint32_t RSTSCKR;   /* 0x24 CSR     */
} RCC_TypeDef;
#define RCC ((RCC_TypeDef *)0x40021000)

/* APB2PCENR bits */
#define RCC_APB2Periph_AFIO     BIT(0)
#define RCC_APB2Periph_GPIOA    BIT(2)
#define RCC_APB2Periph_GPIOB    BIT(3)
#define RCC_APB2Periph_GPIOC    BIT(4)
#define RCC_APB2Periph_ADC1     BIT(9)
#define RCC_APB2Periph_TIM1     BIT(11)
#define RCC_APB2Periph_SPI1     BIT(12)
#define RCC_APB2Periph_USART1   BIT(14)
/* APB1PCENR bits */
#define RCC_APB1Periph_TIM2     BIT(0)
#define RCC_APB1Periph_TIM3     BIT(1)
#define RCC_APB1Periph_TIM4     BIT(2)
#define RCC_APB1Periph_SPI2     BIT(14)
#define RCC_APB1Periph_USART2   BIT(17)
#define RCC_APB1Periph_USART3   BIT(18)

/* ------------------------------------------------------------------ */
/* USART                                                               */
/* ------------------------------------------------------------------ */
typedef struct {
    __IO uint32_t STATR;   /* 0x00 SR  */
    __IO uint32_t DATAR;   /* 0x04 DR  */
    __IO uint32_t BRR;     /* 0x08     */
    __IO uint32_t CTLR1;   /* 0x0C CR1 */
    __IO uint32_t CTLR2;   /* 0x10 CR2 */
    __IO uint32_t CTLR3;   /* 0x14 CR3 */
    __IO uint32_t GUATR;   /* 0x18 GTPR*/
} USART_TypeDef;

#define USART1 ((USART_TypeDef *)0x40013800)
#define USART2 ((USART_TypeDef *)0x40004400)
#define USART3 ((USART_TypeDef *)0x40004800)

/* USART flags (STATR) */
#define USART_FLAG_TC   BIT(6)   /* transmit complete */
#define USART_FLAG_TXE  BIT(7)   /* tx empty */
#define USART_FLAG_RXNE BIT(5)   /* rx not empty */

/* USART CTLR1 bits */
#define USART_CTLR1_UE      BIT(13)
#define USART_CTLR1_WAKE    BIT(14)
#define USART_CTLR1_RXNEIE  BIT(5)
#define USART_CTLR1_TE      BIT(3)
#define USART_CTLR1_RE      BIT(2)

/* ------------------------------------------------------------------ */
/* SPI                                                                 */
/* ------------------------------------------------------------------ */
typedef struct {
    __IO uint32_t CTLR1;    /* 0x00 CR1 */
    __IO uint32_t CFGR1;    /* 0x04 CR2 */
    __IO uint32_t STATR;    /* 0x08 SR  */
    __IO uint32_t DATAR;    /* 0x0C DR  */
    __IO uint32_t CRCPOLYR; /* 0x10     */
    __IO uint32_t RXCRCR;   /* 0x14     */
    __IO uint32_t TXCRCR;   /* 0x18     */
    __IO uint32_t I2SCFGR;  /* 0x1C     */
    __IO uint32_t I2SPR;    /* 0x20     */
} SPI_TypeDef;

#define SPI1 ((SPI_TypeDef *)0x40013000)
#define SPI2 ((SPI_TypeDef *)0x40003800)

/* SPI CTLR1 bits */
#define SPI_CTLR1_BIDIMODE BIT(15)
#define SPI_CTLR1_BIDIOE   BIT(14)
#define SPI_CTLR1_CRCEN    BIT(13)
#define SPI_CTLR1_CRCNEXT  BIT(12)
#define SPI_CTLR1_DFF      BIT(11)
#define SPI_CTLR1_RXONLY   BIT(10)
#define SPI_CTLR1_SSM      BIT(9)
#define SPI_CTLR1_SSI      BIT(8)
#define SPI_CTLR1_LSBFIRST BIT(7)
#define SPI_CTLR1_SPE      BIT(6)
#define SPI_CTLR1_MSTR     BIT(2)
#define SPI_CTLR1_CPOL     BIT(1)
#define SPI_CTLR1_CPHA     BIT(0)
/* SPI CFGR1 (CR2) bits */
#define SPI_CFGR1_TXDMAEN  BIT(1)
#define SPI_CFGR1_RXDMAEN  BIT(0)
#define SPI_CFGR1_SSOE     BIT(2)
#define SPI_CFGR1_RXNEIE   BIT(6)
#define SPI_CFGR1_TXEIE    BIT(7)
/* SPI STATR bits */
#define SPI_STATR_RXNE     BIT(0)
#define SPI_STATR_TXE      BIT(1)
#define SPI_STATR_BSY      BIT(7)

/* ------------------------------------------------------------------ */
/* TIM (STM32F1-style; base 0x40000000 = TIM2)                         */
/* ------------------------------------------------------------------ */
typedef struct {
    __IO uint32_t CTLR1;     /* 0x00 */
    __IO uint32_t CTLR2;     /* 0x04 */
    __IO uint32_t SMCFGR;    /* 0x08 */
    __IO uint32_t DMAINTENR; /* 0x0C */
    __IO uint32_t INTFR;     /* 0x10 */
    __IO uint32_t EVGR;      /* 0x14 */
    __IO uint32_t CHCTLR1;   /* 0x18 */
    __IO uint32_t CHCTLR2;   /* 0x1C */
    __IO uint32_t CCER;      /* 0x20 */
    __IO uint32_t CNT;       /* 0x24 */
    __IO uint32_t PSC;       /* 0x28 */
    __IO uint32_t ATRLR;     /* 0x2C */
    __IO uint32_t CCHR;      /* 0x30 */
    __IO uint32_t CCR1;      /* 0x34 */
    __IO uint32_t CCR2;      /* 0x38 */
    __IO uint32_t CCR3;      /* 0x3C */
    __IO uint32_t CCR4;      /* 0x40 */
    __IO uint32_t DMACFGR;   /* 0x44 */
    __IO uint32_t DMAADR;    /* 0x48 */
} TIM_TypeDef;

#define TIM2 ((TIM_TypeDef *)0x40000000)
#define TIM3 ((TIM_TypeDef *)0x40000400)
#define TIM4 ((TIM_TypeDef *)0x40000800)

#define TIM_DMAINTENR_UIE  BIT(0)
#define TIM_CTLR1_CEN      BIT(0)
#define TIM_CTLR1_ARPE     BIT(7)
#define TIM_INTFR_UIF      BIT(0)

/* ------------------------------------------------------------------ */
/* Core register access (RISC-V only)                                  */
/* ------------------------------------------------------------------ */
#if defined(__riscv) || defined(RISCV)

#define __get_MTVEC()        ({ uint32_t v; __asm volatile("csrr %0, mtvec" : "=r"(v)); v; })
#define __set_MTVEC(v)       __asm volatile("csrw mtvec, %0" :: "r"(v))
#define __get_MSTATUS()      ({ uint32_t v; __asm volatile("csrr %0, mstatus" : "=r"(v)); v; })
#define __set_MSTATUS(v)     __asm volatile("csrw mstatus, %0" :: "r"(v))

/* Enable global interrupt (MIE + MPIE, WCH convention: csrs 0x800, 0x88) */
static inline void __enable_irq(void)
{
    __asm volatile("csrs 0x800, %0" :: "r"((uint32_t)0x88));
}

static inline void __disable_irq(void)
{
    __asm volatile("csrc 0x800, %0" :: "r"((uint32_t)0x88));
}

static inline void NVIC_EnableIRQ(IRQn_Type IRQn)
{
    NVIC->IENR[((uint32_t)IRQn) >> 5] = BIT(((uint32_t)IRQn) & 0x1F);
}

static inline void NVIC_DisableIRQ(IRQn_Type IRQn)
{
    NVIC->IRER[((uint32_t)IRQn) >> 5] = BIT(((uint32_t)IRQn) & 0x1F);
    __asm volatile("fence.i");
}

static inline void NVIC_SystemReset(void)
{
    NVIC->CFGR = NVIC_KEY3 | BIT(7);
}

static inline void __NOP(void)
{
    __asm volatile("nop");
}

#else  /* non-RISC-V: make code host-syntax-check friendly */
#define __get_MTVEC()    0u
#define __set_MTVEC(v)   ((void)(v))
#define __get_MSTATUS()  0u
#define __set_MSTATUS(v) ((void)(v))
static inline void __enable_irq(void) { }
static inline void __disable_irq(void) { }
static inline void NVIC_EnableIRQ(IRQn_Type IRQn) { (void)IRQn; }
static inline void NVIC_DisableIRQ(IRQn_Type IRQn) { (void)IRQn; }
static inline void NVIC_SystemReset(void) { }
static inline void __NOP(void) { }
#endif

#ifdef __cplusplus
}
#endif

#endif /* __CH32V20X_H__ */
