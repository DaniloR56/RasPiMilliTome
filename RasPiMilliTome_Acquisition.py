#! /usr/bin/env python
# -*- coding: utf-8 -*-
#======================================================================
#
#  NAME:  HandSlicerControlDisp240x240V2.3.py
#
#======================================================================
#  DESCRIPTION:
#  INPUT:
#  OUTPUT:
#======================================================================
#  REQU. FUNCTIONS:
#======================================================================
# Author:        Danilo Roccatano <danilo.roccatano@gmail.com>
# Version:       0.1
# Copyright (C): 2025 Danilo Roccatano
# Modified On    2025-12-15 16:09
# Created:       2025-12-15 16:09
# Distributed under terms of the MIT license.
#======================================================================
#

#!/usr/bin/env python3

import RPi.GPIO as GPIO
from picamera import PiCamera
from time import sleep
from PIL import Image, ImageDraw, ImageFont
import st7735
import os
import time

# ================= CONFIG =================
ROTATION_SENSOR_PIN = 18
BUTTON_PIN = 27

LED_R_PIN = 5
LED_G_PIN = 6
LED_B_PIN = 12

ROTATION_LIMIT = 3
PHOTO_FOLDER = "/home/danilo/photos"
os.makedirs(PHOTO_FOLDER, exist_ok=True)

PREVIEW_PATH = os.path.join(PHOTO_FOLDER, "preview.jpg")

# Pi Camera v1 resolutions
PREVIEW_RES = (240, 240)
FULL_RES    = (2592, 1944)

# ================= DISPLAY =================
DC = 24
RST = 25
BL  = 19

disp = st7735.ST7735(
    port=0,
    cs=0,
    dc=DC,
    rst=RST,
    backlight=BL,
    spi_speed_hz=16000000,
    width=240,
    height=240,
    rotation=270,
    offset_left=80,
    offset_top=0,
)

disp.begin()

# ================= GPIO =================
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

GPIO.setup(ROTATION_SENSOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(BUTTON_PIN, GPIO.IN)  # ACTIVE-HIGH 3-pin module

GPIO.setup(LED_R_PIN, GPIO.OUT)
GPIO.setup(LED_G_PIN, GPIO.OUT)
GPIO.setup(LED_B_PIN, GPIO.OUT)

# ================= CAMERA =================
camera = PiCamera()
camera.resolution = PREVIEW_RES
camera.rotation = 270
camera.framerate = 24
sleep(2)

# ================= LED =================
def set_led(r, g, b):
    GPIO.output(LED_R_PIN, r)
    GPIO.output(LED_G_PIN, g)
    GPIO.output(LED_B_PIN, b)

def led_red():    set_led(1, 0, 0)
def led_orange(): set_led(1, 1, 0)
def led_green():  set_led(0, 1, 0)
def led_off():    set_led(0, 0, 0)

# ================= BUTTON =================
def button_event():
    if not GPIO.input(BUTTON_PIN):
        return None

    t0 = time.time()
    while GPIO.input(BUTTON_PIN):
        time.sleep(0.01)

    dt = time.time() - t0
    return "long" if dt > 1.0 else "short"

# ================= TFT DRAW =================
font = ImageFont.load_default()

def draw_screen(image=None, title="", bottom_left="", bottom_right=""):
    canvas = Image.new("RGB", (240, 240), "black")

    if image:
        canvas.paste(image, (0, 0))

    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 240, 22), fill="black")
    draw.rectangle((0, 218, 240, 240), fill="black")

    draw.text((4, 4), title, fill="white", font=font)
    draw.text((4, 220), bottom_left, fill="white", font=font)
    draw.text((140, 220), bottom_right, fill="white", font=font)

    disp.display(canvas)

# ================= SAVE (FULL RES) =================
def save_photo(index):
    filename = os.path.join(PHOTO_FOLDER, f"photo_{index:03d}.jpg")

    old_res = camera.resolution
    camera.resolution = FULL_RES
    sleep(0.2)  # sensor settle

    camera.capture(filename, quality=95)

    camera.resolution = old_res
    sleep(0.1)

    return filename

# ================= STATES =================
STATE_READY = 0
STATE_LIVE  = 1
STATE_SAVE  = 2

state = STATE_READY
rotation_count = 0
photo_index = 1
prev_rot_state = 0

# ================= START =================
draw_screen(
    title="HAND SAND SLICER",
    bottom_left="READY",
    bottom_right="Rot 0/3"
)
led_red()

try:
    while True:
        rot_state = GPIO.input(ROTATION_SENSOR_PIN)

        # -------- READY: COUNT ROTATIONS --------
        if state == STATE_READY:
            led_red()

            if rot_state == 1 and prev_rot_state == 0:
                rotation_count += 1

            draw_screen(
                title="ROTATING",
                bottom_left=f"Rot {rotation_count}/{ROTATION_LIMIT}",
                bottom_right=""
            )

            if rotation_count >= ROTATION_LIMIT:
                state = STATE_LIVE

        # -------- LIVE PREVIEW --------
        elif state == STATE_LIVE:
            led_orange()

            camera.capture(PREVIEW_PATH, use_video_port=True)
            img = Image.open(PREVIEW_PATH).convert("RGB")

            draw_screen(
                image=img,
                title="PREVIEW",
                bottom_left="SHORT: SAVE",
                bottom_right="LONG: RETAKE"
            )

            event = button_event()
            if event == "short":
                state = STATE_SAVE
            elif event == "long":
                pass  # continue preview

        # -------- SAVE --------
        elif state == STATE_SAVE:
            led_green()

            filename = save_photo(photo_index)
            photo_index += 1

            draw_screen(
                title="SAVED",
                bottom_left=os.path.basename(filename),
                bottom_right=""
            )

            sleep(1.0)

            # wait for rotation contact to open
            while GPIO.input(ROTATION_SENSOR_PIN):
                sleep(0.05)

            rotation_count = 0
            state = STATE_READY

        prev_rot_state = rot_state
        sleep(0.05)

except KeyboardInterrupt:
    pass

finally:
    camera.close()
    led_off()
    disp.display(Image.new("RGB", (240, 240), "black"))
    GPIO.cleanup()

