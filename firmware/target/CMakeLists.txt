# The nRF Connect SDK application: the nine HAL functions, and a main() that
# hands them to the logic in ../.
#
# ⭐ THE LOGIC IS NOT COPIED IN, IT IS COMPILED IN. ../sb_power.c and its
# neighbours are the same files firmware/Makefile builds for the host tests, and
# they appear once. A target build that forked them would let the tested version
# and the shipped version drift, which is the failure this whole arrangement
# exists to prevent.
cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(smartbag)

target_include_directories(app PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/..)

target_sources(app PRIVATE
    src/main.c
    src/sb_hal_zephyr.c
    src/npm1300.c
    ../smartbag.c
    ../sb_power.c
    ../sb_sensors.c
    ../sb_fsr.c
    ../sb_ble.c
)
