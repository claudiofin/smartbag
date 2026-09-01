/* The camera, which is the one part of this product that is bought whole.
 *
 * ⭐ EVERY NUMBER IN THE .c COMES FROM ARDUCAM'S OWN TWO DOCUMENTS. The register
 * table is Table 1 of the Arducam Mega SPI Camera Series Application Note; the
 * command bytes, the mask meanings and the burst-read shape are the SDK's own
 * ArducamCamera.c. Both are cited at the definitions. Nothing here was guessed
 * from what a camera "usually" does, because a camera that is usually right is
 * a camera that returns a frame of noise on the bench and no error anywhere.
 *
 * ⛔ AND THE MODULE CANNOT PRODUCE GREY, WHICH IS WHAT THE MODEL WANTS.
 * Register 0x20 offers JPEG, RGB and YUV and nothing else — so the frame comes
 * over the wire as RGB565 and is reduced to luma here, on the processor. That
 * costs 96x96 extra bytes of SPI per frame and it is why ml/inference_budget.py
 * now charges the burst at two bytes a pixel instead of one.
 *
 * ⚠️ THE 3MP HAS TWO RESOLUTION ENCODINGS AND WHICH ONE IS RIGHT DEPENDS ON THE
 * SENSOR ID. Arducam's SDK maps the mode enum through legacyMode() for any part
 * reporting below 0x85 and writes the enum straight through above it. The probe
 * reads the ID and remembers which, because getting it wrong asks a 96x96
 * capture for 1600x1200 and blows the capture timeout with no error at all.
 */
#ifndef SB_CAMERA_H
#define SB_CAMERA_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "sb_hal.h"

/* ⚠️ 96x96 because that is what ml/classify.py trains on, and the size is here
 * rather than in the caller so the buffer and the register value cannot drift
 * apart. RGB565 on the wire, one byte a pixel once it is luma. */
#define SB_CAM_W 96
#define SB_CAM_H 96
#define SB_CAM_PIXELS (SB_CAM_W * SB_CAM_H)
#define SB_CAM_WIRE_BYTES (SB_CAM_PIXELS * 2)

/* ⚠️ 8 MHz is the module's ceiling (hardware/bom.py), so 18432 bytes take
 * 18.4 ms. 200 ms is ten times that and still half of smartbag.c's 400 ms
 * capture timeout, which has to cover three frames. */
#define SB_CAM_CAPTURE_TIMEOUT_MS 200

/* The module's own boot time before it answers on SPI. Arducam's examples wait
 * for the sensor-state register rather than a fixed delay; this is the deadline
 * on that wait. */
#define SB_CAM_READY_TIMEOUT_MS 500

typedef enum {
    SB_CAM_OK = 0,
    SB_CAM_NO_REPLY,      /* the bus transfer itself failed                  */
    SB_CAM_BAD_ID,        /* something answered, and it is not a Mega        */
    SB_CAM_TIMEOUT,       /* asked for a frame, never got the done flag      */
    SB_CAM_SHORT,         /* the FIFO held fewer bytes than a frame          */
    SB_CAM_NO_ROOM,       /* the caller's buffer is too small                */
} sb_cam_status;

typedef struct {
    uint8_t id;           /* CAM_REG_SENSOR_ID, 0x40                         */
    bool legacy;          /* id < 0x85: the resolution enum needs remapping  */
    bool ready;
    uint32_t frames, timeouts, short_frames;
} sb_camera;

/* Reset the module, read its identity and set 96x96 RGB565. Safe to call again;
 * it is the whole of bring-up. */
sb_cam_status sb_cam_probe(sb_camera *c, const sb_hal *hal);

/* One frame, in the two halves it is really made of.
 *
 * ⛔ THE SPLIT IS NOT TIDINESS, IT IS 600 mW. The exposure ends the moment the
 * module raises its capture-done flag; everything after that is an image that
 * already exists being carried across an 8 MHz bus, 18 kB of it, 18 ms a frame.
 * The illuminators have to be on for the first half and must not be on for the
 * second, and a single capture() call gives the caller nowhere to put that. */
sb_cam_status sb_cam_expose(sb_camera *c, const sb_hal *hal);
sb_cam_status sb_cam_fetch(sb_camera *c, const sb_hal *hal, uint8_t *wire,
                           size_t wire_cap, uint8_t *grey);

/* Both halves, for callers that do not have illuminators to worry about — the
 * bench, and test_sb_camera.c. `wire` receives SB_CAM_WIRE_BYTES of RGB565 and
 * must be at least that large; `grey` receives SB_CAM_PIXELS of luma. */
sb_cam_status sb_cam_capture(sb_camera *c, const sb_hal *hal, uint8_t *wire,
                             size_t wire_cap, uint8_t *grey);

/* Put the sensor into its power-down state (register 0x02 bit 1) and take it
 * out again. ⚠️ thermal/budget.py charges the camera 56-136 mA while awake; it
 * is the largest current in the design and it is only allowed to exist inside
 * the capture window. */
void sb_cam_sleep(sb_camera *c, const sb_hal *hal);
void sb_cam_wake(sb_camera *c, const sb_hal *hal);

/* RGB565 big-endian on the wire to 8-bit luma. Exposed for its own test: the
 * coefficients are ITU-R BT.601, in integer form, and a channel swap here is
 * invisible on the bench and fatal to recognition. */
void sb_cam_rgb565_to_grey(const uint8_t *wire, size_t pixels, uint8_t *grey);

#endif /* SB_CAMERA_H */
