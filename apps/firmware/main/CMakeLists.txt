idf_component_register(
    SRCS
        "main.cpp"
        "network.cpp"
        "display.cpp"
        "button.cpp"
        "power.cpp"
        "livekit_transport.cpp"
    INCLUDE_DIRS "."
    REQUIRES
        driver
        esp_event
        esp_netif
        esp_wifi
        json
        nvs_flash
        livekit
)
