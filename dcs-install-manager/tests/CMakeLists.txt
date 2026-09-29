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

set(RULES_SOURCES_FOR_TEST
    ${CMAKE_SOURCE_DIR}/src/core/rules/ModuleRule.h
    ${CMAKE_SOURCE_DIR}/src/core/rules/ModuleRule.cpp
    ${CMAKE_SOURCE_DIR}/src/core/rules/ModuleRuleStore.h
    ${CMAKE_SOURCE_DIR}/src/core/rules/ModuleRuleStore.cpp
    ${CMAKE_SOURCE_DIR}/src/core/rules/ModuleRuleResolver.h
    ${CMAKE_SOURCE_DIR}/src/core/rules/ModuleRuleResolver.cpp
)

qt_add_executable(tst_moduleruleresolver tst_moduleruleresolver.cpp ${RULES_SOURCES_FOR_TEST})
target_link_libraries(tst_moduleruleresolver PRIVATE Qt6::Core Qt6::Test)
target_include_directories(tst_moduleruleresolver PRIVATE ${CMAKE_SOURCE_DIR}/src)

add_test(NAME tst_moduleruleresolver COMMAND tst_moduleruleresolver)

set(PROCESSGUARD_SOURCES_FOR_TEST
    ${CMAKE_SOURCE_DIR}/src/core/safety/DcsProcessGuard.h
    ${CMAKE_SOURCE_DIR}/src/core/safety/DcsProcessGuard.cpp
)

qt_add_executable(tst_dcsprocessguard tst_dcsprocessguard.cpp ${PROCESSGUARD_SOURCES_FOR_TEST})
target_link_libraries(tst_dcsprocessguard PRIVATE Qt6::Core Qt6::Test)
target_include_directories(tst_dcsprocessguard PRIVATE ${CMAKE_SOURCE_DIR}/src)

add_test(NAME tst_dcsprocessguard COMMAND tst_dcsprocessguard)

set(MODINSTALLER_SOURCES_FOR_TEST
    ${CMAKE_SOURCE_DIR}/src/core/catalog/ModEntry.h
    ${CMAKE_SOURCE_DIR}/src/core/catalog/ModEntry.cpp
    ${CMAKE_SOURCE_DIR}/src/core/catalog/ModCatalog.h
    ${CMAKE_SOURCE_DIR}/src/core/catalog/ModCatalog.cpp
    ${CMAKE_SOURCE_DIR}/src/core/install/FileOpsUtil.h
    ${CMAKE_SOURCE_DIR}/src/core/install/FileOpsUtil.cpp
    ${CMAKE_SOURCE_DIR}/src/core/install/InstallStateStore.h
    ${CMAKE_SOURCE_DIR}/src/core/install/InstallStateStore.cpp
    ${CMAKE_SOURCE_DIR}/src/core/install/ModInstaller.h
    ${CMAKE_SOURCE_DIR}/src/core/install/ModInstaller.cpp
    ${CMAKE_SOURCE_DIR}/src/core/safety/DcsProcessGuard.h
    ${CMAKE_SOURCE_DIR}/src/core/safety/DcsProcessGuard.cpp
)

qt_add_executable(tst_modinstaller tst_modinstaller.cpp ${MODINSTALLER_SOURCES_FOR_TEST})
target_link_libraries(tst_modinstaller PRIVATE Qt6::Core Qt6::Test)
target_include_directories(tst_modinstaller PRIVATE ${CMAKE_SOURCE_DIR}/src)

add_test(NAME tst_modinstaller COMMAND tst_modinstaller)

set(PATHLOCATOR_SOURCES_FOR_TEST
    ${CMAKE_SOURCE_DIR}/src/core/paths/DcsPathLocator.h
    ${CMAKE_SOURCE_DIR}/src/core/paths/DcsPathLocator.cpp
)

qt_add_executable(tst_dcspathlocator tst_dcspathlocator.cpp ${PATHLOCATOR_SOURCES_FOR_TEST})
target_link_libraries(tst_dcspathlocator PRIVATE Qt6::Core Qt6::Test)
target_include_directories(tst_dcspathlocator PRIVATE ${CMAKE_SOURCE_DIR}/src)

add_test(NAME tst_dcspathlocator COMMAND tst_dcspathlocator)

set(SETTINGSMANAGER_SOURCES_FOR_TEST
    ${CMAKE_SOURCE_DIR}/src/core/settings/SettingsManager.h
    ${CMAKE_SOURCE_DIR}/src/core/settings/SettingsManager.cpp
)

qt_add_executable(tst_settingsmanager tst_settingsmanager.cpp ${SETTINGSMANAGER_SOURCES_FOR_TEST})
target_link_libraries(tst_settingsmanager PRIVATE Qt6::Core Qt6::Test)
target_include_directories(tst_settingsmanager PRIVATE ${CMAKE_SOURCE_DIR}/src)

add_test(NAME tst_settingsmanager COMMAND tst_settingsmanager)
