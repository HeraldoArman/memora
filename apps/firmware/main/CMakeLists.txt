idf_component_register(
    SRCS
        "main.cpp"
        "media.cpp"
        "jpeg_ingest.cpp"
        "network.cpp"
        "display.cpp"
        "button.cpp"
        "power.cpp"
        "livekit_transport.cpp"
    INCLUDE_DIRS "."
    REQUIRES
        driver
        esp_camera
        esp_capture
        esp_event
        esp_http_client
        esp_netif
        esp_wifi
        json
        nvs_flash
        livekit
    PRIV_REQUIRES
        esp_audio_codec
)

# IDF 5.5's I2S and esp32-camera components can leave GDMA references for the
# final link. Keep the related archives in a linker GROUP so ld rescans them
# when gdma.c is pulled from esp_hw_support.
set(gdma_linker_script "${CMAKE_CURRENT_BINARY_DIR}/gdma_linker.ld")
file(GENERATE
    OUTPUT "${gdma_linker_script}"
    CONTENT "GROUP(esp-idf/esp_hw_support/libesp_hw_support.a esp-idf/hal/libhal.a esp-idf/soc/libsoc.a esp-idf/esp_driver_i2s/libesp_driver_i2s.a esp-idf/espressif__esp32-camera/libespressif__esp32-camera.a)\n"
)
target_link_libraries(${COMPONENT_LIB} INTERFACE "${gdma_linker_script}")
