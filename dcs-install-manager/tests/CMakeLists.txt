find_package(Qt6 REQUIRED COMPONENTS Test)

set(CATALOG_SOURCES_FOR_TEST
    ${CMAKE_SOURCE_DIR}/src/core/catalog/ModEntry.h
    ${CMAKE_SOURCE_DIR}/src/core/catalog/ModEntry.cpp
    ${CMAKE_SOURCE_DIR}/src/core/catalog/ModCatalog.h
    ${CMAKE_SOURCE_DIR}/src/core/catalog/ModCatalog.cpp
)

qt_add_executable(tst_modcatalog tst_modcatalog.cpp ${CATALOG_SOURCES_FOR_TEST})
target_link_libraries(tst_modcatalog PRIVATE Qt6::Core Qt6::Test)
target_include_directories(tst_modcatalog PRIVATE ${CMAKE_SOURCE_DIR}/src)

add_test(NAME tst_modcatalog COMMAND tst_modcatalog)
