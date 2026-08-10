# Memora hardware component checks

Standalone ESP-IDF project for validating the physical components before wiring
them into the full firmware.

## Checks

- OLED basic SSD1306-compatible I²C pattern on D4/GPIO5 and D5/GPIO6.
- OV2640 camera initialization and JPEG frame capture over the XIAO ESP32-S3 Sense
  DVP camera bus.

The serial monitor prints a PASS/FAIL summary and then logs camera frame dimensions
and byte lengths every two seconds. The OLED alternates between two patterns after
each capture.

## Wiring

| Component | XIAO ESP32-S3 pin |
| --- | --- |
| OLED VCC | 3V3 |
| OLED GND | GND |
| OLED SDA | D4 / GPIO5 |
| OLED SCL | D5 / GPIO6 |

The camera uses the fixed Sense expansion-board pins in
`main/hardware.h`; no external camera wiring is required when the OV2640 module is
seated in the Sense expansion board.

## Build and flash

From the repository root, with ESP-IDF 5.4+ activated:

```bash
idf.py -C testing_components set-target esp32s3
idf.py -C testing_components build
idf.py -C testing_components flash monitor
```

The project enables PSRAM because camera frame buffers require external RAM at the
selected resolution. The camera driver dependency is pinned to the current stable
`2.1.x` line. The OLED check assumes a 128x64 SSD1306-compatible module at address
`0x3C`.
