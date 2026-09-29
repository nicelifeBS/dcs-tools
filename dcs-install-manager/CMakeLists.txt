cmake_minimum_required(VERSION 3.21)
project(DcsInstallManager LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

# LGPL Qt: this project must stay dynamically linked against Qt (windeployqt-style
# deployment, Qt DLLs shipped alongside the exe). Do not switch to a static Qt build
# without re-checking LGPL compliance for this project.
#
# QuickDialogs2 backs the "import QtQuick.Dialogs" FolderDialog used by
# PathSetupForm.qml (milestone 5) for native folder-browse dialogs.
find_package(Qt6 REQUIRED COMPONENTS Core Quick QuickControls2 QuickDialogs2 Qml)

qt_standard_project_setup()

set(CORE_SOURCES
    src/core/catalog/ModEntry.h
    src/core/catalog/ModEntry.cpp
    src/core/catalog/ModCatalog.h
    src/core/catalog/ModCatalog.cpp
    src/core/catalog/ModCatalogModel.h
    src/core/catalog/ModCatalogModel.cpp
    src/core/rules/ModuleRule.h
    src/core/rules/ModuleRule.cpp
    src/core/rules/ModuleRuleStore.h
    src/core/rules/ModuleRuleStore.cpp
    src/core/rules/ModuleRuleModel.h
    src/core/rules/ModuleRuleModel.cpp
    src/core/rules/ModuleRuleResolver.h
    src/core/rules/ModuleRuleResolver.cpp
    src/core/install/FileOpsUtil.h
    src/core/install/FileOpsUtil.cpp
    src/core/install/InstallStateStore.h
    src/core/install/InstallStateStore.cpp
    src/core/install/ModInstaller.h
    src/core/install/ModInstaller.cpp
    src/core/safety/DcsProcessGuard.h
    src/core/safety/DcsProcessGuard.cpp
    src/core/paths/DcsPathLocator.h
    src/core/paths/DcsPathLocator.cpp
    src/core/settings/SettingsManager.h
    src/core/settings/SettingsManager.cpp
    src/app/ModuleRuleResolverAdapter.h
    src/app/ModuleRuleResolverAdapter.cpp
    src/app/ModInstallerAdapter.h
    src/app/ModInstallerAdapter.cpp
    src/app/DcsPathLocatorAdapter.h
    src/app/DcsPathLocatorAdapter.cpp
)

# Milestone 4: main.cpp is now a real QGuiApplication + QQmlApplicationEngine GUI, so
# WIN32 is back (it suppresses the console window on Windows for a GUI app).
qt_add_executable(DcsInstallManager
    WIN32
    src/main.cpp
    ${CORE_SOURCES}
)

# qt_add_qml_module's generated module tree lives at build/<URI>/, which collides
# with the executable's own default output path (build/<target-name>/) when the
# target and URI share a name, as they do here - so the executable's binary is
# relocated to build/bin/ to avoid that clash.
set_target_properties(DcsInstallManager PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)

# Theme.qml is the QML singleton (pragma Singleton) holding every color/radius/spacing
# token - see "Visual design / theming" in the plan. This must be set BEFORE
# qt_add_qml_module() is called, since that call reads the property while generating
# the module's qmldir (setting it afterward silently produces a non-singleton entry).
set_source_files_properties(src/qml/Theme.qml PROPERTIES QT_QML_SINGLETON_TYPE true)

qt_add_qml_module(DcsInstallManager
    URI DcsInstallManager
    VERSION 1.0
    QML_FILES
        src/qml/Main.qml
        src/qml/Theme.qml
        src/qml/components/FlatButton.qml
        src/qml/components/FlatTextField.qml
        src/qml/components/FlatComboBox.qml
        src/qml/components/FlatCheckBox.qml
        src/qml/components/ModCard.qml
        src/qml/components/StatusBadge.qml
        src/qml/components/ConfirmDialog.qml
        src/qml/components/PathSetupForm.qml
        src/qml/screens/CatalogView.qml
        src/qml/screens/AddEditEntryDialog.qml
        src/qml/screens/ModuleRulesView.qml
        src/qml/screens/AddEditRuleDialog.qml
        src/qml/screens/SettingsView.qml
)

qt_add_resources(DcsInstallManager "data"
    PREFIX "/data"
    BASE data
    FILES
        data/default-catalog.json
        data/default-module-rules.json
)

target_link_libraries(DcsInstallManager PRIVATE
    Qt6::Core Qt6::Quick Qt6::QuickControls2 Qt6::QuickDialogs2 Qt6::Qml
)
target_include_directories(DcsInstallManager PRIVATE src)

if(WIN32)
    # DcsPathLocator::detectSavedGamesRoot() uses SHGetKnownFolderPath (shell32) and
    # CoTaskMemFree (ole32); DcsPathLocator's Steam-library scan uses QSettings'
    # NativeFormat registry backend, already covered by Qt6::Core.
    target_link_libraries(DcsInstallManager PRIVATE shell32 ole32)
endif()

enable_testing()
add_subdirectory(tests)
