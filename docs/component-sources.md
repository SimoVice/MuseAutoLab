# Component sources and price scope

Checked **2026-10-27**. These are public USD list-price observations for a concept-design comparison. The application uses a committed snapshot so the same revision can reproduce its arithmetic. It does not retrieve live offers when a component is selected.

| Candidate | Unit price (USD) | Primary price source |
| --- | ---: | --- |
| Pololu NEMA 14 motor, 1 A/phase, item 1209 | 35.12 | [Pololu](https://www.pololu.com/product/1209) |
| Pololu NEMA 14 motor, 0.5 A/phase, item 1208 | 30.32 | [Pololu](https://www.pololu.com/product/1208) |
| DRV8825 driver, item 2133 | 15.95 | [Pololu](https://www.pololu.com/product/2133) |
| A4988 driver, item 1182 | 8.95 | [Pololu](https://www.pololu.com/product/1182) |
| Raspberry Pi Pico without headers, item 4864 | 4.00 | [Adafruit](https://www.adafruit.com/product/4864) |
| Raspberry Pi Pico H with headers, item 5525 | 5.00 | [Adafruit](https://www.adafruit.com/product/5525) |
| Peltier, heatsink and fan assembly, item 1335 | 34.95 | [Adafruit](https://www.adafruit.com/product/1335) |
| DS18B20 waterproof probe, item 381 | 9.95 | [Adafruit](https://www.adafruit.com/product/381) |
| DS18B20 bare sensor, item 374 | 3.95 | [Adafruit](https://www.adafruit.com/product/374) |
| Opentrons Temperature Module GEN2 | From 3,975.00 | [Opentrons module catalogue](https://opentrons.com/products/categories/modules) |

Prices do not establish availability in a particular country. Pololu permits backorders for the cited motors/drivers. Pico variant pages show inconsistent stock information; the Pico H listing shows out of stock. Check availability and request territory-specific pricing before procurement. No order or reservation is made by MuseAutoLab.

## What the comparison includes

Four motors and four drivers are a proposed X/Y/Z/plunger architecture, not a proven mechanism. Motor torque, transmission, travel, fixtures and firmware need engineering. Driver swaps need electrical, current-limit and timing checks. Both controller candidates require a carrier and firmware integration.

The displayed subtotal includes only selected offers with known prices. Unspecified frame/deck, linear motion, pipette/tip handling, printed fixtures/labware and power/wiring remain visibly unpriced. Taxes, shipping, import duties, assembly and validation are excluded. Selecting a starting price makes the subtotal a lower bound. Reusing existing equipment is not silently treated as a zero-cost purchase.

## Cooling proposals

The DIY candidate includes a Peltier element, heatsink and fan. Its supplier describes a roughly 90 × 90 mm heatsink, 78 mm total height, 12 V operation, 60 W nominal and 72 W maximum. The proposed **150 × 120 × 130 mm** enclosure shown in MuseAutoLab is an assumed integration envelope, including space for insulation and mounting. A suitable supply with margin, regulation, cold block and condensation management are still required and unpriced. No target-temperature performance is established.

The alternative [Opentrons module](https://opentrons.com/products/temperature-module-gen2) is a complete commercial temperature module. Its manufacturer specifies a **194 × 90 × 84 mm** body and a 4–95 °C operating range. The [current product specifications](https://docs.opentrons.com/temperature-module/product-specs/) describe a choice of thermal block and distinguish plate temperature from sample temperature. Confirm the quoted configuration, included accessories and custom integration requirements; this module has not been validated with MuseAutoLab.

In this prototype the cold bay is attached beside the preparation area and samples are transferred manually. The temperature is a requested/proposed target, not a sensor measurement or thermal simulation. The existing pipetting animation does not imply automatic sample transfer into cold storage.

## Refreshing the snapshot

Reopen each primary listing, record its date, currency, price basis, quantity tier and availability, and update the catalogue data and this source note together. Preserve unknown prices as null and check alternative-specific integration notes. Run the catalogue, domain and browser checks before committing. Do not replace missing offers with invented estimates or convert currencies without a separately dated exchange-rate source.
