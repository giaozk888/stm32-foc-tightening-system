idf_component_register(SRCS "main.c" "router_frame.c" "gateway.c" "modbus_ro.c"
                           "../../firmware_common/network_v1.c"
                       INCLUDE_DIRS "." "../../firmware_common"
                       REQUIRES esp_driver_uart esp_wifi esp_event esp_netif esp_http_client
                                esp_timer mbedtls nvs_flash lwip)
if(CONFIG_GATEWAY_ROUTER_ENABLE)
    target_sources(${COMPONENT_LIB} PRIVATE "router_tcp.c"
        "../../firmware_common/router_network.c"
        "../../foc2_app_a/Core/Src/router.c")
    target_compile_definitions(${COMPONENT_LIB} PRIVATE ROUTER_READ_ONLY_NETWORK=1)
endif()
if(CONFIG_GATEWAY_ROUTER_RPC_ENABLE)
    target_sources(${COMPONENT_LIB} PRIVATE "../../firmware_common/router_rpc_wire.c")
    target_compile_definitions(${COMPONENT_LIB} PRIVATE ROUTER_READ_ONLY_RPC=1)
endif()
if(CONFIG_GATEWAY_ROUTER_TRANSFER_ENABLE)
    target_sources(${COMPONENT_LIB} PRIVATE "../../firmware_common/router_transfer_wire.c")
    target_compile_definitions(${COMPONENT_LIB} PRIVATE ROUTER_READ_ONLY_TRANSFER=1)
endif()
